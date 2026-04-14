#!/usr/bin/env python3
"""
Module: Remediation Advisor
Purpose: Generate context-specific fix steps from compliance findings.

Takes findings from the rule engine and produces a prioritized remediation plan
with actionable, specific instructions — not generic boilerplate.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 12 (Remediation Advisory)
"""

__safety_critical__: bool = True
__version__ = "1.0.0"

import json
from pathlib import Path
from typing import Optional

from sentinel.tocr.models.enums import (
    ComplianceSeverity,
    ReviewPriority,
)
from sentinel.tocr.models.evidence import TOCRFinding
from sentinel.tocr.models.remediation import RemediationPlan, RemediationStep
from sentinel.tocr.models.task_order import TaskOrder

_DEFAULT_GUIDANCE_PATH = Path(__file__).parent.parent / "data" / "guidance.json"

# Severity sort order (CRITICAL first)
_SEVERITY_ORDER = {
    ComplianceSeverity.CRITICAL: 0,
    ComplianceSeverity.HIGH: 1,
    ComplianceSeverity.MEDIUM: 2,
    ComplianceSeverity.LOW: 3,
}

# Review priority to human-readable owner
_OWNER_MAP = {
    ReviewPriority.LEGAL: "Legal / Contracts",
    ReviewPriority.CO: "Contracting Officer",
    ReviewPriority.SUPERVISORY: "Task Lead / PM",
    ReviewPriority.ADVISORY: "Task Lead",
}


