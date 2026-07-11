#!/usr/bin/env python3
"""
Module: TOCR Rule Model
Purpose: Rule schema per Section 5 — no hard-coded logic, all rules are configuration.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 5

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: True
"""

__version__ = "1.0.0"

from typing import Optional

from pydantic import BaseModel, Field

from sentinel.tocr.models.enums import (
    BasisType,
    ComplianceSeverity,
    ConfidenceLevel,
    ReviewPriority,
)


class RuleApplicability(BaseModel):
    """Applicability conditions for a rule (Section 5, 9)."""

    contract_type: Optional[list[str]] = None
    agency: Optional[list[str]] = None
    local_pack: Optional[list[str]] = None
    clause_required: Optional[list[str]] = None
    revision_status: Optional[list[str]] = None

    # Why extra="allow": Rule packs are user-authored JSON that may carry
    # metadata fields (notes, change_history, author) the engine ignores.
    # Forbidding extras would reject valid rule packs on import.
    model_config = {"extra": "allow"}


class RuleTrigger(BaseModel):
    """Trigger conditions for a rule (Section 5)."""

    all: list[str] = Field(default_factory=list)
    any: list[str] = Field(default_factory=list)

    # Why extra="allow": Rule packs are user-authored JSON that may carry
    # metadata fields (notes, change_history, author) the engine ignores.
    # Forbidding extras would reject valid rule packs on import.
    model_config = {"extra": "allow"}


class TOCRRule(BaseModel):
    """
    TOCR rule per the schema in Section 5.

    No hard-coded logic. All rules are configuration.
    Every rule conforms to this schema.
    """

    rule_id: str
    title: str
    basis_type: BasisType
    authority_basis: list[str] = Field(default_factory=list)
    applicability: RuleApplicability = Field(default_factory=RuleApplicability)
    trigger: RuleTrigger = Field(default_factory=RuleTrigger)
    finding: str = ""
    severity: ComplianceSeverity = ComplianceSeverity.MEDIUM
    review_priority: ReviewPriority = ReviewPriority.ADVISORY
    confidence_method: ConfidenceLevel = ConfidenceLevel.DETERMINISTIC
    guidance: str = ""
    remediation: str = ""

    # Why extra="allow": Rule packs are user-authored JSON that may carry
    # metadata fields (notes, change_history, author) the engine ignores.
    # Forbidding extras would reject valid rule packs on import.
    model_config = {"extra": "allow"}
