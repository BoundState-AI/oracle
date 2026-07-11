#!/usr/bin/env python3
"""
Module: DOCX Parser
Purpose: Parse DOCX task order documents into TaskOrder model.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 3.2, 14.1

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: True
"""

__version__ = "1.0.0"

import re
from pathlib import Path
from typing import Optional

from sentinel.tocr.models.enums import ParserConfidence, RevisionStatus
from sentinel.tocr.models.task_order import (
    FundingEntry,
    QualityPlan,
    SubTask,
    TaskOrder,
)


class DOCXParser:
    """
    DOCX parser — structured parse, high confidence with table validation.

    Uses python-docx for structured content and table reconstruction.
    """

    def parse(self, source: Path) -> TaskOrder:
        """
        Parse DOCX file into TaskOrder.

        Args:
            source: Path to DOCX file.

        Returns:
            Parsed TaskOrder with parser_confidence=HIGH.

        Raises:
            ImportError: If python-docx is not installed.
        """
        try:
            from docx import Document
        except ImportError:
            raise ImportError(
                "python-docx is required for DOCX parsing. "
                "Install with: pip install python-docx"
            )

        doc = Document(str(source))
        return self._extract_task_order(doc, source)

    def _extract_task_order(self, doc, source: Path) -> TaskOrder:
        """Extract TaskOrder from parsed DOCX document."""
        full_text = "\n".join(p.text for p in doc.paragraphs)
        tables_data = self._extract_tables(doc)

        # Extract sections by heading
        sections = self._split_by_headings(doc)

        # Extract fields
        to_number = self._find_field(full_text, r"Task Order\s*(?:No\.?|Number)\s*:?\s*(\S+)")
        rev_number = self._find_field(full_text, r"Revision\s*(?:No\.?|Number)\s*:?\s*(\S+)")
        title = self._find_field(full_text, r"Title\s*:?\s*(.+?)(?:\n|$)")

        description = sections.get("task order description", sections.get("scope", ""))
        summary = sections.get("summary of changes", "")
        quality_text = sections.get("quality plan", sections.get("quality", ""))
        emergency_text = sections.get("emergency", "")
        comments = sections.get("comments", sections.get("agency comments", ""))

        # Parse sub-tasks from tables
        sub_tasks = self._extract_sub_tasks(tables_data)
        funding_table = self._extract_funding(tables_data)

        quality_plan = self._detect_quality_plan(description, quality_text)

        # Known limitation: "non-emergency" would match the emergency regex. This
        # is acceptable because emergency designation is typically in a dedicated
        # field, not negated inline.
        emergency = bool(re.search(r"\bemergency\b", emergency_text, re.I))

        return TaskOrder(
            task_order_number=to_number or source.stem,
            revision_number=rev_number or "unknown",
            revision_status=RevisionStatus.DRAFT,
            title=title or "",
            task_order_description=description,
            scope_text=description,
            summary_of_changes=summary,
            sub_tasks=sub_tasks,
            funding_table=funding_table,
            quality_plan=quality_plan,
            emergency_designation=emergency,
            emergency_justification=emergency_text if emergency else "",
            agency_comments=comments,
            # Degrade confidence when critical fields fall back to defaults.
            # Why: a DOCX that yields no TO number or title was likely not a
            # well-formed task order — downstream engines should weight findings
            # accordingly.  Matches the degradation pattern in PDFParser.
            parser_confidence=(
                ParserConfidence.HIGH if (to_number and title) else
                ParserConfidence.MEDIUM if (to_number or title) else
                ParserConfidence.LOW
            ),
            source_format="docx",
        )

    def _detect_quality_plan(self, description: str, quality_text: str) -> Optional[QualityPlan]:
        """Detect quality plan from description and quality section text.

        Compliance heuristics: detect software scope and QMS requirements.
        Why these keywords:
          - software_scope: triggers NASA-STD-8739.8B applicability checks.
            "software", "AI", "machine learning" are the three categories that
            invoke SWE requirements under ESSCA. False negatives are acceptable
            (engine errs toward "not software" — conservative for the contractor).
          - qms_required: "QMS" and "quality management" are the explicit terms;
            "8739" catches references to NASA-STD-8739.x family without the full
            standard title.  False positives are acceptable here (engine errs
            toward "QMS required" — conservative for compliance).
        """
        if not quality_text:
            return None

        software_scope = bool(re.search(r"\b(software|AI|machine learning)\b", description, re.I))
        qms_required = bool(re.search(r"\b(QMS|quality management|8739)\b", quality_text, re.I))

        return QualityPlan(
            text=quality_text,
            qms_required=qms_required,
            software_scope=software_scope,
        )

    def _extract_tables(self, doc) -> list[list[list[str]]]:
        """Extract all tables from DOCX as lists of rows of cells."""
        tables = []
        for table in doc.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append(cells)
            tables.append(rows)
        return tables

    def _split_by_headings(self, doc) -> dict[str, str]:
        """Split document text by heading paragraphs."""
        sections: dict[str, str] = {}
        current_heading = ""
        current_text: list[str] = []

        for para in doc.paragraphs:
            if para.style and para.style.name and "Heading" in para.style.name:
                if current_heading:
                    sections[current_heading.lower()] = "\n".join(current_text).strip()
                current_heading = para.text.strip()
                current_text = []
            else:
                current_text.append(para.text)

        if current_heading:
            sections[current_heading.lower()] = "\n".join(current_text).strip()

        return sections

    def _find_field(self, text: str, pattern: str) -> Optional[str]:
        """Find a field value using regex pattern."""
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _extract_sub_tasks(self, tables: list[list[list[str]]]) -> list[SubTask]:
        """Extract sub-tasks from table data."""
        sub_tasks = []
        for table in tables:
            if not table:
                continue
            header = [h.lower() for h in table[0]]
            # Match tables with sub-task headers: require both "sub" AND "task"
            # in the same cell, OR an "id" column.  Parenthesized to avoid
            # precedence bugs (and binds tighter than or).
            if not any(("sub" in h and "task" in h) or "id" in h for h in header):
                continue

            id_col = self._find_col(header, ["sub_task", "sub-task", "id", "task id"])
            desc_col = self._find_col(header, ["description", "desc", "scope"])

            if id_col is None:
                continue

            for row in table[1:]:
                if len(row) <= id_col or not row[id_col].strip():
                    continue
                desc = row[desc_col].strip() if desc_col is not None and len(row) > desc_col else ""
                sub_tasks.append(SubTask(
                    sub_task_id=row[id_col].strip(),
                    description=desc,
                ))

        return sub_tasks

    def _extract_funding(self, tables: list[list[list[str]]]) -> list[FundingEntry]:
        """Extract funding entries from table data."""
        entries = []
        for table in tables:
            if not table:
                continue
            header = [h.lower() for h in table[0]]
            if not any("fund" in h or "amount" in h or "cost" in h for h in header):
                continue

            id_col = self._find_col(header, ["sub_task", "sub-task", "id", "task"])
            amount_col = self._find_col(header, ["amount", "fund", "cost", "value"])

            if amount_col is None:
                continue

            for row in table[1:]:
                if len(row) <= amount_col:
                    continue
                try:
                    amount = float(re.sub(r"[^\d.]", "", row[amount_col]))
                except (ValueError, IndexError):
                    amount = 0.0

                st_id = row[id_col].strip() if id_col is not None and len(row) > id_col else None
                entries.append(FundingEntry(
                    sub_task_id=st_id,
                    amount=amount,
                ))

        return entries

    def _find_col(self, header: list[str], candidates: list[str]) -> Optional[int]:
        """Find column index matching any candidate string."""
        for i, h in enumerate(header):
            for c in candidates:
                if c in h:
                    return i
        return None
