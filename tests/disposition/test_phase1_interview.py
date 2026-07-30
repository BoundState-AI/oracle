"""Phase 1 — Interview MVP: golden session, decisions, propagation. BoundState AI 2026."""

from __future__ import annotations

from oracle.disposition.decision import evaluate_unit
from oracle.disposition.golden import run_golden_session
from oracle.disposition.session import DispositionSession


def test_phase1_golden_session_labels(tmp_path):
    result = run_golden_session(tmp_path / "g1", export_dir=tmp_path / "g1-out")
    assert result["labels"]["AMR-17"] == "TBD"
    assert "classification_unresolved" in result["amr17_tbd_reason"]
    assert result["labels"]["AMR-14"] == "Open/Not Met"
    # AC-3: program-applicable + external approval → Open/Not Met (not Exception)
    assert result["labels"]["AMR-1"] == "Open/Not Met"
    assert result["ceo_assumed"] is True
    assert result["export_paths"]
    # Classification Class A marks dependents for re-review (durable)
    assert any(u.startswith("AMR-") for u in result["rereview_after_class_a"])
    # H1: re-review survives resume
    from oracle.disposition.session import DispositionSession

    s2 = DispositionSession(tmp_path / "g1")
    s2.resume(actor_name="golden-operator", repin=False)
    assert any(u.startswith("AMR-") for u in s2.units_needing_rereview())


def test_phase1_amr2_blocked_without_amcp(tmp_path):
    import pytest
    from oracle.disposition.session import SessionError, UnitAxesState

    s = DispositionSession(tmp_path / "s")
    s.open(actor_name="a", multi_pack=True)
    # C1: election of Meet without AMCP must be refused
    with pytest.raises(SessionError, match="blocked|AMCP|evidence|Meet"):
        s.set_axes(
            "AMR-2",
            actor_name="a",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="meets_as_written",
            approval_state="not_required",
        )
    probe = UnitAxesState(
        unit_id="AMR-2",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    d = evaluate_unit(probe, facts=s.state.facts)
    assert "Meet" in d.blocked
    assert "AMCP" in d.blocked["Meet"] or any("AMCP" in b for b in d.blockers_meet)


def test_phase1_assumption_not_confirmed(tmp_path):
    s = DispositionSession(tmp_path / "s2")
    s.open(actor_name="a")
    s.assert_fact(
        key="ceo.identity",
        statement="Customer assumed CEO",
        author="a",
        assumed=True,
        owner="a",
    )
    assert s.state.facts["ceo.identity"].assumed is True
    assert s.state.facts["ceo.identity"].confirmed is False
