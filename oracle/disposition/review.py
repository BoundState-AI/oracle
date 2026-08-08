#!/usr/bin/env python3
"""
Module: oracle.disposition.review
Purpose: Role vocabulary for single-operator unit attestation (RDW §5).

Multi-user review-board machinery (ReviewPackage / Assignment) was removed
per Dr. Wilde ruling 2026-07-30: this is a single-user tool. Role strings are
recorded on attestation events for audit lineage; they are not enforced
against an identity system. Multi-user enforcement parks for a later phase.

Use DispositionSession.attest_unit(...) for accept/reject transitions.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

from typing import Literal

# Six-role vocabulary — recorded on events, not enforced (single-operator).
Role = Literal[
    "disposition_author",
    "technical_reviewer",
    "quality_reviewer",
    "program_ceo_reviewer",
    "administrator",
    "auditor",
]

ReviewState = Literal[
    "not_reviewed",
    "proposed",
    "in_review",
    "accepted",
    "rejected",
    "superseded",
]

# Attestation decision vocabulary (F6). Re-open is rejected|superseded → proposed.
AttestDecision = Literal["accepted", "rejected", "proposed"]

# Legal review_state transitions via attest_unit (accepted → superseded is F1 only).
LEGAL_ATTEST_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("proposed", "accepted"),
        ("proposed", "rejected"),
        ("in_review", "accepted"),
        ("in_review", "rejected"),
        ("not_reviewed", "accepted"),
        ("not_reviewed", "rejected"),
        ("rejected", "proposed"),  # re-open
        ("superseded", "proposed"),  # re-open after F1 supersession
    }
)
