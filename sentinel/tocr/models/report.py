#!/usr/bin/env python3
"""
Module: TOCR Report Models
Purpose: Compliance report and scoring models per Section 6.3, 11.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Sections 6.3, 11

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: True
"""

__version__ = "1.0.0"

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from sentinel.tocr.models.enums import (
    ComplianceSeverity,
    ComplianceVerdict,
    ConfidenceLevel,
    ParserConfidence,
)
from sentinel.tocr.models.diff import FieldChange, StructuralDiff
from sentinel.tocr.models.evidence import TOCRFinding
from sentinel.tocr.models.remediation import RemediationPlan


class DisclosureResult(BaseModel):
    """Disclosure audit result for a single change."""

    model_config = {"extra": "forbid"}

    field_path: str
    change_summary: str = ""
    disclosed: bool = False
    matching_summary_text: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.DETERMINISTIC


class ComplianceScore(BaseModel):
    """
    Revision compliance score per Section 6.3.

    Score = 100 - (CRITICAL x 20 + HIGH x 10 + MEDIUM x 5 + LOW x 1)
    """

    raw_score: int = 100
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    verdict: ComplianceVerdict = ComplianceVerdict.CLEAN

    model_config = {"extra": "forbid"}

    @classmethod
    def compute(cls, findings: list[TOCRFinding]) -> "ComplianceScore":
        """Compute score from findings list."""
        critical = sum(1 for f in findings if f.severity == ComplianceSeverity.CRITICAL)
        high = sum(1 for f in findings if f.severity == ComplianceSeverity.HIGH)
        medium = sum(1 for f in findings if f.severity == ComplianceSeverity.MEDIUM)
        low = sum(1 for f in findings if f.severity == ComplianceSeverity.LOW)

        score = 100 - (critical * 20 + high * 10 + medium * 5 + low * 1)
        score = max(0, score)

        # WHY 50: scores below 50 indicate severe non-compliance (e.g., 3+
        # critical findings); any critical finding is also auto-FATAL regardless
        # of score because critical = contract breach risk.
        if score < 50 or critical > 0:
            verdict = ComplianceVerdict.FATAL
        # WHY 90: scores 50-89 or any HIGH finding indicate material issues
        # that require CO attention but aren't contract-stopping.
        elif score < 90 or high > 0:
            verdict = ComplianceVerdict.FLAGGED
        else:
            verdict = ComplianceVerdict.CLEAN

        return cls(
            raw_score=score,
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            low_count=low,
            verdict=verdict,
        )


class ComplianceReport(BaseModel):
    """
    Complete TOCR compliance report per Section 11.

    Contains revision comparison summary, disclosure audit results,
    rule violation table, per-change verdicts, and overall score.
    """

    # Identification
    report_id: str = ""
    generated_at: datetime = Field(default_factory=datetime.now)
    prior_revision: str = ""
    proposed_revision: str = ""

    # Pass 1: Structural diff summary
    structural_diff: Optional[StructuralDiff] = None
    total_changes_detected: int = 0
    material_changes_detected: int = 0

    # Pass 2: Disclosure audit
    disclosure_results: list[DisclosureResult] = Field(default_factory=list)
    undisclosed_changes: int = 0
    disclosed_changes: int = 0

    # Pass 3: Rule findings
    findings: list[TOCRFinding] = Field(default_factory=list)

    # Scoring
    score: Optional[ComplianceScore] = None

    # Remediation plan
    remediation_plan: Optional[RemediationPlan] = None

    # Metadata
    contract_config_summary: str = ""
    parser_confidence: ParserConfidence = ParserConfidence.HIGH
    rules_evaluated: int = 0
    rules_fired: int = 0
    rules_suppressed: int = 0
    suppression_log: list[dict] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    input_fingerprint: str = ""

    # Why extra="allow": ComplianceReport is the primary output artifact and may
    # carry extension fields from LLM-enhanced passes (Sonnet remediation, blind
    # review metadata) that the base report schema doesn't define.  Forbidding
    # extras would break the enrichment pipeline.
    model_config = {"extra": "allow"}

    def compute_score(self) -> None:
        """Compute and attach compliance score from findings."""
        self.score = ComplianceScore.compute(self.findings)
