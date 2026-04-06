#!/usr/bin/env python3
"""
Module: TOCR Remediation Models
Purpose: Remediation plan and step models — tell users exactly how to fix their TOs.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 12 (Remediation Advisory)
"""

__version__ = "1.0.0"

from typing import Optional

from pydantic import BaseModel, Field

from sentinel.tocr.models.enums import ComplianceSeverity, ReviewPriority


class RemediationStep(BaseModel):
    """
    A single, actionable fix step tied to a specific finding.

    Each step tells the user:
    - What to fix (field_path, what_to_fix)
    - How to fix it (how_to_fix — specific, contextual instructions)
    - Why it matters (why_it_matters)
    - Who needs to act (owner)
    - How urgent it is (severity, priority_order)
    """

    finding_id: str
    rule_id: str
    rule_title: str
    severity: ComplianceSeverity
    review_priority: ReviewPriority
    priority_order: int = 0

    field_path: str = ""
    what_to_fix: str = ""
    how_to_fix: str = ""
    why_it_matters: str = ""
    owner: str = ""
    authority_basis: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class RemediationPlan(BaseModel):
    """
    Complete remediation plan — a prioritized checklist of fix steps.

    Generated from compliance findings, ordered by severity then priority.
    Intended to be handed directly to the task lead as a to-do list.
    """

    steps: list[RemediationStep] = Field(default_factory=list)
    total_steps: int = 0
    critical_steps: int = 0
    high_steps: int = 0
    medium_steps: int = 0
    low_steps: int = 0
    estimated_owners: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @property
    def has_blockers(self) -> bool:
        """True if any CRITICAL steps exist — these block release."""
        return self.critical_steps > 0

    @property
    def is_empty(self) -> bool:
        return self.total_steps == 0
