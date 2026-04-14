#!/usr/bin/env python3
"""
Module: PDF Parser
Purpose: Parse PDF task order documents into TaskOrder model.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 3.2, 14.1
"""

__version__ = "1.0.0"

import re
from pathlib import Path
from typing import Optional

from sentinel.tocr.models.enums import ParserConfidence, RevisionStatus
from sentinel.tocr.models.task_order import (
    QualityPlan,
    SubTask,
    TaskOrder,
)


class PDFParser:
    """
    PDF parser — extracted parse, medium confidence.

    Uses pdfplumber for text extraction. OCR-dependent PDFs flagged as
    low confidence.
    """

    def parse(self, source: Path) -> TaskOrder:
        """
        Parse PDF file into TaskOrder.

        Args:
            source: Path to PDF file.

        Returns:
            Parsed TaskOrder with appropriate parser_confidence.

        Raises:
            ImportError: If pdfplumber is not installed.
        """
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber is required for PDF parsing. "
                "Install with: pip install pdfplumber"
            )

        with pdfplumber.open(str(source)) as pdf:
            pages_text = []
            has_text = False
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    has_text = True
                pages_text.append(text)

            full_text = "\n".join(pages_text)

            # Determine confidence
            if not has_text:
                confidence = ParserConfidence.LOW  # OCR needed
            elif len(full_text) < 100:
                confidence = ParserConfidence.LOW
            else:
                confidence = ParserConfidence.MEDIUM

            tables = []
            for page in pdf.pages:
                page_tables = page.extract_tables() or []
                tables.extend(page_tables)

        return self._extract_task_order(full_text, tables, confidence, source)

    def _extract_task_order(
        self,
        text: str,
        tables: list,
        confidence: ParserConfidence,
        source: Path,
    ) -> TaskOrder:
        """Extract TaskOrder from PDF text and tables."""
        to_number = self._find_field(text, r"Task Order\s*(?:No\.?|Number)\s*:?\s*(\S+)")
        rev_number = self._find_field(text, r"Revision\s*(?:No\.?|Number)\s*:?\s*(\S+)")
        title = self._find_field(text, r"Title\s*:?\s*(.+?)(?:\n|$)")

        # Section extraction via regex
        description = self._extract_section(text, "Task Order Description", "Summary of Changes")
        summary = self._extract_section(text, "Summary of Changes", "Quality|Sub-Task|Funding")
        quality_text = self._extract_section(text, "Quality", "Emergency|Funding|Comments")

        software_scope = bool(re.search(r"\b(software|AI|machine learning)\b", description, re.I))

        quality_plan = QualityPlan(
            text=quality_text,
            qms_required=bool(re.search(r"\b(QMS|8739)\b", quality_text, re.I)),
            software_scope=software_scope,
        ) if quality_text else None

        # Sub-tasks from tables
        sub_tasks = self._extract_sub_tasks_from_tables(tables)

        return TaskOrder(
            task_order_number=to_number or source.stem,
            revision_number=rev_number or "unknown",
            revision_status=RevisionStatus.DRAFT,
            title=title or "",
            task_order_description=description,
            scope_text=description,
            summary_of_changes=summary,
            sub_tasks=sub_tasks,
            quality_plan=quality_plan,
            parser_confidence=confidence,
            source_format="pdf",
        )

    def _find_field(self, text: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _extract_section(self, text: str, start: str, end: str) -> str:
        """Extract text between two section headers."""
        pattern = rf"{start}.*?\n(.*?)(?={end}|\Z)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def _extract_sub_tasks_from_tables(self, tables: list) -> list[SubTask]:
        """Extract sub-tasks from PDF tables."""
        sub_tasks = []
        for table in tables:
            if not table or len(table) < 2:
                continue
            header = [str(h or "").lower() for h in table[0]]
            # Match tables with sub-task headers: require both "sub" AND "task"
            # in the same cell, OR an "id" column.  Parenthesized to avoid
            # precedence bugs (and binds tighter than or).
            if not any(("sub" in h and "task" in h) or "id" in h for h in header):
                continue

            id_col = next((i for i, h in enumerate(header) if "id" in h or "sub" in h), None)
            desc_col = next((i for i, h in enumerate(header) if "desc" in h or "scope" in h), None)

            if id_col is None:
                continue

            for row in table[1:]:
                if not row or len(row) <= id_col:
                    continue
                cell_val = str(row[id_col] or "").strip()
                if not cell_val:
                    continue
                desc = str(row[desc_col] or "").strip() if desc_col is not None and len(row) > desc_col else ""
                sub_tasks.append(SubTask(sub_task_id=cell_val, description=desc))

        return sub_tasks
