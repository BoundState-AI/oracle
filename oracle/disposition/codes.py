#!/usr/bin/env python3
"""
Module: oracle.disposition.codes
Purpose: Closed enumerations for disposition codes and OPEN sub-reasons (§2, §2.3).

All values are known at construction time. Unknown codes or sub-reasons are
impossible by design — they are rejected before any downstream logic runs.

Safety Critical: advisory-only per spec D-1

__safety_critical__: bool = False  # advisory-only per D-1 (S1 is pure data + state)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Literal

LOGGER = logging.getLogger("oracle.disposition.codes")


# Single source of truth for workflow state values (consolidated from prior split definitions).
# Used by models.py, state.py, and tests. Defined here to keep the closed vocabulary in one place.
WorkflowStateValue = Literal[
    "proposed",
    "human_confirmed",
    "release_approved",
    "rejected",
]


class DispositionCode(str, Enum):
    """
    The five canonical disposition codes per spec §2.

    CW  — Complies as written
    MI  — Intent met by alternative means (exception requiring acceptance)
    EX  — Exception requested
    NA  — Not applicable (must cite scope declaration)
    OPEN — Evidence or decision incomplete (never releasable)
    """

    CW = "CW"
    MI = "MI"
    EX = "EX"
    NA = "NA"
    OPEN = "OPEN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class OPENSubReason(str, Enum):
    """
    Closed vocabulary for OPEN sub-reasons (§2.3).

    Every OPEN unit carries exactly one value from this set.
    Extending the vocabulary is a spec change, not an implementation edit.
    """

    EVIDENCE_ABSENT = "evidence_absent"
    SCOPE_DECISION_NOT_MADE = "scope_decision_not_made"
    AUTHORITY_UNIDENTIFIED = "authority_unidentified"
    APPROVAL_NOT_EXERCISED = "approval_not_exercised"
    REFERENCED_ARTIFACT_MISSING = "referenced_artifact_missing"
    REFERENCED_STANDARD_UNAVAILABLE = "referenced_standard_unavailable"
    REFERENCE_SEMANTICS_UNRESOLVED = "reference_semantics_unresolved"
    DEPENDENCY_ELIMINATED = "dependency_eliminated"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Convenience sets for fast membership checks in validation
DISPOSITION_CODES: frozenset[str] = frozenset(c.value for c in DispositionCode)
OPEN_SUBREASONS: frozenset[str] = frozenset(r.value for r in OPENSubReason)
