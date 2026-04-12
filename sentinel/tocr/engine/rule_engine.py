#!/usr/bin/env python3
"""
Module: Rule Engine
Purpose: Pass 3 — Evaluate every change against configurable rule packs.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Sections 4.3, 5, 9
"""

__version__ = "1.0.0"

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from sentinel.tocr.engine.shared import (
    CONTRACT_STOPWORDS,
    URGENCY_INDICATORS,
    filter_applicable_rules,
    trigger_matches,
)
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.diff import FieldChange, StructuralDiff
from sentinel.tocr.models.enums import (
    ChangeClassification,
    ChangeType,
    ComplianceSeverity,
    ConfidenceLevel,
    ParserConfidence,
    ReviewPriority,
)
from sentinel.tocr.models.evidence import TOCREvidence, TOCRFinding
from sentinel.tocr.models.report import DisclosureResult
from sentinel.tocr.models.rules import TOCRRule
from sentinel.tocr.models.task_order import TaskOrder


class ChangeContext:
    """Computed context about a single change for trigger evaluation."""

    def __init__(
        self,
        change: FieldChange,
        disclosure: Optional[DisclosureResult],
        proposed: TaskOrder,
        diff: StructuralDiff,
        cost_overlap_threshold: int = 8,
        emergency_word_threshold: int = 2,
    ):
        self.change = change
        self.disclosure = disclosure
        self.proposed = proposed
        self.diff = diff
        self._cost_overlap_threshold = cost_overlap_threshold
        self._emergency_word_threshold = emergency_word_threshold

        # Pre-compute trigger signals
        self.signals: set[str] = set()
        self._compute_signals()

    def _compute_signals(self) -> None:
        """Compute all trigger signals for this change context."""
        c = self.change

        # Material change detection
        if c.is_material:
            self.signals.add("material_change_detected")

        # Disclosure status
        if self.disclosure and not self.disclosure.disclosed:
            self.signals.add("not_listed_in_summary_of_changes")
        if self.disclosure and self.disclosure.disclosed:
            self.signals.add("listed_in_summary_of_changes")

        # Classification signals
        if c.classification == ChangeClassification.SCOPE_LANGUAGE:
            self.signals.add("scope_change_detected")
        if c.classification == ChangeClassification.FUNDING:
            self.signals.add("funding_change_detected")
        if c.classification == ChangeClassification.SKILLS:
            self.signals.add("skills_change_detected")
        if c.classification == ChangeClassification.TEAM:
            self.signals.add("team_change_detected")
        if c.classification == ChangeClassification.QUALITY_PLAN:
            self.signals.add("quality_plan_change_detected")

        # Insertion/deletion
        if c.change_type == ChangeType.INSERTION:
            self.signals.add("insertion_detected")
        if c.change_type == ChangeType.DELETION:
            self.signals.add("deletion_detected")

        # New sub-task
        if c.field_path.startswith("sub_tasks.") and c.change_type == ChangeType.INSERTION:
            self.signals.add("new_sub_task_added")

        # Scope addition (new scope text)
        if c.classification == ChangeClassification.SCOPE_LANGUAGE and c.change_type == ChangeType.INSERTION:
            self.signals.add("scope_addition_detected")

        # Scope modification that introduces a new work domain.
        # A MODIFICATION to scope text that adds keywords from a domain
        # not present in the prior text is functionally equivalent to a
        # scope addition — it introduces new work that needs funding,
        # deliverables, TOCR documentation, and CO review.
        if (
            c.classification == ChangeClassification.SCOPE_LANGUAGE
            and c.change_type == ChangeType.MODIFICATION
        ):
            self._check_new_domain_in_modification()

        # Work type analysis
        proposed_lower = c.proposed_text.lower()
        if any(kw in proposed_lower for kw in ["software", "ai", "machine learn", "algorithm"]):
            self.signals.add("software_scope_present")
        if any(kw in proposed_lower for kw in ["new work type", "new capability", "new scope"]):
            self.signals.add("new_work_type_detected")

        # Funding analysis
        self._compute_funding_signals()

        # Deliverables analysis
        self._compute_deliverable_signals()

        # Emergency analysis
        self._compute_emergency_signals()

        # Quality plan analysis
        self._compute_quality_signals()

        # Skills analysis
        self._compute_skills_signals()

        # ATOMS process signals
        if self.diff.new_sub_tasks:
            self.signals.add("new_sub_task_added")
        if "scope_addition_detected" in self.signals and not self.diff.new_sub_tasks:
            self.signals.add("scope_addition_no_sub_task")

        # Draft/unreleased signals
        if self.proposed.revision_status.value == "draft":
            self.signals.add("revision_is_draft")

        # Cost misallocation signals
        self._compute_cost_signals()

        # Retroactive scope
        if any(kw in proposed_lower for kw in [
            "previously performed", "retroactive", "already completed",
            "work already done", "prior performance",
        ]):
            self.signals.add("retroactive_scope_language")

    # Domain keyword patterns — each represents a distinct work domain.
    # Compiled regexes with word boundaries to avoid substring false positives
    # (e.g., "ai" matching inside "sustaining").
    # Case-insensitive EXCEPT for "AI" which is checked case-sensitive
    # (it's always uppercase as an acronym).
    _DOMAIN_PATTERNS: dict[str, list["re.Pattern"]] = {}

    @classmethod
    def _get_domain_patterns(cls) -> dict[str, list["re.Pattern"]]:
        if cls._DOMAIN_PATTERNS:
            return cls._DOMAIN_PATTERNS
        import re
        _raw = {
            "software_ai": {
                # Case-insensitive patterns
                "ci": [
                    r"\bsoftware\b", r"\bartificial.?intelligence\b",
                    r"\bmachine.?learn", r"\bneural.?network",
                    r"\bdeep.?learn", r"\balgorithm\b", r"\bdata.?pipeline",
                    r"\bnatural.?language", r"\bintelligence.?layer",
                    r"\bsoftware.?tool", r"\bcode.?develop",
                    r"\bweb.?service", r"\bapi.?develop", r"\bmodel.?train",
                ],
                # Case-SENSITIVE patterns (AI is always uppercase)
                "cs": [r"\bAI\b"],
            },
            "manufacturing": {
                "ci": [
                    r"\bmanufactur", r"\bfabricat", r"\bmachining\b",
                    r"\bwelding\b", r"\bcasting\b", r"\bforging\b",
                    r"\badditive.?manufactur", r"\b3d.?print",
                ],
                "cs": [],
            },
        }
        for domain, groups in _raw.items():
            patterns = []
            for pat in groups.get("ci", []):
                patterns.append(re.compile(pat, re.IGNORECASE))
            for pat in groups.get("cs", []):
                patterns.append(re.compile(pat))
            cls._DOMAIN_PATTERNS[domain] = patterns
        return cls._DOMAIN_PATTERNS

    def _check_new_domain_in_modification(self) -> None:
        """Detect when a scope MODIFICATION introduces a fundamentally new work domain.

        Example: inserting "development of Software Tools for integration of
        AI solutions" into a materials engineering paragraph.  The prior text
        has zero software/AI keywords; the proposed text has several.  This is
        functionally a scope addition hiding inside a text edit.
        """
        c = self.change
        prior_text = c.prior_text
        proposed_text = c.proposed_text

        for domain_name, patterns in self._get_domain_patterns().items():
            prior_hits = sum(1 for p in patterns if p.search(prior_text))
            proposed_hits = sum(1 for p in patterns if p.search(proposed_text))

            # New domain: zero keywords in prior, 2+ in proposed
            if prior_hits == 0 and proposed_hits >= 2:
                self.signals.add("scope_addition_detected")
                self.signals.add("new_work_type_detected")
                self.signals.add(f"new_domain_{domain_name}")

                # Also check if this new domain has a sub-task
                if not self.diff.new_sub_tasks:
                    self.signals.add("scope_addition_no_sub_task")

                return

    def _compute_funding_signals(self) -> None:
        """Compute funding-related trigger signals.

        Checks the *specific* sub-task associated with the change, not all
        sub-tasks globally.  If the change is a new sub-task, checks that
        sub-task.  If no specific sub-task can be identified, falls back to
        checking whether ANY sub-task is unfunded (conservative — flag more,
        not less).
        """
        if "scope_addition_detected" not in self.signals:
            return

        c = self.change
        # Identify the specific sub-task this change relates to
        target_sub_tasks: list = []
        if c.field_path.startswith("sub_tasks."):
            parts = c.field_path.split(".")
            if len(parts) >= 2:
                st_id = parts[1]
                target_sub_tasks = [
                    st for st in self.proposed.sub_tasks
                    if st.sub_task_id == st_id
                ]

        # If we can't identify a specific sub-task, check ALL new sub-tasks
        # (conservative: flag unfunded scope even if we're not sure which one)
        if not target_sub_tasks:
            target_sub_tasks = [
                st for st in self.proposed.sub_tasks
                if st.sub_task_id in self.diff.new_sub_tasks
            ]

        # If still empty (scope text change, not sub-task-level), check all
        if not target_sub_tasks:
            target_sub_tasks = list(self.proposed.sub_tasks)

        has_funding = any(st.funding and st.funding > 0 for st in target_sub_tasks)
        has_wbs = any(st.wbs_code for st in target_sub_tasks)
        has_charge_code = any(st.charge_code for st in target_sub_tasks)

        if not has_funding:
            self.signals.add("scope_with_zero_funding")
        if not has_wbs:
            self.signals.add("scope_with_no_wbs")
        if not has_charge_code:
            self.signals.add("scope_with_no_charge_code")
        if not has_funding and not has_wbs and not has_charge_code:
            self.signals.add("unfunded_scope")

    def _compute_deliverable_signals(self) -> None:
        """Compute deliverable-related signals."""
        if "scope_addition_detected" not in self.signals:
            return

        has_deliverables = any(
            st.deliverables for st in self.proposed.sub_tasks
        )
        if not has_deliverables:
            self.signals.add("scope_with_no_deliverables")

    def _compute_emergency_signals(self) -> None:
        """Compute emergency-related signals.

        FAR 16.505(b)(4) requires emergency justifications to document:
          (i)   Circumstances justifying the exception
          (ii)  Why normal ordering procedures cannot be followed
          (iii) Impact of delay (urgency/harm)

        We check for both coverage (does the justification reference the
        changes?) and substance (does it actually explain urgency?).
        """
        if not self.proposed.emergency_designation:
            return

        self.signals.add("emergency_designated")

        just_text = self.proposed.emergency_justification.strip()
        if not just_text:
            self.signals.add("emergency_no_justification")
            # No justification at all implies no substance either
            self.signals.add("emergency_justification_no_urgency")
            return

        just_lower = just_text.lower()

        # Check if justification covers all changes
        if self.change.is_material and self.change.classification == ChangeClassification.SCOPE_LANGUAGE:
            change_words = set(self.change.proposed_text.lower().split()[:10])
            just_words = set(just_lower.split())
            if len(change_words & just_words) < self._emergency_word_threshold:
                self.signals.add("emergency_justification_mismatch")

        # FAR 16.505(b)(4) substance check: does the justification explain
        # WHY this is urgent, not just WHAT the change is?
        # See engine/shared.py for indicator list provenance.
        has_urgency = any(phrase in just_lower for phrase in URGENCY_INDICATORS)

        if not has_urgency:
            self.signals.add("emergency_justification_no_urgency")

    def _compute_quality_signals(self) -> None:
        """Compute quality plan signals."""
        if "software_scope_present" in self.signals:
            qp = self.proposed.quality_plan
            if not qp or not qp.qms_required:
                self.signals.add("software_without_qms")

        if self.change.classification == ChangeClassification.QUALITY_PLAN:
            # Check if quality plan change has matching scope justification
            scope_changes = [
                c for c in self.diff.field_changes
                if c.classification == ChangeClassification.SCOPE_LANGUAGE and c.is_material
            ]
            if not scope_changes:
                self.signals.add("quality_plan_changed_without_scope")

    def _compute_skills_signals(self) -> None:
        """Compute skills mismatch signals."""
        if self.change.classification != ChangeClassification.SCOPE_LANGUAGE:
            return

        scope_lower = self.change.proposed_text.lower()
        all_skills = set()
        for st in self.proposed.sub_tasks:
            all_skills.update(s.lower() for s in st.skills)

        if "software" in scope_lower and not any("software" in s for s in all_skills):
            self.signals.add("skills_mismatch_detected")
        if "ai" in scope_lower and not any("ai" in s or "artificial" in s for s in all_skills):
            self.signals.add("skills_mismatch_detected")

    def _compute_cost_signals(self) -> None:
        """Compute cost misallocation signals.

        Only runs for changes directly related to sub-task descriptions or
        funding, not for every material change.  Uses an expanded stopword
        list that filters common contract/ESSCA boilerplate so that shared
        phrasing like "contractor shall provide materials evaluation" doesn't
        trigger false positives.
        """
        # Only compute for sub-task-level changes, not top-level scope fields
        if not self.change.field_path.startswith("sub_tasks."):
            return

        if len(self.proposed.sub_tasks) < 2:
            return

        for st in self.proposed.sub_tasks:
            if not st.description:
                continue
            desc_lower = st.description.lower()
            for other_st in self.proposed.sub_tasks:
                if other_st.sub_task_id == st.sub_task_id:
                    continue
                if not other_st.description:
                    continue
                other_words = set(other_st.description.lower().split())
                overlap = (set(desc_lower.split()) & other_words) - CONTRACT_STOPWORDS
                if len(overlap) > self._cost_overlap_threshold:
                    self.signals.add("cost_misallocation_risk")
                    break


