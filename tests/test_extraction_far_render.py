"""render_unassigned visibility contract (FAR rule pack).

Unassigned requirements are binding text that could not be mapped to a FAR
Part; they must render with the same [pack_id:rule_id] citation convention
the cli renderers use, so oracle2_adapter can extract citations to them.
The pack_id parameter is optional: existing callers (render_for_oracle)
render without citations and their output must stay byte-identical.
"""

from __future__ import annotations

from oracle.build_far_rulepack import render_for_oracle, render_unassigned


def _rulepack(unassigned: list[dict]) -> dict:
    return {
        "total_binding_requirements": len(unassigned),
        "parts_count": 0,
        "total_unassigned": len(unassigned),
        "part_index": [],
        "parts": {},
        "unassigned": unassigned,
    }


def _req(req_id: int | str = 42) -> dict:
    return {
        "id": req_id,
        "section": "",
        "page": 3,
        "obligation_type": "mandatory",
        "obligation_keyword": "shall",
        "statement_text": "The contractor shall maintain records.",
    }


def test_render_unassigned_empty_returns_empty_string():
    assert render_unassigned(_rulepack([])) == ""


def test_render_unassigned_without_pack_id_keeps_legacy_format():
    block = render_unassigned(_rulepack([_req()]))
    assert "UNASSIGNED BINDING REQUIREMENTS" in block
    assert "[SHALL] §?? p.3: The contractor shall maintain records." in block
    # No citation token without a pack_id — backward compatibility.
    assert "42]" not in block


def test_render_unassigned_with_pack_id_prefixes_citation_token():
    block = render_unassigned(_rulepack([_req()]), pack_id="far-pack")
    assert "[far-pack:42] [SHALL] §?? p.3: The contractor shall maintain records." in block


def test_render_unassigned_missing_id_uses_placeholder():
    req = _req()
    del req["id"]
    block = render_unassigned(_rulepack([req]), pack_id="far-pack")
    assert "[far-pack:?] [SHALL]" in block


def test_render_for_oracle_still_includes_unassigned_block():
    context = render_for_oracle(_rulepack([_req()]))
    assert "UNASSIGNED BINDING REQUIREMENTS" in context
    assert "The contractor shall maintain records." in context
