"""Phase 3 — Review controls + audit lineage. BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.audit import build_lineage
from oracle.disposition.evidence import EvidenceStore
from oracle.disposition.golden import run_golden_session
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.review import ReviewPackage, create_review_package
from oracle.disposition.session import DispositionSession


def test_phase3_review_assignment_and_accept(tmp_path):
    run_golden_session(tmp_path / "g")
    s = DispositionSession(tmp_path / "g")
    s.resume(actor_name="golden-operator", repin=True)
    pkg = create_review_package(
        s.state.session_id,
        created_by="lead",
        unit_ids=["AMR-14", "AMR-17"],
    )
    pkg.assign("AMR-14", "tech.reviewer", "technical_reviewer", assigned_by="lead")
    pkg.assign("AMR-17", "tech.reviewer", "technical_reviewer", assigned_by="lead")
    pkg.decide(
        "AMR-14",
        decision="accepted",
        reviewer="tech.reviewer",
        role="technical_reviewer",
        comment="Open/Not Met correct without EFCP",
    )
    with pytest.raises(ValueError, match="not assigned"):
        pkg.decide(
            "AMR-17",
            decision="accepted",
            reviewer="stranger",
            role="technical_reviewer",
        )
    pkg.decide(
        "AMR-17",
        decision="accepted",
        reviewer="tech.reviewer",
        role="technical_reviewer",
    )
    assert pkg.is_package_accepted(["AMR-14", "AMR-17"])
    path = tmp_path / "review.json"
    pkg.save(path)
    loaded = ReviewPackage.load(path)
    assert loaded.decisions[-1].unit_id == "AMR-17"


def test_phase3_audit_lineage(tmp_path):
    run_golden_session(tmp_path / "g2")
    s = DispositionSession(tmp_path / "g2")
    s.resume(actor_name="golden-operator", repin=True)
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
    lin = build_lineage(
        "AMR-14", s, records, evidence_store=store
    )
    assert lin.unit_id == "AMR-14"
    assert lin.export_label == "Open/Not Met"
    assert lin.source_text  # from pack
    assert lin.events  # session events
    assert any(e["doc_id"] == "NOTE" for e in lin.evidence)
