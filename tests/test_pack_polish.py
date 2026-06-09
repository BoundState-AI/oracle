"""Tests for pack version archiving on overwrite and explicit render truncation."""
from __future__ import annotations

import json
from pathlib import Path

from oracle.build_far_rulepack import render_tier2_part
from oracle.cli import register_pack


def _generic_pack_payload(statement: str = "The system shall do the thing.") -> dict:
    return {
        "schema_version": "oracle_generic/v1",
        "rule_pack_id": "generic-test-pack",
        "standard_id": "TEST-STD-1",
        "standard_title": "Test Standard",
        "version": "1.0.0",
        "generated_at": "2026-06-09T00:00:00Z",
        "source_document": "test.pdf",
        "extraction_method": "test",
        "extraction_status": "complete",
        "total_source_pages": 1,
        "extracted_pages": [1],
        "failed_page_ranges": [],
        "chunk_failures": [],
        "total_rules": 1,
        "oracle_metadata": {
            "name": "Test Pack",
            "slug": "test_pack",
            "description": "Test pack",
            "status": "draft",
            "added_at": "2026-06-09T00:00:00Z",
        },
        "rules": [
            {"rule_id": "RULE-001", "statement_text": statement, "severity": "high"}
        ],
    }


def test_overwrite_archives_prior_pack_version(tmp_path: Path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()

    src_v1 = tmp_path / "v1.json"
    src_v1.write_text(json.dumps(_generic_pack_payload("Version one rule.")))
    slug = register_pack(src_v1, pack_dir, name="Test Pack")

    src_v2 = tmp_path / "v2.json"
    src_v2.write_text(json.dumps(_generic_pack_payload("Version two rule.")))
    register_pack(src_v2, pack_dir, name="Test Pack", overwrite=True)

    archived = list((pack_dir / "archive").glob(f"{slug}@*.json"))
    assert len(archived) == 1
    prior = json.loads(archived[0].read_text(encoding="utf-8"))
    assert prior["rules"][0]["statement_text"] == "Version one rule."

    current = json.loads((pack_dir / f"{slug}.json").read_text(encoding="utf-8"))
    assert current["rules"][0]["statement_text"] == "Version two rule."


def test_archived_versions_are_invisible_to_pack_globs(tmp_path: Path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(_generic_pack_payload()))
    register_pack(src, pack_dir, name="Test Pack")
    register_pack(src, pack_dir, name="Test Pack", overwrite=True)

    top_level = [p.name for p in pack_dir.glob("*.json")]

    assert all("@" not in name for name in top_level)


def test_long_statement_render_uses_explicit_truncation_marker():
    rulepack = {
        "parts": {
            "15": [
                {
                    "obligation_keyword": "shall",
                    "section": "15.203",
                    "page": 12,
                    "statement_text": "x" * 600,
                }
            ]
        }
    }

    rendered = render_tier2_part(rulepack, 15)

    assert "[TRUNCATED — see full text in the rule pack]" in rendered
    assert "x" * 501 not in rendered


def test_short_statement_render_is_untouched():
    rulepack = {
        "parts": {
            "15": [
                {
                    "obligation_keyword": "shall",
                    "section": "15.203",
                    "page": 12,
                    "statement_text": "Short requirement.",
                }
            ]
        }
    }

    rendered = render_tier2_part(rulepack, 15)

    assert "Short requirement." in rendered
    assert "TRUNCATED" not in rendered
