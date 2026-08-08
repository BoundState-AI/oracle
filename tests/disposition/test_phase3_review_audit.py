"""Phase 3 — Single-operator attestation + audit lineage. BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.audit import build_lineage
from oracle.disposition.evidence import EvidenceStore
from oracle.disposition.golden import run_golden_session
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.session import DispositionSession, SessionError


def test_phase3_attest_coherence_and_transitions(tmp_path):
    """F6: attest_unit — coherence gate + transition legality; no assignment board."""
    run_golden_session(tmp_path / "g")
    s = DispositionSession(tmp_path / "g")
    s.resume(actor_name="golden-operator", repin=True)

    # AMR-14 is Open/Not Met with non-TBD axes → accept
    s.attest_unit(
        "AMR-14",
        actor_name="operator",
        role="technical_reviewer",
        decision="accepted",
        comment="Open/Not Met correct without EFCP",
    )
    assert s.state.units["AMR-14"].review_state == "accepted"

    # AMR-17 still TBD axes → need accepted_with_tbd
    with pytest.raises(SessionError, match="review_coherence"):
        s.attest_unit(
            "AMR-17",
            actor_name="operator",
            role="technical_reviewer",
            decision="accepted",
        )
    s.attest_unit(
        "AMR-17",
        actor_name="operator",
        role="technical_reviewer",
        decision="accepted",
        accepted_with_tbd=True,
    )
    assert s.state.units["AMR-17"].review_state == "accepted"
    assert s.state.units["AMR-17"].accepted_with_tbd is True

    # Never accepted → proposed directly
    with pytest.raises(SessionError, match="illegal review transition"):
        s.attest_unit(
            "AMR-14",
            actor_name="operator",
            role="technical_reviewer",
            decision="proposed",
        )

    # Reject from proposed/in_review only — accepted cannot go to rejected via attest
    with pytest.raises(SessionError, match="illegal review transition"):
        s.attest_unit(
            "AMR-14",
            actor_name="operator",
            role="technical_reviewer",
            decision="rejected",
        )

    # Re-open path: reject a fresh unit, then re-open to proposed
    s.set_axes(
        "AMR-1",
        actor_name="operator",
        election=False,
        enforce_decision=False,
        # leave axes as golden left them (non-TBD)
    )
    # ensure proposed
    if s.state.units["AMR-1"].review_state == "accepted":
        pass  # golden doesn't accept AMR-1
    s.attest_unit(
        "AMR-1",
        actor_name="operator",
        role="quality_reviewer",
        decision="rejected",
        comment="needs work",
    )
    assert s.state.units["AMR-1"].review_state == "rejected"
    s.attest_unit(
        "AMR-1",
        actor_name="operator",
        role="quality_reviewer",
        decision="proposed",
    )
    assert s.state.units["AMR-1"].review_state == "proposed"


def test_phase3_attest_replay_roundtrips_accepted_with_tbd(tmp_path):
    """A7/F6: resume restores review_state and accepted_with_tbd."""
    run_golden_session(tmp_path / "g_replay")
    s = DispositionSession(tmp_path / "g_replay")
    s.resume(actor_name="golden-operator", repin=True)
    s.attest_unit(
        "AMR-17",
        actor_name="operator",
        role="disposition_author",
        decision="accepted",
        accepted_with_tbd=True,
        comment="park TBD under election",
    )
    s2 = DispositionSession(tmp_path / "g_replay")
    s2.resume(actor_name="golden-operator", repin=False)
    u = s2.state.units["AMR-17"]
    assert u.review_state == "accepted"
    assert u.accepted_with_tbd is True


def test_phase3_audit_lineage(tmp_path):
    run_golden_session(tmp_path / "g2")
    s = DispositionSession(tmp_path / "g2")
    s.resume(actor_name="golden-operator", repin=True)
    s.attest_unit(
        "AMR-14",
        actor_name="operator",
        role="technical_reviewer",
        decision="accepted",
        comment="ok",
    )
    recs, _ = load_rdw_default_packs(repin=True)
    records = {r.requirement_id: r for r in recs}
    store = EvidenceStore(tmp_path / "ev")
    store.register(
        evidence_id="e1",
        doc_id="NOTE",
        revision="1",
        unit_ids=("AMR-14",),
        effective_date="2026-01-01",
        approval_date="2026-01-01",
        note="gap note",
    )
    lin = build_lineage("AMR-14", s, records, evidence_store=store)
    assert lin.unit_id == "AMR-14"
    assert lin.export_label == "Open/Not Met"
    assert lin.source_text  # from pack
    assert lin.events  # session events
    assert any(e["doc_id"] == "NOTE" for e in lin.evidence)
    # F6: review decisions from event log
    assert any(d.get("decision") == "accepted" for d in lin.review_decisions)
