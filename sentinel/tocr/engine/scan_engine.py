#!/usr/bin/env python3
"""
Module: Standalone Compliance Scan Engine
Purpose: Evaluate a single task order for compliance — no prior revision needed.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

The diff-based pipeline catches what CHANGED. This engine catches what IS WRONG.
Give it a task order, it tells you compliant or not, and if not, why not.
"""

__safety_critical__: bool = True
__version__ = "1.0.0"

import hashlib
import re
from typing import Optional

from sentinel.tocr.engine.shared import (
    CONTRACT_STOPWORDS,
    URGENCY_INDICATORS,
    filter_applicable_rules,
    trigger_matches,
)
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import (
    ChangeClassification,
    ChangeType,
    ComplianceSeverity,
    ConfidenceLevel,
    ParserConfidence,
    ReviewPriority,
)
from sentinel.tocr.models.evidence import TOCREvidence, TOCRFinding
from sentinel.tocr.models.rules import TOCRRule
from sentinel.tocr.models.task_order import TaskOrder


# Software/AI scope patterns
_SOFTWARE_PATTERNS = re.compile(
    r"\b(software|code|programming|software.?application|database|web.?service|api.?develop"
    r"|artificial.?intelligence|AI|machine.?learn|neural.?network|deep.?learn"
    r"|algorithm|model.?train|data.?pipeline)\b",
    re.IGNORECASE,
)

# Retroactive scope language
_RETROACTIVE_PATTERNS = re.compile(
    r"\b(previously performed|retroactive|already completed|work already done"
    r"|prior performance|past effort|work.?to.?date|effort.?already)\b",
    re.IGNORECASE,
)


