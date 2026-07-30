"""Stage 0 — curated 6030 pack integrity. BoundState AI 2026."""

from __future__ import annotations

from pathlib import Path

from oracle.disposition.packs import CURATED_6030, load_rdw_default_packs
from oracle.disposition.rulepack import load_requirement_records


def test_curated_pack_present_and_preferred():
    assert CURATED_6030.is_file(), "curated pack must be promoted under disposition/data"
    recs, hashes = load_rdw_default_packs(repin=True)
    # curated pack id preferred
    assert any("curated" in k or "6030" in k for k in hashes)
    amrs = [r for r in recs if r.requirement_id.startswith("AMR-")]
    assert len(amrs) >= 115


def test_curated_pack_integrity():
    recs, digest = load_requirement_records(CURATED_6030, repin=True)
    assert len(recs) == 115
    dangling = [r.requirement_id for r in recs if r.shall_text.rstrip().endswith("[")]
    assert dangling == []
    amr2 = next(r for r in recs if r.requirement_id == "AMR-2")
    assert "AMCP" in amr2.shall_text
    assert not amr2.shall_text.rstrip().endswith("follo")
    assert "controlling document" in amr2.shall_text or "consolidated AMCP" in amr2.shall_text
    for r in recs:
        assert r.locator.page is not None, r.requirement_id
        assert r.shall_text.strip()
        assert "shall" in r.shall_text.lower()
    # source hash pin on pack file
    import json

    data = json.loads(CURATED_6030.read_text(encoding="utf-8"))
    assert data["source_hash"].startswith("sha256:5246d3b9")
    assert data["total_requirements"] == 115
