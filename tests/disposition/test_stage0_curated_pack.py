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


def test_curated_pack_hyphen_and_rationale_fidelity():
    """AF1: no soft-hyphen join artifacts; rationale not embedded in shall_text."""
    import json
    import re

    data = json.loads(CURATED_6030.read_text(encoding="utf-8"))
    join_artifacts = (
        "NASASTD",
        "NASA-STD5009",
        "insitu",
        "postbuild",
        "postAM",
        "LotMature",
        "growthrate",
    )
    for r in data["requirements"]:
        text = r["shall_text"]
        for art in join_artifacts:
            assert art not in text, f"{r['id']} has join artifact {art!r}"
        assert "[Rationale" not in text, f"{r['id']} embeds rationale in shall_text"
        assert not re.search(r"(?i)\brationale\s*:", text), (
            f"{r['id']} embeds rationale prose in shall_text"
        )
    by_id = {r["id"]: r for r in data["requirements"]}
    assert "NASA-STD-5019" in by_id["amr-15"]["shall_text"]
    assert "NASA-STD-5009" in by_id["amr-20"]["shall_text"]
    assert "in-situ" in by_id["amr-21"]["shall_text"]
