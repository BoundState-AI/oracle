#!/usr/bin/env python3
"""
Module: TOCR Evidence and Finding Models
Purpose: Evidence record and finding models per Section 8.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 8

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: True
"""

__version__ = "1.0.0"

from typing import Optional

from pydantic import BaseModel, Field

from sentinel.tocr.models.enums import (
    ChangeClassification,
    ChangeType,
    ComplianceSeverity,
    ConfidenceLevel,
    ParserConfidence,
    ReviewPriority,
)


class TOCREvidence(BaseModel):
    """
    Complete evidence record per Section 8.

    Every finding stores a complete evidence record with prior text,
    proposed text, field path, change classification, and triggered rules.
    """

    finding_id: str
    rule_id: str
    prior_text: str = ""
    proposed_text: str = ""
    field_path: str = ""
    change_type: ChangeType = ChangeType.MODIFICATION
    classification: ChangeClassification = ChangeClassification.ADMINISTRATIVE
    classification_confidence: ConfidenceLevel = ConfidenceLevel.DETERMINISTIC
    classification_reason: str = ""
    disclosed_in_summary: bool = False
    triggered_rules: list[str] = Field(default_factory=list)
    suppressed_rules: list[str] = Field(default_factory=list)
    parser_confidence: ParserConfidence = ParserConfidence.HIGH
    reviewer_override: Optional[str] = None

    model_config = {"extra": "forbid"}


class TOCRFinding(BaseModel):
    """
    A compliance finding produced by the rule engine.

    Each finding includes rule citation, severity, review priority,
    evidence, confidence method, guidance, and remediation.
    """

    finding_id: str
    rule_id: str
    rule_title: str
    severity: ComplianceSeverity
    review_priority: ReviewPriority
    confidence_method: ConfidenceLevel = ConfidenceLevel.DETERMINISTIC
    finding_text: str = ""
    guidance: str = ""
    remediation: str = ""
    authority_basis: list[str] = Field(default_factory=list)
    evidence: Optional[TOCREvidence] = None

    model_config = {"extra": "forbid"}

    @property
    def is_critical(self) -> bool:
        return self.severity == ComplianceSeverity.CRITICAL

    @property
    def severity_score(self) -> int:
        """Numeric score for compliance calculation (Section 6.3)."""
        return {
            ComplianceSeverity.CRITICAL: 20,
            ComplianceSeverity.HIGH: 10,
            ComplianceSeverity.MEDIUM: 5,
            ComplianceSeverity.LOW: 1,
        }[self.severity]
