#!/usr/bin/env python3
"""
Module: oracle.disposition.export_map
Purpose: RDW §7.1 export-label mapping from independent axes (derived view only).

The six axes are the system of record. Customer labels and the five engine
codes are computed views. Every reachable combination maps to exactly one
export label or one named contradiction.

Safety Critical: advisory-only per spec D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from oracle.disposition.codes import (
    Applicability,
    ApprovalState,
    DispositionCode,
    ExportLabel,
    ImplementationState,
    ObligatedActor,
    OrgResponsibility,
    TBDReason,
)

LOGGER = logging.getLogger("oracle.disposition.export_map")


class AxisContradiction(ValueError):
    """Named contradiction between axes (RDW §10.3 / §7.1 truth table)."""

    def __init__(self, name: str, detail: str):
        self.name = name
        super().__init__(f"{name}: {detail}")


@dataclass(frozen=True)
class AxisSnapshot:
    """Pure axis values for mapping (no workflow / identity)."""

    applicability: Applicability
    obligated_actor: Optional[ObligatedActor]
    organization_responsibility: OrgResponsibility
    implementation_state: ImplementationState
    approval_state: ApprovalState
    applicability_tbd_reason: Optional[TBDReason] = None
    org_responsibility_tbd_reason: Optional[TBDReason] = None
    implementation_tbd_reason: Optional[TBDReason] = None
    approval_tbd_reason: Optional[TBDReason] = None


def validate_tbd_reasons(snap: AxisSnapshot) -> None:
    """TBD validity gate: every TBD axis carries exactly one closed reason."""
    if snap.applicability == "tbd" and snap.applicability_tbd_reason is None:
        raise AxisContradiction(
            "tbd_validity",
            "applicability=TBD requires applicability_tbd_reason",
        )
    if snap.organization_responsibility == "tbd" and snap.org_responsibility_tbd_reason is None:
        raise AxisContradiction(
            "tbd_validity",
            "organization_responsibility=TBD requires org_responsibility_tbd_reason",
        )
    if snap.implementation_state == "tbd" and snap.implementation_tbd_reason is None:
        raise AxisContradiction(
            "tbd_validity",
            "implementation_state=TBD requires implementation_tbd_reason",
        )
    if snap.approval_state == "tbd" and snap.approval_tbd_reason is None:
        raise AxisContradiction(
            "tbd_validity",
            "approval_state=TBD requires approval_tbd_reason",
        )
    if snap.applicability != "tbd" and snap.applicability_tbd_reason is not None:
        raise AxisContradiction(
            "tbd_validity",
            "applicability_tbd_reason only allowed when applicability=TBD",
        )
    if (
        snap.organization_responsibility != "tbd"
        and snap.org_responsibility_tbd_reason is not None
    ):
        raise AxisContradiction(
            "tbd_validity",
            "org_responsibility_tbd_reason only allowed when organization_responsibility=TBD",
        )
    if snap.implementation_state != "tbd" and snap.implementation_tbd_reason is not None:
        raise AxisContradiction(
            "tbd_validity",
            "implementation_tbd_reason only allowed when implementation_state=TBD",
        )
    if snap.approval_state != "tbd" and snap.approval_tbd_reason is not None:
        raise AxisContradiction(
            "tbd_validity",
            "approval_tbd_reason only allowed when approval_state=TBD",
        )


def validate_applicability_coherence(snap: AxisSnapshot) -> None:
    """applicability No + active implementation is a contradiction."""
    if snap.applicability != "no":
        return
    active = {"meets_as_written", "alternate_proposed", "partial", "not_met"}
    if snap.implementation_state in active:
        raise AxisContradiction(
            "applicability_coherence",
            "applicability No cannot pair with implementation "
            f"{snap.implementation_state!r} (nothing to implement)",
        )


def validate_actor_coherence(snap: AxisSnapshot) -> None:
    """owner responsibility cannot claim an exclusively external obligation."""
    if snap.applicability != "yes":
        return
    if (
        snap.organization_responsibility == "owner"
        and snap.obligated_actor is None
    ):
        raise AxisContradiction(
            "actor_coherence",
            "organization_responsibility=owner requires an obligated_actor when applicable",
        )
    # external responsibility never forces applicability No (checked elsewhere);
    # owner + no local actor when actor is pure external program role is allowed
    # only when org_responsibility is external/support.


def map_axes_to_export_label(snap: AxisSnapshot) -> ExportLabel:
    """
    RDW §7.1 deterministic mapping.

    Raises AxisContradiction for unreachable/invalid combinations.
    Applicability is decided first so N/A is not swallowed by downstream TBDs.
    """
    validate_tbd_reasons(snap)
    validate_applicability_coherence(snap)
    validate_actor_coherence(snap)

    if snap.applicability == "tbd":
        return ExportLabel.TBD

    if snap.applicability == "no":
        return ExportLabel.NA

    # applicability == yes — unresolved subordinate axes → TBD
    if (
        snap.organization_responsibility == "tbd"
        or snap.implementation_state == "tbd"
        or snap.approval_state == "tbd"
    ):
        return ExportLabel.TBD

    impl = snap.implementation_state
    appr = snap.approval_state

    if impl == "meets_as_written":
        if appr in ("not_required", "approved"):
            return ExportLabel.MEET
        if appr == "rejected":
            return ExportLabel.OPEN_NOT_MET
        if appr in ("required", "draft", "submitted"):
            return ExportLabel.TBD
        raise AxisContradiction("export_coherence", f"unmapped approval for Meet path: {appr}")

    if impl == "alternate_proposed":
        # Guard 1: Meets Intent never under a compliance heading.
        return ExportLabel.MEETS_INTENT

    if impl == "partial":
        if appr == "not_required":
            return ExportLabel.OPEN_NOT_MET
        return ExportLabel.MEETS_INTENT

    if impl == "not_met":
        if appr == "not_required":
            return ExportLabel.OPEN_NOT_MET
        if appr in ("required", "draft", "submitted", "approved", "rejected"):
            return ExportLabel.EXCEPTION
        raise AxisContradiction("export_coherence", f"unmapped approval for not_met: {appr}")

    if impl == "not_reached":
        raise AxisContradiction(
            "applicability_coherence",
            "implementation not_reached is only valid when applicability is No",
        )

    raise AxisContradiction(
        "export_coherence",
        f"unmapped implementation_state={impl!r} with applicability=yes",
    )


def export_label_to_code(label: ExportLabel) -> DispositionCode:
    """Five-code derived view. Open/Not Met collapses to OPEN (inexpressible otherwise)."""
    return {
        ExportLabel.MEET: DispositionCode.CW,
        ExportLabel.MEETS_INTENT: DispositionCode.MI,
        ExportLabel.EXCEPTION: DispositionCode.EX,
        ExportLabel.NA: DispositionCode.NA,
        ExportLabel.TBD: DispositionCode.OPEN,
        ExportLabel.OPEN_NOT_MET: DispositionCode.OPEN,
    }[label]


def export_label_composition_key(label: ExportLabel) -> str:
    """Stable composition-vector key for roll-ups over export labels."""
    return {
        ExportLabel.MEET: "CW",
        ExportLabel.MEETS_INTENT: "MI",
        ExportLabel.EXCEPTION: "EX",
        ExportLabel.NA: "NA",
        ExportLabel.TBD: "OPEN",
        ExportLabel.OPEN_NOT_MET: "ONM",
    }[label]


def axes_from_legacy_code(
    code: str | DispositionCode,
    *,
    open_sub_reason: Optional[TBDReason | str] = None,
) -> dict:
    """
    Expand a legacy five-code into default axes for S1 port / migration.

    Used only as a construction convenience when axes are not supplied.
    """
    c = code.value if isinstance(code, DispositionCode) else str(code)
    if c == "CW":
        return {
            "applicability": "yes",
            "obligated_actor": "producer",
            "organization_responsibility": "owner",
            "implementation_state": "meets_as_written",
            "approval_state": "not_required",
        }
    if c == "MI":
        return {
            "applicability": "yes",
            "obligated_actor": "producer",
            "organization_responsibility": "owner",
            "implementation_state": "alternate_proposed",
            "approval_state": "required",
        }
    if c == "EX":
        return {
            "applicability": "yes",
            "obligated_actor": "producer",
            "organization_responsibility": "owner",
            "implementation_state": "not_met",
            "approval_state": "required",
        }
    if c == "NA":
        return {
            "applicability": "no",
            "obligated_actor": None,
            "organization_responsibility": "external",
            "implementation_state": "not_reached",
            "approval_state": "not_required",
        }
    if c == "OPEN":
        # Without open_sub_reason, leave TBD reasons unset so construction fails closed.
        reason: Optional[TBDReason] = None
        if open_sub_reason is not None:
            reason = (
                TBDReason(open_sub_reason)
                if isinstance(open_sub_reason, str)
                else open_sub_reason
            )
        return {
            "applicability": "tbd",
            "obligated_actor": None,
            "organization_responsibility": "tbd",
            "implementation_state": "tbd",
            "approval_state": "tbd",
            "applicability_tbd_reason": reason,
            "org_responsibility_tbd_reason": reason,
            "implementation_tbd_reason": reason,
            "approval_tbd_reason": reason,
        }
    raise ValueError(f"Unknown legacy code for axis expansion: {c!r}")