class RuleEngine:
    """
    Pass 3: Rule Engine.

    Evaluates every change against loaded rule packs.
    Rules fire only when their applicability conditions are met.
    """

    def __init__(self, rules: Optional[list[TOCRRule]] = None):
        self.rules: list[TOCRRule] = rules or []
        self._suppression_log: list[dict] = []

    def load_rules_from_json(self, path: Path) -> None:
        """Load rules from a JSON file."""
        with open(path) as f:
            data = json.load(f)

        if isinstance(data, list):
            for item in data:
                self.rules.append(TOCRRule(**item))
        elif isinstance(data, dict) and "rules" in data:
            for item in data["rules"]:
                self.rules.append(TOCRRule(**item))

    def load_rules_from_list(self, rules: list[TOCRRule]) -> None:
        """Load rules from a list of TOCRRule objects."""
        self.rules.extend(rules)

    @property
    def suppression_log(self) -> list[dict]:
        return self._suppression_log

    def run(
        self,
        diff: StructuralDiff,
        disclosures: list[DisclosureResult],
        proposed: TaskOrder,
        config: ContractConfig,
    ) -> list[TOCRFinding]:
        """
        Execute rule evaluation for all material changes.

        Args:
            diff: Structural diff from Pass 1.
            disclosures: Disclosure results from Pass 2.
            proposed: The proposed task order revision.
            config: Contract configuration for applicability filtering.

        Returns:
            List of TOCRFindings for all triggered rules.
        """
        findings: list[TOCRFinding] = []
        self._suppression_log = []

        # Build disclosure lookup
        disclosure_map = {d.field_path: d for d in disclosures}

        # Filter applicable rules
        applicable_rules = self._filter_applicable(config)

        # Evaluate each material change against each applicable rule
        for change in diff.field_changes:
            if not change.is_material:
                continue

            disclosure = disclosure_map.get(change.field_path)
            ctx = ChangeContext(
                change, disclosure, proposed, diff,
                cost_overlap_threshold=config.cost_overlap_word_threshold,
                emergency_word_threshold=config.emergency_justification_word_threshold,
            )

            for rule in applicable_rules:
                if self._trigger_matches(rule, ctx):
                    finding = self._create_finding(rule, change, disclosure, ctx)
                    findings.append(finding)

        # Deduplicate findings by (rule_id, field_path)
        findings = self._deduplicate(findings)

        return findings

    def _filter_applicable(self, config: ContractConfig) -> list[TOCRRule]:
        """Filter rules by applicability against contract config."""
        return filter_applicable_rules(self.rules, config, self._suppression_log)

    def _trigger_matches(self, rule: TOCRRule, ctx: ChangeContext) -> bool:
        """Check if all trigger conditions are met."""
        return trigger_matches(rule, ctx.signals)

    def _create_finding(
        self,
        rule: TOCRRule,
        change: FieldChange,
        disclosure: Optional[DisclosureResult],
        ctx: ChangeContext,
    ) -> TOCRFinding:
        """Create a finding from a triggered rule."""
        # Deterministic ID: hash of (rule_id, field_path, change content)
        # Same input always produces the same finding ID.
        id_source = f"{rule.rule_id}|{change.field_path}|{change.proposed_text[:200]}"
        finding_id = f"F-{hashlib.sha256(id_source.encode()).hexdigest()[:6].upper()}"

        evidence = TOCREvidence(
            finding_id=finding_id,
            rule_id=rule.rule_id,
            prior_text=change.prior_text[:500],
            proposed_text=change.proposed_text[:500],
            field_path=change.field_path,
            change_type=change.change_type,
            classification=change.classification,
            classification_confidence=change.classification_confidence,
            classification_reason=change.classification_reason,
            disclosed_in_summary=disclosure.disclosed if disclosure else False,
            triggered_rules=[rule.rule_id],
            parser_confidence=change.parser_confidence,
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

    # Rules that are task-order-level (not per-field). These should only
    # produce one finding regardless of how many changes trigger them.
    _TASK_ORDER_LEVEL_RULES = {"TOCR-015", "TOCR-013"}

    def _deduplicate(self, findings: list[TOCRFinding]) -> list[TOCRFinding]:
        """Deduplicate findings.

        Per-field rules: deduplicate by (rule_id, field_path).
        Task-order-level rules: deduplicate by rule_id only — they describe
        a condition of the task order, not of a specific field change.
        """
        seen = set()
        deduped = []
        for f in findings:
            if f.rule_id in self._TASK_ORDER_LEVEL_RULES:
                key = f.rule_id
            else:
                key = (f.rule_id, f.evidence.field_path if f.evidence else "")
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return deduped
