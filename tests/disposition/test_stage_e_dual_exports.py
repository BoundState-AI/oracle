"""Stage E — Appendix-A + readiness roadmap exports. BoundState AI 2026."""

from __future__ import annotations

from oracle.disposition.actions import ActionRecord
from oracle.disposition.export import (
    ADVISORY_BANNER,
    export_appendix_a,
    export_dual_products,
    export_readiness_roadmap,
)
from oracle.disposition.golden import run_golden_session
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.session import DispositionSession


def test_appendix_a_and_roadmap_for_golden(tmp_path):
    run_golden_session(tmp_path / "g", export_dir=None)
    s = DispositionSession(tmp_path / "g")
    s.resume(actor_name="golden-operator", repin=True)
    for uid in list(s.units_needing_rereview()):
        s.clear_rereview(uid, actor_name="op")
    s.record_action(
        ActionRecord(
            action_id="EFCP-01",
            title="Obtain EFCP",
            owner="program.mp",
            deliverable="EFCP",
            exit_criteria="plan.EFCP confirmed",
            work_package="fracture-control",
            affected_unit_ids=("AMR-14",),
        ),
        actor_name="op",
    )
    recs, _ = load_rdw_default_packs(repin=True)
    records = {r.requirement_id: r for r in recs}
    app = export_appendix_a(s, records, tmp_path / "app_a.csv", include_draft=True)
    text = app.read_text(encoding="utf-8")
    assert ADVISORY_BANNER in text
    assert "Section" in text
    assert "AMR-14" in text
    road = export_readiness_roadmap(s, records, tmp_path / "road.md")
    rtext = road.read_text(encoding="utf-8")
    assert "readiness_counts=" in rtext
    assert "EFCP-01" in rtext or "AMR-14" in rtext
    paths = export_dual_products(s, records, tmp_path / "dual", include_draft=True)
    assert paths["appendix_a"].is_file()
    assert paths["roadmap"].is_file()
    assert paths["csv"].is_file()
