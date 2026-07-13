"""Tests for review-time pack integrity checks in load_pack (AUDIT B1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle.cli import _load_manifest, _save_manifest, load_pack, register_pack


def _generic_pack_payload() -> dict:
    return {
        "schema_version": "oracle_generic/v1",
        "rule_pack_id": "generic-test-pack",
        "standard_id": "TEST-STD-1",
        "standard_title": "Test Standard",
        "version": "1.0.0",
        "generated_at": "2026-04-05T00:00:00Z",
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
            "added_at": "2026-04-05T00:00:00Z",
        },
        "rules": [
            {
                "rule_id": "RULE-001",
                "statement_text": "The system shall do the thing.",
                "severity": "high",
            }
        ],
    }


def _register(tmp_path: Path) -> tuple[Path, str]:
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    src = tmp_path / "src_pack.json"
    src.write_text(json.dumps(_generic_pack_payload()), encoding="utf-8")
    slug = register_pack(src, pack_dir, name="Test Pack")
    return pack_dir, slug


def test_load_pack_succeeds_for_untouched_registered_pack(tmp_path):
    pack_dir, slug = _register(tmp_path)

    pack_data, resolved = load_pack(slug, pack_dir)

    assert resolved == slug
    assert pack_data["rule_pack_id"] == "generic-test-pack"


def test_load_pack_rejects_pack_modified_after_registration(tmp_path):
    pack_dir, slug = _register(tmp_path)
    pack_file = pack_dir / f"{slug}.json"
    tampered = json.loads(pack_file.read_text(encoding="utf-8"))
    tampered["rules"][0]["statement_text"] = "The system shall do something ELSE."
    pack_file.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError, match="modified on disk"):
        load_pack(slug, pack_dir)


def test_load_pack_rejects_schema_invalid_pack_when_hash_is_legacy(tmp_path):
    """Legacy manifests (no content_hash) still get schema validation."""
    pack_dir, slug = _register(tmp_path)

    # Simulate a legacy manifest entry with no recorded hash, plus a pack
    # that lost a required field after registration.
    manifest = _load_manifest(pack_dir)
    manifest["packs"][slug]["content_hash"] = ""
    _save_manifest(manifest, pack_dir)

    pack_file = pack_dir / f"{slug}.json"
    broken = json.loads(pack_file.read_text(encoding="utf-8"))
    del broken["rules"]
    pack_file.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="schema validation"):
        load_pack(slug, pack_dir)


def test_load_pack_verify_false_skips_integrity_checks(tmp_path):
    pack_dir, slug = _register(tmp_path)
    pack_file = pack_dir / f"{slug}.json"
    tampered = json.loads(pack_file.read_text(encoding="utf-8"))
    tampered["extra_field"] = "modified"
    pack_file.write_text(json.dumps(tampered), encoding="utf-8")

    pack_data, _ = load_pack(slug, pack_dir, verify=False)

    assert pack_data["extra_field"] == "modified"


# ---------------------------------------------------------------------------
# Manifest schema validation tests (Section 4.4)
# ---------------------------------------------------------------------------

from oracle.pack_validator import validate_manifest, MANIFEST_SCHEMA


def test_validate_manifest_accepts_well_formed_manifest():
    m = {
        "schema_version": "oracle_packs/v1",
        "description": "test",
        "packs": {
            "foo": {
                "name": "Foo",
                "slug": "foo",
                "file": "foo.json",
                "schema": "generic",
                "standard_id": "FOO",
                "rule_count": 3,
                "status": "draft",
            }
        },
    }
    errs = validate_manifest(m)
    assert errs == []


def test_validate_manifest_rejects_bad_schema_version():
    m = {"schema_version": "wrong", "packs": {}}
    errs = validate_manifest(m)
    assert any("oracle_packs/v1" in e for e in errs)


def test_validate_manifest_rejects_missing_required_entry_fields():
    m = {
        "schema_version": "oracle_packs/v1",
        "packs": {
            "bad": {"slug": "bad"}  # missing file, schema, status
        },
    }
    errs = validate_manifest(m)
    assert len(errs) >= 1
    assert any("file" in e or "schema" in e or "status" in e for e in errs)
