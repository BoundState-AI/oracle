#!/usr/bin/env python3
"""
Module: oracle.disposition.coherence
Purpose: RDW §10.3 axis-consistency gates as pure validators.

All six gates raise AxisContradiction (or ValueError) on construction /
transition when violated. No I/O.

Safety Critical: advisory-only per spec D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from oracle.disposition.codes import ExportLabel, WorkflowStateValue
from oracle.disposition.export_map import (
    AxisContradiction,
    AxisSnapshot,
    map_axes_to_export_label,
    validate_actor_coherence,
    validate_applicability_coherence,
    validate_tbd_reasons,
)

LOGGER = logging.getLogger("oracle.disposition.coherence")


def snapshot_from_unit_fields(
    *,
    applicability: str,
    obligated_actor: Optional[str],
    organization_responsibility: str,
    implementation_state: str,
    approval_state: str,
    applicability_tbd_reason: Any = None,
    org_responsibility_tbd_reason: Any = None,
    implementation_tbd_reason: Any = None,
    approval_tbd_reason: Any = None,
) -> AxisSnapshot:
    """Build an AxisSnapshot from raw field values."""
    return AxisSnapshot(
        applicability=applicability,  # type: ignore[arg-type]
        obligated_actor=obligated_actor,  # type: ignore[arg-type]
        organization_responsibility=organization_responsibility,  # type: ignore[arg-type]
        implementation_state=implementation_state,  # type: ignore[arg-type]
        approval_state=approval_state,  # type: ignore[arg-type]
        applicability_tbd_reason=applicability_tbd_reason,
        org_responsibility_tbd_reason=org_responsibility_tbd_reason,
        implementation_tbd_reason=implementation_tbd_reason,
        approval_tbd_reason=approval_tbd_reason,
    )


def gate_applicability_coherence(snap: AxisSnapshot) -> None:
    validate_applicability_coherence(snap)


def gate_tbd_validity(snap: AxisSnapshot) -> None:
    validate_tbd_reasons(snap)


def gate_actor_coherence(snap: AxisSnapshot) -> None:
    validate_actor_coherence(snap)


def gate_approval_coherence(
    snap: AxisSnapshot,
    *,
    has_approval_record: bool,
    open_tailoring_action: bool = False,
) -> None:
    """
    Approval approved requires an approval record with identity fields.
    Approval not-required + open tailoring action is a contradiction.
    """
    if snap.approval_state == "approved" and not has_approval_record:
        raise AxisContradiction(
            "approval_coherence",
            "approval_state=approved requires an approval record "
            "(identity/revision/approver/date/scope)",
        )
    if snap.approval_state == "not_required" and open_tailoring_action:
        raise AxisContradiction(
            "approval_coherence",
            "approval_state=not_required cannot coexist with an open tailoring action",
        )


def gate_review_coherence(
    snap: AxisSnapshot,
    workflow_state: WorkflowStateValue,
    *,
    accepted_with_tbd: bool = False,
) -> None:
    """
    Review accepted (human_confirmed / release_approved) requires every axis
    non-TBD, or an explicit accepted-with-TBD election.
    """
    if workflow_state not in ("human_confirmed", "release_approved"):
        return
    # Model split: execution_state is the reviewable axis — the legacy view
    # can read meets_as_written while execution is TBD (CW commitment).
    has_tbd = (
        snap.applicability == "tbd"
        or snap.organization_responsibility == "tbd"
        or snap.execution_state == "tbd"
        or snap.approval_state == "tbd"
    )
    if has_tbd and not accepted_with_tbd:
        raise AxisContradiction(
            "review_coherence",
            "review accepted requires every axis non-TBD or an explicit "
            "accepted-with-TBD election naming the TBD reason and owner",
        )


def gate_export_coherence(
    snap: AxisSnapshot,
    claimed_label: Optional[ExportLabel | str],
) -> ExportLabel:
    """Exported label must equal the §7.1 mapping of current axes."""
    computed = map_axes_to_export_label(snap)
    if claimed_label is None:
        return computed
    claimed = (
        claimed_label
        if isinstance(claimed_label, ExportLabel)
        else ExportLabel(str(claimed_label))
    )
    if claimed != computed:
        raise AxisContradiction(
            "export_coherence",
            f"claimed export label {claimed.value!r} != computed {computed.value!r}",
        )
    return computed


def run_all_coherence_gates(
    snap: AxisSnapshot,
    *,
    workflow_state: WorkflowStateValue = "proposed",
    has_approval_record: bool = False,
    open_tailoring_action: bool = False,
    accepted_with_tbd: bool = False,
    claimed_export_label: Optional[ExportLabel | str] = None,
) -> ExportLabel:
    """Run all six §10.3 gates; return the computed export label."""
    gate_tbd_validity(snap)
    gate_applicability_coherence(snap)
    gate_actor_coherence(snap)
    gate_approval_coherence(
        snap,
        has_approval_record=has_approval_record,
        open_tailoring_action=open_tailoring_action,
    )
    gate_review_coherence(
        snap, workflow_state, accepted_with_tbd=accepted_with_tbd
    )
    return gate_export_coherence(snap, claimed_export_label)
