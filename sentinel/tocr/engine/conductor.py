#!/usr/bin/env python3
"""
Module: TOCR Conductor
Purpose: Orchestrates the three-pass pipeline for task order compliance review.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 4
"""

__version__ = "1.0.0"

import copy
import hashlib
import json
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from sentinel.tocr.engine.diff_engine import DiffEngine
from sentinel.tocr.engine.disclosure_engine import DisclosureEngine
from sentinel.tocr.engine.remediation_advisor import RemediationAdvisor
from sentinel.tocr.engine.rule_engine import RuleEngine
from sentinel.tocr.engine.scan_engine import ScanEngine
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.report import ComplianceReport
from sentinel.tocr.models.rules import TOCRRule
from sentinel.tocr.models.task_order import TaskOrder


# Default rule pack locations
_DEFAULT_RULES_PATH = Path(__file__).parent.parent / "data" / "tocr_rules.json"
_DEFAULT_SCAN_RULES_PATH = Path(__file__).parent.parent / "data" / "scan_rules.json"


class TOCRConductor:
    """
    Orchestrates the three-pass TOCR pipeline.

    Pass 1: Structural Diff — field-by-field comparison.
    Pass 2: Disclosure Audit — check every change against Summary of Changes.
    Pass 3: Rule Engine — evaluate changes against configurable rule packs.

    Produces a ComplianceReport with findings, score, and verdict.
    """

    def __init__(
        self,
        config: ContractConfig,
        rules: Optional[list[TOCRRule]] = None,
        rules_path: Optional[Path] = None,
        scan_rules: Optional[list[TOCRRule]] = None,
        scan_rules_path: Optional[Path] = None,
    ):
        self.config = config
        self.diff_engine = DiffEngine()
        self.disclosure_engine = DisclosureEngine(
            similarity_threshold=config.disclosure_similarity_threshold,
        )
        self.rule_engine = RuleEngine()
        self.scan_engine = ScanEngine()
        self.remediation_advisor = RemediationAdvisor()

        # Load diff rules
        if rules:
            self.rule_engine.load_rules_from_list(rules)
        elif rules_path and rules_path.exists():
            self.rule_engine.load_rules_from_json(rules_path)
        elif _DEFAULT_RULES_PATH.exists():
            self.rule_engine.load_rules_from_json(_DEFAULT_RULES_PATH)

        # Load scan rules
        if scan_rules:
            self.scan_engine.load_rules_from_list(scan_rules)
        elif scan_rules_path and scan_rules_path.exists():
            self.scan_engine.load_rules_from_json(scan_rules_path)
        elif _DEFAULT_SCAN_RULES_PATH.exists():
            self.scan_engine.load_rules_from_json(_DEFAULT_SCAN_RULES_PATH)

    def review(
        self,
        prior: TaskOrder,
        proposed: TaskOrder,
    ) -> ComplianceReport:
        """
        Execute full three-pass compliance review.

        Args:
            prior: Prior task order revision (baseline).
            proposed: Proposed task order revision (candidate).

        Returns:
            Complete ComplianceReport with findings, score, and verdict.
        """
        report_id = f"TOCR-{uuid.uuid4().hex[:8].upper()}"
        start_time = datetime.now()

        # Pass 1: Structural Diff
        diff = self.diff_engine.run(prior, proposed)

        # Pass 2: Disclosure Audit
        disclosures = self.disclosure_engine.run(diff, proposed.summary_of_changes)

        # Pass 3: Rule Engine
        findings = self.rule_engine.run(diff, disclosures, proposed, self.config)

        # Build report
        undisclosed = sum(1 for d in disclosures if not d.disclosed)
        disclosed = sum(1 for d in disclosures if d.disclosed)

        # Build input fingerprint: prior + proposed + rule pack
        fp_prior = self._fingerprint_task_order(prior)
        fp_proposed = self._fingerprint_task_order(proposed)
        fp_rules = self._fingerprint_rules(self.rule_engine.rules)
        input_fingerprint = (
            f"prior:{fp_prior[:16]} | proposed:{fp_proposed[:16]} | rules:{fp_rules[:16]}"
        )

        report = ComplianceReport(
            report_id=report_id,
            generated_at=start_time,
            prior_revision=prior.revision_number,
            proposed_revision=proposed.revision_number,
            structural_diff=diff,
            total_changes_detected=diff.total_changes,
            material_changes_detected=diff.material_changes,
            disclosure_results=disclosures,
            undisclosed_changes=undisclosed,
            disclosed_changes=disclosed,
            findings=findings,
            contract_config_summary=(
                f"{self.config.agency} {'/'.join(ct.value for ct in self.config.contract_type)}"
                f" | Vehicle: {self.config.vehicle or 'N/A'}"
                f" | Pack: {self.config.local_policy_pack or 'N/A'}"
            ),
            parser_confidence=diff.parser_confidence,
            rules_evaluated=len(self.rule_engine.rules),
            rules_fired=len(set(f.rule_id for f in findings)),
            rules_suppressed=len(self.rule_engine.suppression_log),
            suppression_log=list(self.rule_engine.suppression_log),
            assumptions=self._build_assumptions(diff, disclosures),
            input_fingerprint=input_fingerprint,
        )

        report.compute_score()
        report.remediation_plan = self.remediation_advisor.advise(findings, proposed)
        return report

    async def review_with_sonnet(
        self,
        prior: TaskOrder,
        proposed: TaskOrder,
    ) -> ComplianceReport:
        """
        Execute full review + Sonnet-enriched remediation language.

        Same as review() but adds a Bedrock Sonnet call to rewrite each
        remediation step in contract-attorney-grade plain English.
        Falls back to template language if Sonnet is unavailable.
        """
        report = self.review(prior, proposed)

        if report.findings and report.remediation_plan and report.remediation_plan.steps:
            from sentinel.tocr.engine.remediation_formatter import format_all_remediations

            enriched = await format_all_remediations(
                report.remediation_plan.steps,
                report.findings,
                task_order=proposed,
            )
            # Overwrite template remediation with Sonnet-generated text
            for step in report.remediation_plan.steps:
                if step.finding_id in enriched:
                    step.how_to_fix = enriched[step.finding_id]

        return report

    async def scan_with_sonnet(
        self,
        task_order: TaskOrder,
    ) -> ComplianceReport:
        """
        Execute standalone scan + Sonnet-enriched remediation language.
        """
        report = self.scan(task_order)

        if report.findings and report.remediation_plan and report.remediation_plan.steps:
            from sentinel.tocr.engine.remediation_formatter import format_all_remediations

            enriched = await format_all_remediations(
                report.remediation_plan.steps,
                report.findings,
                task_order=task_order,
            )
            for step in report.remediation_plan.steps:
                if step.finding_id in enriched:
                    step.how_to_fix = enriched[step.finding_id]

        return report

    def scan(
        self,
        task_order: TaskOrder,
    ) -> ComplianceReport:
        """
        Standalone compliance scan of a single task order.

        Give it a task order, it tells you compliant or not, and if not, why not.
        No prior revision needed.

        Args:
            task_order: The task order to evaluate.

        Returns:
            ComplianceReport with findings, score, and verdict.
        """
        report_id = f"SCAN-{uuid.uuid4().hex[:8].upper()}"
        start_time = datetime.now()

        findings = self.scan_engine.run(task_order, self.config)

        # Build input fingerprint
        fp_to = self._fingerprint_task_order(task_order)
        fp_rules = self._fingerprint_rules(self.scan_engine.rules)
        input_fingerprint = f"to:{fp_to[:16]} | rules:{fp_rules[:16]}"

        report = ComplianceReport(
            report_id=report_id,
            generated_at=start_time,
            proposed_revision=task_order.revision_number,
            findings=findings,
            contract_config_summary=(
                f"{self.config.agency} {'/'.join(ct.value for ct in self.config.contract_type)}"
                f" | Vehicle: {self.config.vehicle or 'N/A'}"
                f" | Pack: {self.config.local_policy_pack or 'N/A'}"
            ),
            parser_confidence=task_order.parser_confidence,
            rules_evaluated=len(self.scan_engine.rules),
            rules_fired=len(set(f.rule_id for f in findings)),
            rules_suppressed=len(self.scan_engine.suppression_log),
            suppression_log=list(self.scan_engine.suppression_log),
            assumptions=self._build_scan_assumptions(task_order),
            input_fingerprint=input_fingerprint,
        )

        report.compute_score()
        report.remediation_plan = self.remediation_advisor.advise(findings, task_order)
        return report

    def review_chain(
        self,
        revisions: list[TaskOrder],
    ) -> list[ComplianceReport]:
        """
        Run sequential pairwise comparisons for a revision chain (Section 14.3).

        Args:
            revisions: List of task order revisions in order (oldest to newest).

        Returns:
            List of ComplianceReports, one per pairwise comparison.
        """
        reports = []
        for i in range(len(revisions) - 1):
            report = self.review(revisions[i], revisions[i + 1])
            reports.append(report)
        return reports

    @staticmethod
    def _fingerprint_task_order(to: TaskOrder) -> str:
        """
        SHA-256 fingerprint of a task order's content fields.

        Proves which data produced the report. Covers every field the engine
        evaluates — excludes parser metadata that doesn't affect scoring.
        """
        parts = [
            to.task_order_number,
            to.revision_number,
            to.revision_status.value,
            to.title,
            to.task_order_description,
            to.scope_text,
            to.summary_of_changes,
            str(to.emergency_designation),
            to.emergency_justification,
            to.agency_comments,
            str(to.total_funding),
        ]
        if to.quality_plan:
            parts.extend([
                to.quality_plan.text,
                str(to.quality_plan.qms_required),
                str(to.quality_plan.software_scope),
                str(to.quality_plan.safety_critical),
            ])
        for st in to.sub_tasks:
            parts.extend([
                st.sub_task_id,
                st.description,
                str(st.funding),
                st.wbs_code or "",
                st.charge_code or "",
                "|".join(st.skills),
                "|".join(st.labor_categories),
                "|".join(st.deliverables),
                "|".join(st.participating_team),
            ])
        for fe in to.funding_table:
            parts.extend([
                fe.sub_task_id or "",
                fe.clin or "",
                str(fe.amount),
                fe.wbs_code or "",
                fe.charge_code or "",
                fe.description,
            ])
        raw = "\n".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _fingerprint_rules(rules: list) -> str:
        """SHA-256 fingerprint of the rule pack used."""
        parts = [f"{r.rule_id}|{r.title}|{r.severity.value}|{r.finding}" for r in rules]
        raw = "\n".join(sorted(parts))
        return hashlib.sha256(raw.encode()).hexdigest()

    def blind_review_chain(
        self,
        revisions: list[TaskOrder],
        seed: Optional[int] = None,
    ) -> dict:
        """
        Blind test: strip identifiers, randomize order, run all pairs, map back.

        This proves the engine scores on data alone — not on cycle identity.
        If a specific pair still scores as the outlier when the engine has no
        idea which cycle it's looking at, intent is proven by the data.

        Args:
            revisions: List of task order revisions in order (oldest first).
            seed: Optional RNG seed for reproducible randomization.

        Returns:
            Dict with:
                - blind_results: list of {blind_index, report} in randomized order
                - mapping: list of {blind_index, original_prior, original_proposed}
                - ranked: results sorted by score ascending (worst first)
        """
        # Build revision pairs with original identity
        pairs = []
        for i in range(len(revisions) - 1):
            pairs.append({
                "original_prior": revisions[i].revision_number,
                "original_proposed": revisions[i + 1].revision_number,
                "prior": revisions[i],
                "proposed": revisions[i + 1],
            })

        # Randomize order
        rng = random.Random(seed)
        indices = list(range(len(pairs)))
        rng.shuffle(indices)

        # Run each pair with stripped identifiers
        blind_results = []
        mapping = []

        for blind_idx, original_idx in enumerate(indices):
            pair = pairs[original_idx]

            # Fingerprint the ORIGINAL data before stripping identifiers.
            # This preserves chain-of-custody: the fingerprint proves which
            # real data produced the blind score.
            original_prior_fp = self._fingerprint_task_order(pair["prior"])
            original_proposed_fp = self._fingerprint_task_order(pair["proposed"])

            # Deep copy and strip identifiers
            prior_blind = copy.deepcopy(pair["prior"])
            proposed_blind = copy.deepcopy(pair["proposed"])
            prior_blind.task_order_number = "BLIND"
            prior_blind.revision_number = f"BLIND-{blind_idx}-A"
            prior_blind.title = "BLIND"
            proposed_blind.task_order_number = "BLIND"
            proposed_blind.revision_number = f"BLIND-{blind_idx}-B"
            proposed_blind.title = "BLIND"

            # Run the review — engine has no idea which cycle this is
            report = self.review(prior_blind, proposed_blind)

            # Overwrite the corrupted blind fingerprint with the real one
            fp_rules = self._fingerprint_rules(self.rule_engine.rules)
            report.input_fingerprint = (
                f"prior:{original_prior_fp[:16]} | proposed:{original_proposed_fp[:16]} | rules:{fp_rules[:16]}"
            )

            blind_results.append({
                "blind_index": blind_idx,
                "report": report,
            })
            mapping.append({
                "blind_index": blind_idx,
                "original_prior": pair["original_prior"],
                "original_proposed": pair["original_proposed"],
            })

        # Rank by score ascending (worst compliance first)
        ranked = sorted(
            blind_results,
            key=lambda r: r["report"].score.raw_score if r["report"].score else 100,
        )

        return {
            "blind_results": blind_results,
            "mapping": mapping,
            "ranked": ranked,
        }

    def _build_assumptions(self, diff, disclosures) -> list[str]:
        """Build the assumption drawer for the report."""
        assumptions = []

        if diff.parser_confidence.value == "low":
            assumptions.append(
                "Parser confidence is LOW (OCR-dependent). "
                "Field extraction may contain errors. Manual verification recommended."
            )
        elif diff.parser_confidence.value == "medium":
            assumptions.append(
                "Parser confidence is MEDIUM (PDF text extraction). "
                "Some fields may have extraction artifacts."
            )

        if diff.formatting_changes > 0:
            assumptions.append(
                f"{diff.formatting_changes} formatting-only changes were filtered "
                "from material change analysis."
            )

        return assumptions

    def _build_scan_assumptions(self, task_order: TaskOrder) -> list[str]:
        """Build assumptions for standalone scan."""
        assumptions = []

        if task_order.parser_confidence.value == "low":
            assumptions.append(
                "Parser confidence is LOW (OCR-dependent). "
                "Field extraction may contain errors. Manual verification recommended."
            )
        elif task_order.parser_confidence.value == "medium":
            assumptions.append(
                "Parser confidence is MEDIUM (PDF text extraction). "
                "Some fields may have extraction artifacts."
            )

        assumptions.append(
            "Standalone scan evaluates this task order in isolation. "
            "Use review() mode to compare against a prior revision."
        )

        return assumptions