class TaskOrderContext:
    """
    Computed signals from a single task order for standalone rule evaluation.

    Unlike ChangeContext (which needs a diff), this inspects the task order
    as-is and flags structural compliance issues.
    """

    def __init__(self, task_order: TaskOrder, config: ContractConfig):
        self.task_order = task_order
        self.config = config
        self._cost_overlap_threshold = config.cost_overlap_word_threshold
        self.signals: set[str] = set()
        self.signal_details: dict[str, str] = {}
        self._compute_signals()

    def _compute_signals(self) -> None:
        to = self.task_order

        # --- Scope analysis ---
        scope = f"{to.task_order_description} {to.scope_text}"
        scope_lower = scope.lower()

        if scope.strip():
            self.signals.add("has_scope")
        else:
            self.signals.add("no_scope_text")
            self.signal_details["no_scope_text"] = "Task order has no scope description."

        # Software scope detection
        if _SOFTWARE_PATTERNS.search(scope):
            self.signals.add("software_scope_present")
            match = _SOFTWARE_PATTERNS.search(scope)
            self.signal_details["software_scope_present"] = (
                f"Software keyword detected: '{match.group()}'"
            )

        # Retroactive language
        if _RETROACTIVE_PATTERNS.search(scope):
            self.signals.add("retroactive_scope_language")
            match = _RETROACTIVE_PATTERNS.search(scope)
            self.signal_details["retroactive_scope_language"] = (
                f"Retroactive language detected: '{match.group()}'"
            )

        # --- Sub-task analysis ---
        if not to.sub_tasks:
            self.signals.add("no_sub_tasks")
            self.signal_details["no_sub_tasks"] = "Task order has zero sub-tasks."

        for st in to.sub_tasks:
            st_prefix = f"sub_task_{st.sub_task_id}"

            # Unfunded sub-task
            if st.funding is None or st.funding == 0:
                self.signals.add("sub_task_unfunded")
                self.signal_details.setdefault("sub_task_unfunded", "")
                self.signal_details["sub_task_unfunded"] += f"{st.sub_task_id} has $0 funding. "

            # No WBS
            if not st.wbs_code:
                self.signals.add("sub_task_no_wbs")
                self.signal_details.setdefault("sub_task_no_wbs", "")
                self.signal_details["sub_task_no_wbs"] += f"{st.sub_task_id} has no WBS code. "

            # No charge code
            if not st.charge_code:
                self.signals.add("sub_task_no_charge_code")
                self.signal_details.setdefault("sub_task_no_charge_code", "")
                self.signal_details["sub_task_no_charge_code"] += f"{st.sub_task_id} has no charge code. "

            # No deliverables
            if not st.deliverables:
                self.signals.add("sub_task_no_deliverables")
                self.signal_details.setdefault("sub_task_no_deliverables", "")
                self.signal_details["sub_task_no_deliverables"] += f"{st.sub_task_id} has no deliverables. "

            # No skills
            if not st.skills and not st.labor_categories:
                self.signals.add("sub_task_no_skills")
                self.signal_details.setdefault("sub_task_no_skills", "")
                self.signal_details["sub_task_no_skills"] += (
                    f"{st.sub_task_id} has no skills or labor categories. "
                )

            # Empty description
            if not st.description.strip():
                self.signals.add("sub_task_no_description")
                self.signal_details.setdefault("sub_task_no_description", "")
                self.signal_details["sub_task_no_description"] += (
                    f"{st.sub_task_id} has no description. "
                )

            # Scope text has software but sub-task skills don't
            if "software_scope_present" in self.signals:
                st_skills_lower = " ".join(st.skills + st.labor_categories).lower()
                if not any(kw in st_skills_lower for kw in ["software", "ai", "developer", "engineer"]):
                    self.signals.add("skills_mismatch_for_software")

        # Check if ALL sub-tasks are unfunded (complete unfunded scope)
        if to.sub_tasks and all(
            (st.funding is None or st.funding == 0) for st in to.sub_tasks
        ):
            self.signals.add("all_sub_tasks_unfunded")
            self.signal_details["all_sub_tasks_unfunded"] = (
                "Every sub-task has $0 funding. No work can be authorized."
            )

        # Check if ANY sub-task has no WBS AND no charge code AND no funding
        for st in to.sub_tasks:
            if (st.funding is None or st.funding == 0) and not st.wbs_code and not st.charge_code:
                self.signals.add("sub_task_completely_unfunded")
                self.signal_details.setdefault("sub_task_completely_unfunded", "")
                self.signal_details["sub_task_completely_unfunded"] += (
                    f"{st.sub_task_id} has no funding, no WBS, no charge code. "
                )

        # --- Funding analysis ---
        if to.total_funding is not None and to.total_funding == 0:
            self.signals.add("zero_total_funding")
            self.signal_details["zero_total_funding"] = "Total funding is $0."

        # --- QMS analysis ---
        if "software_scope_present" in self.signals:
            qp = to.quality_plan
            if not qp or not qp.qms_required:
                self.signals.add("software_without_qms")
                self.signal_details["software_without_qms"] = (
                    "Software scope present but no QMS plan (NASA-STD-8739.8B required)."
                )

        # --- Emergency analysis ---
        if to.emergency_designation:
            self.signals.add("emergency_designated")
            just_text = to.emergency_justification.strip()
            if not just_text:
                self.signals.add("emergency_no_justification")
                self.signal_details["emergency_no_justification"] = (
                    "Emergency designated but justification is empty."
                )
                self.signals.add("emergency_justification_no_urgency")
                self.signal_details["emergency_justification_no_urgency"] = (
                    "No emergency justification provided. FAR 16.505(b)(4) requires "
                    "documented urgency, not just a scope description."
                )
            else:
                # FAR 16.505(b)(4) substance check
                # See engine/shared.py for indicator list provenance.
                just_lower = just_text.lower()
                has_urgency = any(phrase in just_lower for phrase in URGENCY_INDICATORS)
                if not has_urgency:
                    self.signals.add("emergency_justification_no_urgency")
                    self.signal_details["emergency_justification_no_urgency"] = (
                        f"Emergency justification describes scope but does not explain urgency. "
                        f"Justification: \"{just_text[:200]}\". "
                        f"FAR 16.505(b)(4) requires: (1) why this is urgent, "
                        f"(2) why normal procedures cannot be followed, "
                        f"(3) what harm results from delay."
                    )

        # --- Draft status ---
        if to.revision_status.value == "draft":
            self.signals.add("revision_is_draft")

        # --- Cost misallocation ---
        self._check_cost_misallocation()

        # --- Summary of changes ---
        if not to.summary_of_changes.strip():
            self.signals.add("no_summary_of_changes")
            self.signal_details["no_summary_of_changes"] = (
                "Summary of Changes is empty."
            )

    def _check_cost_misallocation(self) -> None:
        """Check for cross-sub-task cost misallocation risk.

        Uses expanded stopwords that filter common contract/ESSCA boilerplate
        so that shared phrasing doesn't trigger false positives.
        """
        to = self.task_order
        if len(to.sub_tasks) < 2:
            return

        for st in to.sub_tasks:
            if not st.description:
                continue
            desc_words = set(st.description.lower().split())
            for other in to.sub_tasks:
                if other.sub_task_id == st.sub_task_id or not other.description:
                    continue
                other_words = set(other.description.lower().split())
                overlap = (desc_words & other_words) - CONTRACT_STOPWORDS
                if len(overlap) > self._cost_overlap_threshold:
                    self.signals.add("cost_misallocation_risk")
                    self.signal_details["cost_misallocation_risk"] = (
                        f"Sub-tasks {st.sub_task_id} and {other.sub_task_id} have "
                        f"highly overlapping descriptions ({len(overlap)} shared words)."
                    )
                    return


