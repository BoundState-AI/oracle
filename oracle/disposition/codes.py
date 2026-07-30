#!/usr/bin/env python3
"""
Module: oracle.disposition.codes
Purpose: Closed enumerations for disposition axes, export labels, codes, TBD reasons.

Axes are the system of record (RDW §7). The five engine codes (CW/MI/EX/NA/OPEN)
and customer export labels are derived views (RDW §7.1).

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


# Single source of truth for workflow state values (Review axis = engine §7.1).
WorkflowStateValue = Literal[
    "proposed",
    "human_confirmed",
    "release_approved",
    "rejected",
]


# ---------------------------------------------------------------------------
# Six independent axes (RDW §7)
# ---------------------------------------------------------------------------

Applicability = Literal["yes", "no", "tbd"]
ObligatedActor = Literal["program", "ceo", "producer", "supplier", "subtier", "other"]
OrgResponsibility = Literal["owner", "support", "external", "tbd"]
# not_reached: only legal when applicability is No (migration "—" cells)
ImplementationState = Literal[
    "meets_as_written",
    "alternate_proposed",
    "partial",
    "not_met",
    "tbd",
    "not_reached",
]
ApprovalState = Literal[
    "not_required",
    "required",
    "draft",
    "submitted",
    "approved",
    "rejected",
    "tbd",
]


class DispositionCode(str, Enum):
    """
    The five canonical disposition codes — derived export view (RDW §7.1).

    CW  — Complies as written ≈ Meet
    MI  — Intent met by alternative means ≈ Meets Intent
    EX  — Exception requested ≈ Exception
    NA  — Not applicable ≈ N/A
    OPEN — Evidence or decision incomplete ≈ TBD (Open/Not Met also collapses here
           in the five-code view; the six-label view preserves the distinction)
    """

    CW = "CW"
    MI = "MI"
    EX = "EX"
    NA = "NA"
    OPEN = "OPEN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ExportLabel(str, Enum):
    """Customer-facing export labels (RDW §7.1). Never the system of record."""

    MEET = "Meet"
    MEETS_INTENT = "Meets Intent"
    NA = "N/A"
    TBD = "TBD"
    OPEN_NOT_MET = "Open/Not Met"
    EXCEPTION = "Exception"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class OPENSubReason(str, Enum):
    """
    Closed vocabulary for OPEN/TBD reasons (engine §2.3 + RDW §7).

    Every TBD on any axis carries exactly one value from this set.
    `customer_input_missing` is the RDW alias of `scope_decision_not_made`
    (both remain valid; they are distinct enum members that normalize equal
    for alias comparison via is_customer_input_reason()).
    `classification_unresolved` is new per RDW §7.
    """

    EVIDENCE_ABSENT = "evidence_absent"
    SCOPE_DECISION_NOT_MADE = "scope_decision_not_made"
    CUSTOMER_INPUT_MISSING = "customer_input_missing"
    AUTHORITY_UNIDENTIFIED = "authority_unidentified"
    APPROVAL_NOT_EXERCISED = "approval_not_exercised"
    REFERENCED_ARTIFACT_MISSING = "referenced_artifact_missing"
    REFERENCED_STANDARD_UNAVAILABLE = "referenced_standard_unavailable"
    REFERENCE_SEMANTICS_UNRESOLVED = "reference_semantics_unresolved"
    DEPENDENCY_ELIMINATED = "dependency_eliminated"
    CLASSIFICATION_UNRESOLVED = "classification_unresolved"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Alias used by axis TBD fields (same closed vocabulary)
TBDReason = OPENSubReason


def is_customer_input_reason(reason: OPENSubReason | str | None) -> bool:
    """True for customer_input_missing or its alias scope_decision_not_made."""
    if reason is None:
        return False
    val = reason.value if isinstance(reason, OPENSubReason) else str(reason)
    return val in {
        OPENSubReason.CUSTOMER_INPUT_MISSING.value,
        OPENSubReason.SCOPE_DECISION_NOT_MADE.value,
    }


# Convenience sets for fast membership checks in validation
DISPOSITION_CODES: frozenset[str] = frozenset(c.value for c in DispositionCode)
OPEN_SUBREASONS: frozenset[str] = frozenset(r.value for r in OPENSubReason)
EXPORT_LABELS: frozenset[str] = frozenset(lab.value for lab in ExportLabel)
# Composition keys for roll-ups (includes ONM for Open/Not Met)
COMPOSITION_KEYS: frozenset[str] = frozenset({"CW", "MI", "EX", "NA", "OPEN", "ONM"})


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
