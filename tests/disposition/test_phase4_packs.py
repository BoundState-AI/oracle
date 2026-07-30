"""Phase 4 — Generalize: draft pack workspace + revision diff. BoundState AI 2026."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle.disposition.packs import DraftPackWorkspace, pack_revision_diff
from oracle.disposition.rulepack import BUILTIN_NASA_6030


def test_phase4_draft_review_promote(tmp_path):
    ws = DraftPackWorkspace(tmp_path / "ws")
    draft = ws.import_source_json(BUILTIN_NASA_6030, name="6030-copy")
    assert draft.is_file()
    recs, _ = ws.load_draft()
    assert len(recs) >= 100
    with pytest.raises(ValueError, match="reviewed"):
        ws.promote_to(tmp_path / "out.json")
    meta = ws.mark_reviewed("curator@boundstate", notes="source reviewed")
    assert meta["status"] == "reviewed"
    dest = ws.promote_to(tmp_path / "promoted" / "pack.json")
    assert dest.is_file()
    # Fresh reviewed draft to test builtin_packs refusal
    ws2 = DraftPackWorkspace(tmp_path / "ws2")
    ws2.import_source_json(BUILTIN_NASA_6030, name="copy2")
    ws2.mark_reviewed("curator@boundstate")
    with pytest.raises(ValueError, match="builtin_packs"):
        ws2.promote_to(Path("oracle/builtin_packs/evil.json"))


def test_phase4_revision_diff(tmp_path):
    # Modify a copy slightly
    raw = json.loads(Path(BUILTIN_NASA_6030).read_text(encoding="utf-8"))
    new_path = tmp_path / "v2.json"
    if raw.get("requirements"):
        raw["requirements"][0]["shall_text"] = raw["requirements"][0]["shall_text"] + " [rev]"
    new_path.write_text(json.dumps(raw), encoding="utf-8")
    diff = pack_revision_diff(BUILTIN_NASA_6030, new_path)
    assert diff["changed_text_or_locator"] or diff["reevaluate"]
    assert diff["old_hash"] != diff["new_hash"]