class ScanEngine:
    """
    Standalone compliance scan engine.

    Evaluates a single task order against compliance rules.
    No prior revision required. Answers: is this TO compliant? If not, why?
    """

    def __init__(self, rules: Optional[list[TOCRRule]] = None):
        self.rules: list[TOCRRule] = rules or []
        self._suppression_log: list[dict] = []

    @property
    def suppression_log(self) -> list[dict]:
        return self._suppression_log

    def load_rules_from_list(self, rules: list[TOCRRule]) -> None:
        self.rules.extend(rules)

    def load_rules_from_json(self, path) -> None:
        """Load rules from a JSON file."""
        import json
        from pathlib import Path
        with open(Path(path)) as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("rules", [])
        for item in items:
            self.rules.append(TOCRRule(**item))

    def run(
        self,
        task_order: TaskOrder,
        config: ContractConfig,
    ) -> list[TOCRFinding]:
        """
        Scan a single task order for compliance issues.

        Args:
            task_order: The task order to evaluate.
            config: Contract configuration for applicability.

        Returns:
            List of findings. Empty list = compliant.
        """
        self._suppression_log = []
        findings: list[TOCRFinding] = []

        ctx = TaskOrderContext(task_order, config)
        applicable_rules = self._filter_applicable(config)

        for rule in applicable_rules:
            if self._trigger_matches(rule, ctx):
                finding = self._create_finding(rule, ctx)
                findings.append(finding)

        return findings

    def _filter_applicable(self, config: ContractConfig) -> list[TOCRRule]:
        """Filter rules by contract config applicability."""
        return filter_applicable_rules(self.rules, config, self._suppression_log)

    def _trigger_matches(self, rule: TOCRRule, ctx: TaskOrderContext) -> bool:
        """Check if all trigger conditions are met."""
        return trigger_matches(rule, ctx.signals)

    def _create_finding(self, rule: TOCRRule, ctx: TaskOrderContext) -> TOCRFinding:
        # Deterministic ID: hash of (rule_id, TO number, signals)
        # Same input always produces the same finding ID.
        signal_key = "|".join(sorted(ctx.signals))
        id_source = f"{rule.rule_id}|{ctx.task_order.task_order_number}|{signal_key}"
        finding_id = f"F-{hashlib.sha256(id_source.encode()).hexdigest()[:6].upper()}"

        # Build detail from signal evidence
        detail_parts = []
        for sig in rule.trigger.all + rule.trigger.any:
            if sig in ctx.signal_details:
                detail_parts.append(ctx.signal_details[sig])

        evidence = TOCREvidence(
            finding_id=finding_id,
            rule_id=rule.rule_id,
            proposed_text="; ".join(detail_parts) if detail_parts else "",
            field_path="task_order",
            change_type=ChangeType.MODIFICATION,
            classification=ChangeClassification.ADMINISTRATIVE,
            classification_confidence=ConfidenceLevel.DETERMINISTIC,
            classification_reason="Standalone compliance scan",
            parser_confidence=ctx.task_order.parser_confidence,
        )

        return TOCRFinding(
            finding_id=finding_id,
            rule_id=rule.rule_id,
            rule_title=rule.title,
            severity=rule.severity,
            review_priority=rule.review_priority,
            confidence_method=rule.confidence_method,
            finding_text=rule.finding,
            guidance=rule.guidance,
            remediation=rule.remediation,
            authority_basis=rule.authority_basis,
            evidence=evidence,
        )
