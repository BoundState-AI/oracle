"""Stage A — readiness truth table, ActionRecord, EX gate, raw answers."""

from __future__ import annotations

import pytest

from oracle.disposition.actions import ActionRecord, migrate_string_action
from oracle.disposition.readiness import ReadinessLabel, map_readiness
from oracle.disposition.session import DispositionSession, SessionError, UnitAxesState


def test_action_record_roundtrip_and_replay(tmp_path):
    s = DispositionSession(tmp_path / "a")
    s.open(actor_name="op")
    act = ActionRecord(
        action_id="GOV-01",
        title="Obtain EFCP",
        owner="program.mp",
        deliverable="Approved EFCP",
        exit_criteria="plan.EFCP confirmed",
        work_package="fracture-control",
        affected_unit_ids=("AMR-14",),
    )
    s.record_action(act, actor_name="op")
    assert "GOV-01" in s.state.actions
    s2 = DispositionSession(tmp_path / "a")
    s2.resume(actor_name="op", repin=False)
    assert "GOV-01" in s2.state.actions
    assert s2.state.actions["GOV-01"].owner == "program.mp"


def test_raw_answer_retention_on_replay(tmp_path):
    s = DispositionSession(tmp_path / "raw")
    s.open(actor_name="op")
    s.record_answer("AMR-1", "applicability.AMR-1", "yes — cold spray", actor_name="op")
    s2 = DispositionSession(tmp_path / "raw")
    s2.resume(actor_name="op", repin=False)
    assert any(
        a["raw"] == "yes — cold spray" and a["unit_id"] == "AMR-1"
        for a in s2.state.raw_answers
    )


def test_ex_closure_gate(tmp_path):
    s = DispositionSession(tmp_path / "ex")
    s.open(actor_name="op")
    # Exception path: not_met + required approval + local owner
    with pytest.raises(SessionError, match="exception_basis"):
        s.set_axes(
            "AMR-3",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="not_met",
            approval_state="required",
        )
    with pytest.raises(SessionError, match="closure_path|permanent_relief"):
        s.set_axes(
            "AMR-3",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="not_met",
            approval_state="required",
            exception_basis="unique geometry prevents as-written control",
        )
    # With permanent relief — allowed
    u = s.set_axes(
        "AMR-3",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="not_met",
        approval_state="required",
        exception_basis="unique geometry prevents as-written control",
        permanent_relief_basis="TA concurrence memo R-9",
    )
    assert u.export_label().value == "Exception"


def test_readiness_truth_table_exhaustive():
    """Every readiness label reachable; priority order holds."""
    base = dict(
        unit_id="U",
        obligated_actor="producer",
    )
    plan = ActionRecord(
        action_id="A1",
        title="Close gap",
        owner="qa",
        exit_criteria="evidence on file",
        affected_unit_ids=("U",),
    )

    # Not Yet Due
    u = UnitAxesState(
        **base,
        applicability="yes",
        organization_responsibility="owner",
        implementation_state="not_met",
        approval_state="not_required",
        not_yet_due=True,
        not_yet_due_justification="levied prior to flight-hardware production",
    )
    assert map_readiness(u, [plan]).label == ReadinessLabel.NOT_YET_DUE

    # Technical N/A
    u = UnitAxesState(
        **base,
        applicability="no",
        organization_responsibility="external",
        implementation_state="not_reached",
        approval_state="not_required",
        scope_citation="polymer only; out of metal AM scope",
    )
    assert map_readiness(u).label == ReadinessLabel.TECHNICAL_NA

    # TBD Verify
    u = UnitAxesState(
        unit_id="U",
        applicability="tbd",
        applicability_tbd_reason="classification_unresolved",
        organization_responsibility="tbd",
        org_responsibility_tbd_reason="classification_unresolved",
        implementation_state="tbd",
        implementation_tbd_reason="classification_unresolved",
        approval_state="tbd",
        approval_tbd_reason="classification_unresolved",
    )
    assert map_readiness(u).label == ReadinessLabel.TBD_VERIFY

    # External Action
    u = UnitAxesState(
        **base,
        applicability="yes",
        organization_responsibility="external",
        implementation_state="not_met",
        approval_state="required",
    )
    assert map_readiness(u, [plan]).label == ReadinessLabel.EXTERNAL_ACTION

    # Met
    u = UnitAxesState(
        **base,
        applicability="yes",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    assert (
        map_readiness(u, has_qualifying_evidence=True).label == ReadinessLabel.MET
    )

    # Not Met with Plan
    u = UnitAxesState(
        **base,
        applicability="yes",
        organization_responsibility="owner",
        implementation_state="not_met",
        approval_state="not_required",
    )
    assert map_readiness(u, [plan]).label == ReadinessLabel.NOT_MET_WITH_PLAN

    # migrate string
    m = migrate_string_action("Obtain EFCP", unit_id="AMR-14")
    assert m.action_id.startswith("LEGACY-")
