#!/usr/bin/env python3
"""
Module: hearth.data
Purpose: Pydantic v2 data contracts for HEARTH (spec v0.3 §2, §11).

Single import surface for the six Phase-1 contracts. All models inherit
HearthModel (extra="forbid"; unknown keys are defects, not extensions).

Safety Critical: False
Financially Critical: False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

from hearth.data.audit import (
    STUB_MODEL_HASH,
    STUB_PROMPT_HASH,
    AuditArtifact,
    RunType,
)
from hearth.data.base import HearthModel
from hearth.data.buyer_pack import (
    BuyerPack,
    BuyerPackIdentity,
    Financing,
    Geography,
    HardConstraints,
    Posture,
    SoftPreference,
    Timeline,
)
from hearth.data.jurisdiction import (
    AuthorityReview,
    Governance,
    Jurisdiction,
    JurisdictionPack,
    MicroRule,
    ReviewStatus,
    RuleCategory,
)
from hearth.data.property import (
    Geocode,
    PropertyEvidence,
    PropertyIdentity,
)
from hearth.data.scrub import (
    FAIL_CLOSED_BASIS,
    SEVERITY_RANK,
    FindingCategory,
    FindingSeverity,
    ScrubFinding,
)

__all__ = [
    "AuditArtifact",
    "AuthorityReview",
    "BuyerPack",
    "BuyerPackIdentity",
    "FAIL_CLOSED_BASIS",
    "Financing",
    "FindingCategory",
    "FindingSeverity",
    "Geocode",
    "Geography",
    "Governance",
    "HardConstraints",
    "HearthModel",
    "Jurisdiction",
    "JurisdictionPack",
    "MicroRule",
    "Posture",
    "PropertyEvidence",
    "PropertyIdentity",
    "ReviewStatus",
    "RuleCategory",
    "RunType",
    "ScrubFinding",
    "SEVERITY_RANK",
    "SoftPreference",
    "STUB_MODEL_HASH",
    "STUB_PROMPT_HASH",
    "Timeline",
]
