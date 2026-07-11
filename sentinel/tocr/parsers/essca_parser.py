#!/usr/bin/env python3
"""
Module: ESSCA Task Order Parser
Purpose: Parse ESSCA/MSFC task order DOCX documents into TaskOrder model.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Handles the specific ESSCA format:
- Metadata in Normal paragraphs (TO Number, Revision, etc.)
- Summary of Changes in Table 0
- Sub-tasks demarcated by 'SubTask Title' paragraph style
- Structured sections within each sub-task (Description, Skills, etc.)

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


class ESSCAParser:
    """
    ESSCA/MSFC task order DOCX parser — high confidence structured parse.

    Understands the ESSCA task order format used at MSFC including:
    - Header metadata (TO number, revision, contract, dates)
    - Summary of Changes table (always Table 0)
    - Sub-tasks delimited by 'SubTask Title' styled paragraphs
    - Per-sub-task sections: Description, Skills, Deliverables, Team
    """

    def parse(self, source: Path) -> TaskOrder:
        try:
            from docx import Document
        except ImportError:
            raise ImportError(
                "python-docx is required for DOCX parsing. "
                "Install with: pip install python-docx"
            )

        doc = Document(str(source))
        return self._extract(doc, source)

    def _extract(self, doc, source: Path) -> TaskOrder:
        paragraphs = [(p.style.name if p.style else "", p.text.strip()) for p in doc.paragraphs]

        # --- Header metadata ---
        meta = self._extract_metadata(paragraphs)

        # --- Task Order Description (between header and first sub-task) ---
        description = self._extract_description(paragraphs)

        # --- Summary of Changes from Table 0 ---
        summary_of_changes = self._extract_summary_table(doc)

        # --- Map deliverables tables to sub-tasks by document order ---
        deliverables_by_subtask = self._map_deliverables_to_subtasks(doc)

        # --- Sub-tasks ---
        sub_tasks = self._extract_sub_tasks(paragraphs, deliverables_by_subtask)

        # --- Funding from tables ---
        funding_table = self._extract_funding_tables(doc)

        # Compute total funding from funding entries
        total_funding = None
        if funding_table:
            total_funding = sum(e.amount for e in funding_table)

        # --- Quality plan ---
        quality_text = self._find_quality_plan(paragraphs, doc)
        quality_plan = self._detect_quality_plan(description, quality_text)

        # --- Revision status ---
        rev_status = RevisionStatus.RELEASED
        if meta.get("emergency", "").lower() == "yes":
            emergency = True
        else:
            emergency = False

        return TaskOrder(
            task_order_number=meta.get("to_number", source.stem),
            revision_number=meta.get("revision", "unknown"),
            revision_status=rev_status,
            title=meta.get("title", ""),
            task_order_description=description,
            scope_text=description,
            summary_of_changes=summary_of_changes,
            sub_tasks=sub_tasks,
            funding_table=funding_table,
            total_funding=total_funding,
            quality_plan=quality_plan,
            emergency_designation=emergency,
            emergency_justification="" if not emergency else meta.get("emergency_text", ""),
            agency_comments="",
            parser_confidence=ParserConfidence.HIGH,
            source_format="docx-essca",
            raw_fields={
                "skill": meta.get("skill", ""),
                "contract": meta.get("contract", ""),
                "team_lead": meta.get("team_lead", ""),
                "task_initiator": meta.get("task_initiator", ""),
            },
        )

    def _extract_metadata(self, paragraphs: list[tuple[str, str]]) -> dict:
        meta = {}
        for _, text in paragraphs[:25]:
            # TO Number:  EM04.04.01		Revision:  36
            m = re.match(r"TO\s+Number:\s*(\S+)\s+Revision:\s*(\S+)", text)
            if m:
                meta["to_number"] = m.group(1)
                meta["revision"] = f"Rev {m.group(2)}"
                continue

            m = re.match(r"TO\s+Title:\s*(.+)", text)
            if m:
                meta["title"] = m.group(1).strip()
                continue

            m = re.match(r"Contract\s+Number:\s*(\S+)", text)
            if m:
                meta["contract"] = m.group(1)
                continue

            m = re.match(r"Skill:\s*(.+)", text)
            if m:
                meta["skill"] = m.group(1).strip()
                continue

            m = re.match(r"Emergency:\s*(\S+)", text)
            if m:
                meta["emergency"] = m.group(1)
                continue

            m = re.match(r"Team\s+Lead:\s*(.+)", text)
            if m:
                meta["team_lead"] = m.group(1).strip()
                continue

            m = re.match(r"Task\s+Initiator:\s*(.+)", text)
            if m:
                meta["task_initiator"] = m.group(1).strip()
                continue

        return meta

    def _extract_description(self, paragraphs: list[tuple[str, str]]) -> str:
        """Extract Task Order Description between header and first sub-task."""
        collecting = False
        parts = []
        for style, text in paragraphs:
            if "Task Order Description" in text or "Description/Objectives:" in text:
                collecting = True
                continue
            if style == "SubTask Title":
                break
            if collecting and text and not text.startswith("Legend"):
                parts.append(text)
        return "\n".join(parts)

    def _extract_summary_table(self, doc) -> str:
        """Extract Summary of Changes from Table 0."""
        if not doc.tables:
            return ""

        table = doc.tables[0]
        rows = []
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            rows.append(cells)

        if not rows:
            return ""

        # Verify this looks like a Summary of Changes table
        header = [h.lower() for h in rows[0]]
        if not any("sub" in h or "task" in h for h in header):
            return ""

        # Build summary text from each row
        parts = []
        for row in rows[1:]:
            st_id = row[0] if row else ""
            # Gather all non-empty comment cells
            comments = []
            for cell in row[1:]:
                cell = cell.strip()
                if cell and cell not in ("0", "1", "2", "3"):
                    comments.append(cell)
            if st_id and comments:
                parts.append(f"{st_id}: {'; '.join(comments)}")

        return "\n".join(parts)

    def _map_deliverables_to_subtasks(self, doc) -> dict[str, list[str]]:
        """Walk document body elements in order to map deliverable tables to sub-tasks.

        Iterates ``doc.element.body`` which yields paragraphs and tables in
        document order.  Each time a SubTask Title paragraph is encountered the
        current sub-task ID is updated.  Any subsequent table whose first-row
        header contains "Deliverable" is parsed and its non-empty first-column
        values (skipping the header row) are collected as deliverables for that
        sub-task.
        """
        from docx.table import Table as DocxTable
        from docx.text.paragraph import Paragraph as DocxParagraph

        nsmap = doc.element.nsmap
        # Namespace-qualified tag names for paragraphs and tables
        p_tag = f"{{{nsmap['w']}}}p"
        tbl_tag = f"{{{nsmap['w']}}}tbl"

        deliverables_map: dict[str, list[str]] = {}
        current_subtask_id: Optional[str] = None

        for child in doc.element.body:
            tag = child.tag

            if tag == p_tag:
                para = DocxParagraph(child, doc)
                style_name = para.style.name if para.style else ""
                if style_name == "SubTask Title":
                    text = para.text.strip()
                    m = re.match(r"Sub-Task\s+Title:\s*(\S+)\s*-\s*(.*)", text)
                    if m:
                        current_subtask_id = m.group(1)
                    else:
                        tokens = text.replace("Sub-Task Title:", "").strip().split()
                        current_subtask_id = tokens[0] if tokens else None

            elif tag == tbl_tag and current_subtask_id is not None:
                table = DocxTable(child, doc)
                rows = [[c.text.strip() for c in row.cells] for row in table.rows]
                if not rows:
                    continue
                header = [h.lower() for h in rows[0]]
                # Check if this is a deliverables table
                if any("deliverable" in h for h in header):
                    # Find the column index for the deliverable name
                    deliv_col = 0
                    for i, h in enumerate(header):
                        if "deliverable" in h:
                            deliv_col = i
                            break
                    for row in rows[1:]:
                        if len(row) > deliv_col:
                            val = row[deliv_col].strip()
                            if val:
                                deliverables_map.setdefault(current_subtask_id, []).append(val)

        return deliverables_map

    def _extract_sub_tasks(
        self,
        paragraphs: list[tuple[str, str]],
        deliverables_by_subtask: Optional[dict[str, list[str]]] = None,
    ) -> list[SubTask]:
        """Extract sub-tasks from SubTask Title styled paragraphs and their content."""
        if deliverables_by_subtask is None:
            deliverables_by_subtask = {}
        sub_tasks = []
        current_id = None
        current_name = ""
        current_section = ""
        sections: dict[str, list[str]] = {}

        for style, text in paragraphs:
            if style == "SubTask Title":
                # Save previous sub-task
                if current_id:
                    st = self._build_sub_task(current_id, current_name, sections, deliverables_by_subtask)
                    sub_tasks.append(st)

                # Parse new sub-task header
                m = re.match(r"Sub-Task\s+Title:\s*(\S+)\s*-\s*(.*)", text)
                if m:
                    current_id = m.group(1)
                    current_name = m.group(2).strip().rstrip("-")
                else:
                    current_id = text.replace("Sub-Task Title:", "").strip().split()[0] if text else None
                    current_name = text
                sections = {}
                current_section = "header"
                continue

            if current_id is None:
                continue

            # Detect section headers within sub-task
            text_lower = text.lower()
            classified = self._classify_section(text_lower)
            if classified:
                current_section = classified
                continue

            # Detect metadata fields in header
            if current_section == "header":
                m = re.match(r"(Resource Analyst|Task Lead|Sub-Task Lead|Cost Center|"
                             r"Funding Source|Funding SubSource|Activity|Period of Performance|"
                             r"Classified):\s*(.*)", text)
                if m:
                    sections.setdefault("meta", []).append(f"{m.group(1)}: {m.group(2)}")
                    continue

            if text and current_section:
                sections.setdefault(current_section, []).append(text)

        # Save last sub-task
        if current_id:
            st = self._build_sub_task(current_id, current_name, sections, deliverables_by_subtask)
            sub_tasks.append(st)

        return sub_tasks

    def _detect_quality_plan(self, description: str, quality_text: str) -> Optional[QualityPlan]:
        """Detect quality plan from description and quality section text.

        Compliance heuristics: detect software scope and QMS requirements.
        ESSCA uses a broader keyword set than the generic DOCX parser because
        ESSCA task orders often describe computational work without using the
        word "software" (e.g., "algorithm development", "data pipeline").
        Why these keywords:
          - software_scope: "software", "AI", "machine learning", "algorithm",
            "data pipeline" — triggers NASA-STD-8739.8B applicability.
          - qms_required: "QMS", "quality management", "8739", "quality plan" —
            detects explicit QMS references in the quality section.
        False positive bias is intentional: better to flag for review than miss.
        """
        if not quality_text:
            return None

        software_scope = bool(re.search(
            r"\b(software|AI|machine.?learn|algorithm|data.?pipeline)\b",
            description, re.I
        ))
        qms_required = bool(re.search(
            r"\b(QMS|quality.?management|8739|quality.?plan)\b",
            quality_text, re.I
        ))

        return QualityPlan(
            text=quality_text,
            qms_required=qms_required,
            software_scope=software_scope,
        )

    def _classify_section(self, text_lower: str) -> str:
        """Classify a paragraph's text as a section header category.

        Args:
            text_lower: Lowercased paragraph text.

        Returns:
            Section category string, or empty string if not a section header.
        """
        if "description/objectives" in text_lower and "nasa" not in text_lower:
            return "description"
        if text_lower == "skills required":
            return "skills"
        if text_lower == "technical approach":
            return "technical"
        if "participating team" in text_lower:
            return "team"
        if "deliverables" in text_lower and "nasa" not in text_lower and "essca" not in text_lower:
            return "deliverables"
        if text_lower.startswith("sub-task description"):
            return "description"
        if text_lower.startswith("discussion of skills"):
            return "skills_discussion"
        if text_lower.startswith("deliverables and milestones"):
            if "nasa" in text_lower:
                return "deliverables_nasa"
            return "deliverables"
        if text_lower.startswith("travel and risk"):
            return "travel"
        if text_lower.startswith("gfe"):
            return "gfe"
        if text_lower.startswith("additional comments"):
            return "comments"
        if text_lower.startswith("technical approach (essca)"):
            return "technical_essca"
        return ""

    def _build_sub_task(
        self,
        st_id: str,
        name: str,
        sections: dict[str, list[str]],
        deliverables_by_subtask: Optional[dict[str, list[str]]] = None,
    ) -> SubTask:
        """Build a SubTask from extracted sections."""
        description_parts = sections.get("description", [])
        description = "\n".join(description_parts) if description_parts else name

        skills_text = "\n".join(sections.get("skills", []))
        skills = self._parse_skills(skills_text)

        team_parts = sections.get("team", [])
        team = [t.strip() for t in team_parts if t.strip() and t.strip() != "N/A"]

        # Extract funding source from metadata
        meta = sections.get("meta", [])
        wbs_code = ""
        charge_code = ""
        funding_source = ""
        for m in meta:
            if "Funding Source:" in m:
                funding_source = m.split(":", 1)[1].strip()
            if "Cost Center:" in m:
                charge_code = m.split(":", 1)[1].strip()
            if "Funding SubSource:" in m:
                sub_src = m.split(":", 1)[1].strip()
                if funding_source:
                    wbs_code = f"{funding_source}.{sub_src}"

        # Pull deliverables from the table-based map; fall back to empty list
        deliverables = (deliverables_by_subtask or {}).get(st_id, [])

        return SubTask(
            sub_task_id=st_id,
            description=description,
            skills=skills,
            labor_categories=skills,
            deliverables=deliverables,
            participating_team=team,
            wbs_code=wbs_code,
            charge_code=charge_code,
        )

    def _parse_skills(self, text: str) -> list[str]:
        """Extract skill keywords from skills text."""
        if not text:
            return []
        skills = []
        skill_patterns = [
            r"(materials?\s+engineer\w*)",
            r"(software\s+engineer\w*)",
            r"(systems?\s+engineer\w*)",
            r"(data\s+(?:analyst|scientist)\w*)",
            r"(project\s+manager\w*)",
            r"(quality\s+(?:engineer|assurance)\w*)",
            r"(test\s+engineer\w*)",
            r"(design\s+engineer\w*)",
            r"(mechanical\s+engineer\w*)",
            r"(electrical\s+engineer\w*)",
            r"(senior[\s-]+level)",
            r"(mid[\s-]+level)",
            r"(junior[\s-]+level)",
        ]
        for pat in skill_patterns:
            for m in re.finditer(pat, text, re.I):
                skills.append(m.group(1).strip())
        if not skills and text.strip():
            skills = [text.strip()[:80]]
        return skills

    def _extract_funding_tables(self, doc) -> list[FundingEntry]:
        """Extract funding from document tables."""
        entries = []
        for table in doc.tables:
            rows = [[c.text.strip() for c in row.cells] for row in table.rows]
            if not rows:
                continue
            header = [h.lower() for h in rows[0]]
            # Look for funding/cost tables
            if any("fund" in h or "amount" in h or "cost" in h or "value" in h for h in header):
                amount_col = None
                id_col = None
                for i, h in enumerate(header):
                    if any(kw in h for kw in ["amount", "fund", "cost", "value", "total"]):
                        amount_col = i
                    if any(kw in h for kw in ["sub", "task", "id"]):
                        id_col = i
                if amount_col is None:
                    continue
                for row in rows[1:]:
                    if len(row) <= amount_col:
                        continue
                    try:
                        amount = float(re.sub(r"[^\d.]", "", row[amount_col]))
                    except (ValueError, IndexError):
                        continue
                    st_id = row[id_col].strip() if id_col is not None and len(row) > id_col else None
                    entries.append(FundingEntry(sub_task_id=st_id, amount=amount))
        return entries

    def _find_quality_plan(self, paragraphs: list[tuple[str, str]], doc) -> str:
        """Look for quality plan content."""
        # Check if any paragraph mentions QP/Quality Plan
        for _, text in paragraphs:
            if re.search(r"\b(quality\s+plan|QMS|8739)\b", text, re.I):
                return text

        # Check for QP appendix reference
        for _, text in paragraphs[:10]:
            if "QP appendix" in text or "quality" in text.lower():
                return text

        return ""