class RemediationAdvisor:
    """
    Generates a prioritized remediation plan from compliance findings.

    Enriches each finding with context-specific fix instructions using:
    - The plain-English guidance pack (guidance.json)
    - Evidence from the finding (field_path, proposed_text, etc.)
    - Task order context (sub-tasks, funding, quality plan)
    """

    def __init__(self, guidance_path: Optional[Path] = None):
        self._guidance: dict = {}
        path = guidance_path or _DEFAULT_GUIDANCE_PATH
        if path.exists():
            self._load_guidance(path)

    def _load_guidance(self, path: Path) -> None:
        """Load the plain-English guidance pack."""
        with open(path) as f:
            data = json.load(f)
        self._guidance = data.get("entries", {})

    def advise(
        self,
        findings: list[TOCRFinding],
        task_order: Optional[TaskOrder] = None,
    ) -> RemediationPlan:
        """
        Generate a remediation plan from findings.

        Args:
            findings: Compliance findings from rule engine or scan engine.
            task_order: Optional proposed task order for context-specific advice.

        Returns:
            Prioritized RemediationPlan with actionable steps.
        """
        steps: list[RemediationStep] = []

        for finding in findings:
            step = self._build_step(finding, task_order)
            steps.append(step)

        # Sort by severity (CRITICAL first), then by rule_id for stability
        steps.sort(key=lambda s: (_SEVERITY_ORDER.get(s.severity, 99), s.rule_id))

        # Assign priority order
        for i, step in enumerate(steps, 1):
            step.priority_order = i

        # Collect unique owners
        owners = list(dict.fromkeys(s.owner for s in steps if s.owner))

        # Count by severity
        critical = sum(1 for s in steps if s.severity == ComplianceSeverity.CRITICAL)
        high = sum(1 for s in steps if s.severity == ComplianceSeverity.HIGH)
        medium = sum(1 for s in steps if s.severity == ComplianceSeverity.MEDIUM)
        low = sum(1 for s in steps if s.severity == ComplianceSeverity.LOW)

        return RemediationPlan(
            steps=steps,
            total_steps=len(steps),
            critical_steps=critical,
            high_steps=high,
            medium_steps=medium,
            low_steps=low,
            estimated_owners=owners,
        )

    def _build_step(
        self,
        finding: TOCRFinding,
        task_order: Optional[TaskOrder],
    ) -> RemediationStep:
        """Build a single remediation step from a finding."""
        guidance_entry = self._guidance.get(finding.rule_id, {})

        what_to_fix = self._build_what_to_fix(finding, guidance_entry)
        how_to_fix = self._build_how_to_fix(finding, task_order, guidance_entry)
        why_it_matters = self._build_why_it_matters(finding, guidance_entry)
        owner = self._resolve_owner(finding, guidance_entry)

        return RemediationStep(
            finding_id=finding.finding_id,
            rule_id=finding.rule_id,
            rule_title=finding.rule_title,
            severity=finding.severity,
            review_priority=finding.review_priority,
            field_path=finding.evidence.field_path if finding.evidence else "",
            what_to_fix=what_to_fix,
            how_to_fix=how_to_fix,
            why_it_matters=why_it_matters,
            owner=owner,
            authority_basis=finding.authority_basis,
        )

    def _build_what_to_fix(
        self,
        finding: TOCRFinding,
        guidance_entry: dict,
    ) -> str:
        """Build a plain-English description of what's wrong."""
        # Use guidance.json's what_it_means if available
        if guidance_entry.get("what_it_means"):
            return guidance_entry["what_it_means"]
        # Fall back to finding text
        return finding.finding_text

    def _build_how_to_fix(
        self,
        finding: TOCRFinding,
        task_order: Optional[TaskOrder],
        guidance_entry: dict,
    ) -> str:
        """
        Build context-specific fix instructions.

        This is the core value — not just "add funding" but
        "add funding to sub-task ST-003 which has $0 allocated for AI development scope."
        """
        parts: list[str] = []

        # Start with the guidance.json action steps
        if guidance_entry.get("what_to_do"):
            parts.append(guidance_entry["what_to_do"])

        # Layer on context from the finding evidence
        context = self._extract_context(finding, task_order)
        if context:
            parts.append(context)

        # Fall back to rule remediation if no guidance pack entry
        if not parts and finding.remediation:
            parts.append(finding.remediation)

        return " ".join(parts) if parts else finding.remediation

    def _build_why_it_matters(
        self,
        finding: TOCRFinding,
        guidance_entry: dict,
    ) -> str:
        """Build plain-English explanation of why this matters."""
        if guidance_entry.get("why_it_matters"):
            return guidance_entry["why_it_matters"]
        return finding.guidance

    def _resolve_owner(
        self,
        finding: TOCRFinding,
        guidance_entry: dict,
    ) -> str:
        """Determine who needs to act."""
        if guidance_entry.get("who_needs_to_act"):
            return guidance_entry["who_needs_to_act"]
        return _OWNER_MAP.get(finding.review_priority, "Task Lead")

    def _extract_context(
        self,
        finding: TOCRFinding,
        task_order: Optional[TaskOrder],
    ) -> str:
        """
        Extract context-specific details from the finding evidence and task order.

        This turns generic advice into specific, actionable instructions.
        """
        if not finding.evidence:
            return ""

        evidence = finding.evidence
        rule_id = finding.rule_id
        parts: list[str] = []

        # Context based on rule type
        if rule_id == "TOCR-002":
            # Out-of-scope work type — show what was inserted vs authorized scope
            parts.append(self._context_out_of_scope(evidence, task_order))

        elif rule_id in ("TOCR-001", "TOCR-012", "SCAN-012"):
            # Undisclosed change — tell them exactly what field changed
            parts.append(self._context_undisclosed(evidence))

        elif rule_id in ("TOCR-004", "SCAN-001", "SCAN-011"):
            # Unfunded scope — identify the unfunded sub-tasks
            parts.append(self._context_unfunded(evidence, task_order))

        elif rule_id in ("TOCR-005", "SCAN-002"):
            # Missing deliverables — identify which sub-tasks
            parts.append(self._context_missing_deliverables(evidence, task_order))

        elif rule_id in ("TOCR-008", "SCAN-003"):
            # Software QMS — identify the software scope
            parts.append(self._context_software_qms(evidence, task_order))

        elif rule_id in ("TOCR-010", "SCAN-007", "SCAN-008"):
            # Skills mismatch — identify the gap
            parts.append(self._context_skills_mismatch(evidence, task_order))

        elif rule_id in ("TOCR-013", "SCAN-009"):
            # Cost misallocation — identify overlapping sub-tasks
            parts.append(self._context_cost_misallocation(evidence, task_order))

        elif rule_id in ("TOCR-015", "SCAN-014"):
            # Emergency justification lacks substance
            parts.append(self._context_emergency_no_urgency(evidence, task_order))

        elif rule_id in ("TOCR-014", "SCAN-005"):
            # Retroactive scope — flag the language
            parts.append(self._context_retroactive(evidence))

        elif rule_id == "SCAN-006":
            # No sub-tasks
            parts.append(self._context_no_sub_tasks(task_order))

        elif rule_id == "SCAN-013":
            # Missing description
            parts.append(self._context_missing_description(evidence, task_order))

        return " ".join(p for p in parts if p)

    def _context_out_of_scope(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for out-of-scope work type findings."""
        parts = []

        # Show the diff — what was added
        diff_summary = self._summarize_text_diff(
            evidence.prior_text or "", evidence.proposed_text or ""
        )
        if diff_summary:
            parts.append(f"Scope change: {diff_summary}")

        # Identify violated regulations
        parts.append(
            "Regulations violated: "
            "FAR 16.505(a)(2) — orders must be within contract scope. "
            "FAR 43.102(a) — only COs may execute contract modifications. "
            "FAR 43.102(a)(3) — other personnel shall not direct work that "
            "should be a contract modification. "
            "NFS 1816.506-70 — task orders must align with the contract SOW."
        )

        # Compare against task order metadata if available
        if task_order:
            # Check raw_fields for Skill field from ESSCA format
            raw = getattr(task_order, "raw_fields", None) or {}
            skill_field = raw.get("skill", "")
            if not skill_field:
                # Search sub-task skills for the authorized domain
                all_skills = set()
                for st in task_order.sub_tasks:
                    all_skills.update(st.skills)
                skill_field = ", ".join(sorted(all_skills)[:5]) if all_skills else "not specified"

            parts.append(
                f"Authorized Skill field: \"{skill_field}\". "
                f"The inserted work type must fall within this authorized scope. "
                f"If it does not, remove it from this TO and initiate separate procurement."
            )

        return " ".join(parts)

    def _context_undisclosed(self, evidence) -> str:
        """Context for undisclosed change findings.

        When both prior and proposed text are available, computes a targeted
        diff summary showing what was actually added/removed/changed — not
        just dumping the full field text.
        """
        field = evidence.field_path
        prior = evidence.prior_text or ""
        proposed = evidence.proposed_text or ""

        # Compute what actually changed
        diff_summary = self._summarize_text_diff(prior, proposed)

        if field and diff_summary:
            return (
                f"Specifically, in '{field}': {diff_summary} "
                f"This change must be added to the Summary of Changes section "
                f"with a description of what was added/removed and why."
            )
        if field and proposed:
            return (
                f"The change at '{field}' "
                f"(\"{proposed[:150]}{'...' if len(proposed) > 150 else ''}\")"
                f" must be added to the Summary of Changes section."
            )
        if field:
            return f"The change at '{field}' must be added to the Summary of Changes."
        return ""

    @staticmethod
    def _summarize_text_diff(prior: str, proposed: str) -> str:
        """Produce a human-readable summary of what changed between two texts."""
        if not prior and proposed:
            return f"New content added: \"{proposed[:200]}{'...' if len(proposed) > 200 else ''}\""
        if prior and not proposed:
            return f"Content removed: \"{prior[:200]}{'...' if len(prior) > 200 else ''}\""
        if not prior or not proposed:
            return ""

        # Find inserted and removed segments using SequenceMatcher
        import difflib
        prior_words = prior.split()
        proposed_words = proposed.split()
        sm = difflib.SequenceMatcher(None, prior_words, proposed_words)

        added_segments = []
        removed_segments = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "insert":
                added_segments.append(" ".join(proposed_words[j1:j2]))
            elif op == "delete":
                removed_segments.append(" ".join(prior_words[i1:i2]))
            elif op == "replace":
                removed_segments.append(" ".join(prior_words[i1:i2]))
                added_segments.append(" ".join(proposed_words[j1:j2]))

        parts = []
        if added_segments:
            added_text = " [...] ".join(s[:150] for s in added_segments[:3])
            parts.append(f"Added: \"{added_text}\"")
        if removed_segments:
            removed_text = " [...] ".join(s[:150] for s in removed_segments[:3])
            parts.append(f"Removed: \"{removed_text}\"")

        return ". ".join(parts) if parts else ""

    def _context_unfunded(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for unfunded scope findings."""
        unfunded = []
        if task_order:
            for st in task_order.sub_tasks:
                if (st.funding is None or st.funding == 0) and not st.wbs_code and not st.charge_code:
                    unfunded.append(st.sub_task_id)

        if unfunded:
            ids = ", ".join(unfunded)
            return (
                f"Sub-task(s) {ids} have no funding, WBS code, or charge code. "
                f"Assign funding amounts and accounting codes before submission."
            )

        # Fall back to evidence text
        if evidence.proposed_text:
            return f"Details: {evidence.proposed_text[:200]}"
        return ""

    def _context_missing_deliverables(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for missing deliverables."""
        missing = []
        if task_order:
            for st in task_order.sub_tasks:
                if not st.deliverables:
                    missing.append(st.sub_task_id)

        if missing:
            ids = ", ".join(missing)
            return (
                f"Sub-task(s) {ids} have no deliverables defined. "
                f"Add measurable deliverables with acceptance criteria and due dates."
            )
        return ""

    def _context_software_qms(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for software without QMS."""
        software_keywords = []
        if task_order:
            scope = f"{task_order.task_order_description} {task_order.scope_text}".lower()
            for kw in ["software", "ai", "machine learning", "algorithm", "code", "application"]:
                if kw in scope:
                    software_keywords.append(kw)

        if software_keywords:
            return (
                f"Software scope detected (keywords: {', '.join(software_keywords)}). "
                f"A QMS plan referencing NASA-STD-8739.8B must be added to the Quality Plan section."
            )
        return ""

    def _context_skills_mismatch(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for skills mismatch."""
        if not task_order:
            return ""

        all_skills = set()
        for st in task_order.sub_tasks:
            all_skills.update(st.skills)
            all_skills.update(st.labor_categories)

        current = ", ".join(sorted(all_skills)) if all_skills else "none defined"
        return f"Current labor categories: {current}. Update to include skills matching the new scope."

    def _context_cost_misallocation(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for cost misallocation."""
        if evidence.proposed_text:
            return f"Overlap details: {evidence.proposed_text[:200]}"
        return ""

    def _context_emergency_no_urgency(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for emergency justification that lacks urgency substance."""
        parts = []

        # Show what the justification actually says
        if task_order and task_order.emergency_justification.strip():
            just_text = task_order.emergency_justification.strip()
            parts.append(
                f"Current justification: \"{just_text[:300]}"
                f"{'...' if len(just_text) > 300 else ''}\". "
                f"This describes WHAT is needed but does not address WHY it is urgent."
            )

        parts.append(
            "The justification must answer: "
            "(1) What external pressure (safety, schedule, hardware jeopardy) "
            "requires immediate action? "
            "(2) What specific harm occurs during the 2-3 weeks of standard review? "
            "(3) What is the consequence of NOT using emergency authority? "
            "If these questions cannot be answered with specific facts, "
            "remove the emergency designation and use standard review."
        )

        return " ".join(parts)

    def _context_retroactive(self, evidence) -> str:
        """Context for retroactive scope language."""
        if evidence.proposed_text:
            text = evidence.proposed_text[:200]
            return (
                f"The following language suggests retroactive scope: "
                f"\"{text}{'...' if len(evidence.proposed_text) > 200 else ''}\"."
                f" Remove this language and initiate ratification under FAR 1.602-3 if work was already performed."
            )
        return ""

    def _context_no_sub_tasks(self, task_order: Optional[TaskOrder]) -> str:
        """Context for task order with no sub-tasks."""
        if task_order and task_order.scope_text:
            scope_preview = task_order.scope_text[:150]
            return (
                f"The task order has scope (\"{scope_preview}...\") but no sub-tasks to structure it. "
                f"Create sub-tasks with IDs, descriptions, funding, WBS codes, skills, and deliverables."
            )
        return "Create sub-tasks to structure the scope of work."

    def _context_missing_description(self, evidence, task_order: Optional[TaskOrder]) -> str:
        """Context for sub-tasks missing descriptions."""
        empty = []
        if task_order:
            for st in task_order.sub_tasks:
                if not st.description.strip():
                    empty.append(st.sub_task_id)

        if empty:
            ids = ", ".join(empty)
            return f"Sub-task(s) {ids} have no description. Add scope of work descriptions."
        return ""
