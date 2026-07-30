"""Phase 2 — Evidence & export: artifacts, gates, XLSX. BoundState AI 2026."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from oracle.disposition.evidence import EvidenceStore, evidence_supports_meet
from oracle.disposition.export import export_all, export_xlsx
from oracle.disposition.golden import run_golden_session
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.session import DispositionSession


def test_phase2_evidence_register_and_gate(tmp_path):
    store = EvidenceStore(tmp_path / "ev")
    sample = tmp_path / "as9100.txt"
    sample.write_text("certificate body", encoding="utf-8")
    art = store.register(
        evidence_id="ev-1",
        doc_id="AS9100-CERT",
        revision="2024",
        unit_ids=("AMR-45",),
        title="AS9100 certificate",
        effective_date="2024-01-01",
        approval_date="2024-01-15",
        local_file=sample,
    )
    assert art.content_hash and art.content_hash.startswith("sha256:")
    assert evidence_supports_meet(art).ok
    assert store.unit_has_qualifying_meet_evidence("AMR-45")

    # Expired fails gate
    exp = store.register(
        evidence_id="ev-2",
        doc_id="OLD",
        revision="1",
        unit_ids=("AMR-45",),
        effective_date="2020-01-01",
        expiration_date="2020-12-31",
    )
    assert not evidence_supports_meet(exp).ok

    withdrawn = store.withdraw("ev-1")
    assert withdrawn.withdrawn
    assert "AMR-45" in store.expired_or_withdrawn_unit_ids()


def test_phase2_xlsx_and_export_all(tmp_path):
    run_golden_session(tmp_path / "g", export_dir=None)
    s = DispositionSession(tmp_path / "g")
    s.resume(actor_name="golden-operator", repin=True)
    # F1: Class A at end of golden marks dependents for re-review — clear before export
    for uid in list(s.units_needing_rereview()):
        s.clear_rereview(uid, actor_name="golden-operator")
    recs, _ = load_rdw_default_packs(repin=True)
    records = {r.requirement_id: r for r in recs}
    xlsx = export_xlsx(s, records, tmp_path / "m.xlsx")
    assert xlsx.is_file()
    with zipfile.ZipFile(xlsx, "r") as zf:
        names = zf.namelist()
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/workbook.xml" in names
    paths = export_all(s, records, tmp_path / "all")
    assert paths["csv"].is_file()
    assert paths["docx"].is_file()
    assert paths["xlsx"].is_file()
    # F2: no registry → skip stamp present
    assert "phantom-ref check: skipped" in paths["csv"].read_text(encoding="utf-8")
