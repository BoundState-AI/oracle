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
    assert result["ceo_assumed"] is True
    assert result["export_paths"]
    # Classification Class A marks dependents for re-review
    assert any(u.startswith("AMR-") for u in result["rereview_after_class_a"])


def test_phase1_amr2_blocked_without_amcp(tmp_path):
    s = DispositionSession(tmp_path / "s")
    s.open(actor_name="a", multi_pack=True)
    s.set_axes(
        "AMR-2",
        actor_name="a",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    d = evaluate_unit(s.state.units["AMR-2"], facts=s.state.facts)
    assert "MEET" in str(d.blocked).upper() or ExportLabel_MEET_blocked(d)


def ExportLabel_MEET_blocked(d) -> bool:
    return "Meet" in d.blocked or any("AMCP" in b for b in d.blockers_meet)


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
