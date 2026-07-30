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


class ProposalBand(str, Enum):
    """Qualitative confidence band for a machine proposal (§8).

    WHY an enum and not a float: §8 defines exactly three bands with structural
    bases — it contains no calibration data, no reference distribution, and no
    empirical reliability model. A 0.0-1.0 float labelled "calibrated
    confidence" therefore advertises precision that does not exist, and does so
    to an audience for whom "confidence" is a statistical term: these
    dispositions sit alongside A-basis and B-basis allowables (99/95 and 90/95)
    in the same submittal. A three-value enum makes the false precision
    unrepresentable rather than merely discouraged.

    HIGH   — requirement text unambiguous, scope citation direct, no authority
             dependency, no definitional remap. Reviewer skims.
    MEDIUM — disposition depends on a referenced table or subparagraph set not
             yet examined, or on a routing decision consistent with another
             open entry. Reviewer verifies against source.
    LOW    — disposition depends on a scope decision the customer has not made,
             or on process capability not established at intake. Per §8, Oracle
             proposes NOTHING: the unit is OPEN with the applicable §2.3
             sub-reason and renders to the reviewer as a question.

    Never aggregated into a package-level score (§8), and never rendered on a
    customer-facing artifact — this is internal triage.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
