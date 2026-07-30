"""RDW §10.3 axis-coherence gates. BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.codes import ExportLabel, TBDReason
from oracle.disposition.coherence import run_all_coherence_gates, snapshot_from_unit_fields
from oracle.disposition.export_map import AxisContradiction


def test_all_six_gates_pass_on_clean_meet():
    snap = snapshot_from_unit_fields(
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    label = run_all_coherence_gates(snap, workflow_state="proposed")
    assert label == ExportLabel.MEET


def test_approval_approved_requires_record():
    snap = snapshot_from_unit_fields(
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="approved",
    )
    with pytest.raises(AxisContradiction) as ei:
        run_all_coherence_gates(snap, has_approval_record=False)
    assert ei.value.name == "approval_coherence"

    label = run_all_coherence_gates(snap, has_approval_record=True)
    assert label == ExportLabel.MEET


def test_review_coherence_blocks_tbd_without_election():
    snap = snapshot_from_unit_fields(
        applicability="tbd",
        obligated_actor=None,
        organization_responsibility="tbd",
        implementation_state="tbd",
        approval_state="tbd",
        applicability_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
        org_responsibility_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
        implementation_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
        approval_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
    )
    with pytest.raises(AxisContradiction) as ei:
        run_all_coherence_gates(snap, workflow_state="human_confirmed")
    assert ei.value.name == "review_coherence"

    label = run_all_coherence_gates(
        snap, workflow_state="human_confirmed", accepted_with_tbd=True
    )
    assert label == ExportLabel.TBD


def test_not_required_plus_open_tailoring_contradiction():
    snap = snapshot_from_unit_fields(
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    with pytest.raises(AxisContradiction) as ei:
        run_all_coherence_gates(snap, open_tailoring_action=True)
    assert ei.value.name == "approval_coherence"
