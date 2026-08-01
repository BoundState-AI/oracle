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
    ExecutionState,
    ExportLabel,
    FulfillmentPath,
    ImplementationState,
    ObligatedActor,
    OrgResponsibility,
    TBDReason,
    split_from_legacy,
)

LOGGER = logging.getLogger("oracle.disposition.export_map")


class AxisContradiction(ValueError):
    """Named contradiction between axes (RDW §10.3 / §7.1 truth table)."""

    def __init__(self, name: str, detail: str):
        self.name = name
        super().__init__(f"{name}: {detail}")


@dataclass(frozen=True)
class AxisSnapshot:
    """Pure axis values for mapping (no workflow / identity).

    Model split: fulfillment_path/execution_state are the decision inputs.
    Legacy constructors that supply only implementation_state get the
    validated migration applied in __post_init__ — one conversion point.
    """

    applicability: Applicability
    obligated_actor: Optional[ObligatedActor]
    organization_responsibility: OrgResponsibility
    implementation_state: ImplementationState
    approval_state: ApprovalState
    applicability_tbd_reason: Optional[TBDReason] = None
    org_responsibility_tbd_reason: Optional[TBDReason] = None
    implementation_tbd_reason: Optional[TBDReason] = None
    approval_tbd_reason: Optional[TBDReason] = None
    fulfillment_path: Optional[FulfillmentPath] = None
    execution_state: Optional[ExecutionState] = None

    def __post_init__(self) -> None:
        if self.fulfillment_path is None or self.execution_state is None:
            ful, execu = split_from_legacy(
                self.implementation_state,
                self.applicability,
                self.approval_state,
            )
            object.__setattr__(
                self, "fulfillment_path", self.fulfillment_path or ful
            )
            object.__setattr__(
                self, "execution_state", self.execution_state or execu
            )


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
    # Model split: the implementation reason tracks EXECUTION tbd-ness —
    # the legacy view can be non-TBD (a commitment) while execution is TBD.
    if snap.execution_state == "tbd" and snap.implementation_tbd_reason is None:
        raise AxisContradiction(
            "tbd_validity",
            "execution_state=TBD requires implementation_tbd_reason",
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
    if snap.execution_state != "tbd" and snap.implementation_tbd_reason is not None:
        raise AxisContradiction(
            "tbd_validity",
            "implementation_tbd_reason only allowed when execution_state=TBD",
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
    RDW §7.1 deterministic mapping — CONTRACT label from the fulfillment
    ELECTION, never from execution (model split, Fran P0). Execution is
    consulted only to distinguish TBD from Open/Not Met when no
    commitment has been elected.

    Raises AxisContradiction for unreachable/invalid combinations.
    Applicability is decided first so N/A is not swallowed by downstream
    TBDs. Prototype-validated identical to the pre-split table on every
    legacy combination (RDW_MODEL_SPLIT_SPEC.md).
    """
    validate_tbd_reasons(snap)
    validate_applicability_coherence(snap)
    validate_actor_coherence(snap)

    ful = snap.fulfillment_path
    execu = snap.execution_state
    appr = snap.approval_state

    if snap.applicability == "tbd":
        return ExportLabel.TBD

    if snap.applicability == "no":
        if ful not in ("not_applicable", "tbd"):
            raise AxisContradiction(
                "applicability_coherence",
                f"applicability No cannot pair with a committed fulfillment "
                f"path {ful!r}",
            )
        return ExportLabel.NA

    # applicability == yes — unresolved subordinate axes → TBD
    if snap.organization_responsibility == "tbd" or appr == "tbd":
        return ExportLabel.TBD

    # preserved legacy rule (frozen-table position): not_reached while
    # applicable is a contradiction, never laundered into Open/Not Met
    if snap.implementation_state == "not_reached":
        raise AxisContradiction(
            "applicability_coherence",
            "implementation not_reached is only valid when applicability is No",
        )

    if ful == "not_applicable":
        raise AxisContradiction(
            "applicability_coherence",
            "fulfillment not_applicable requires applicability No",
        )

    if ful == "as_written":
        if appr == "rejected":
            return ExportLabel.OPEN_NOT_MET
        if appr in ("required", "draft", "submitted"):
            return ExportLabel.TBD
        return ExportLabel.MEET  # not_required | approved

    if ful == "alternative_intent":
        # Rejected tailoring must not claim Meets Intent (review C2).
        if appr == "rejected":
            return ExportLabel.OPEN_NOT_MET
        # Guard 1: Meets Intent never under a compliance heading.
        return ExportLabel.MEETS_INTENT

    if ful == "exception":
        # Rejected relief is not a live Exception (review C2).
        if appr == "rejected":
            return ExportLabel.OPEN_NOT_MET
        # External responsibility: approval pending elsewhere is Open/Not
        # Met, not Exception — AC-3 AMR-1.
        if snap.organization_responsibility == "external":
            return ExportLabel.OPEN_NOT_MET
        if appr == "not_required":
            raise AxisContradiction(
                "export_coherence",
                "exception fulfillment requires a relief approval path",
            )
        return ExportLabel.EXCEPTION

    # ful == tbd — no commitment elected
    if execu == "tbd":
        return ExportLabel.TBD
    return ExportLabel.OPEN_NOT_MET


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
