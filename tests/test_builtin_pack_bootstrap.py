"""Tests for builtin pack bootstrapping — copying bundled packs into the library on first run."""
import json

from oracle import cli


def _builtin_pack_payload(standard_id: str = "BUILTIN-STD-1") -> dict:
    return {
        "schema_version": "oracle_generic/v1",
        "rule_pack_id": standard_id.lower().replace("-", "_"),
        "standard_id": standard_id,
        "standard_title": "Builtin Standard",
        "version": "1.0.0",
        "generated_at": "2026-04-05T00:00:00Z",
        "source_document": "builtin.pdf",
        "extraction_method": "test",
        "extraction_status": "complete",
        "total_source_pages": 1,
        "extracted_pages": [1],
        "failed_page_ranges": [],
        "chunk_failures": [],
        "total_rules": 1,
        "rules": [
            {
                "rule_id": "RULE-001",
                "statement_text": "The system shall do the thing.",
                "severity": "high",
            }
        ],
    }


def test_bootstrap_builtin_packs(tmp_path, monkeypatch):
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir(parents=True, exist_ok=True)
    pack_path = builtin_dir / "builtin_pack.json"
    pack_path.write_text(json.dumps(_builtin_pack_payload()), encoding="utf-8")

    pack_dir = tmp_path / "library"
    pack_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cli, "_builtin_pack_dir", lambda: builtin_dir)
    monkeypatch.setattr(
        cli,
        "BUILTIN_PACK_SPECS",
        (
            {
                "filename": "builtin_pack.json",
                "name": "Builtin Pack",
                "description": "Bundled starter pack",
            },
        ),
    )
    monkeypatch.delenv("ORACLE_DISABLE_BOOTSTRAP_PACKS", raising=False)

    cli._bootstrap_builtin_packs(pack_dir)

    manifest = cli._load_manifest(pack_dir)
    assert "builtin_pack" in manifest["packs"]
    entry = manifest["packs"]["builtin_pack"]
    assert entry["name"] == "Builtin Standard"
    assert entry["description"] == "Bundled starter pack"
    assert (pack_dir / "builtin_pack.json").exists()


def test_bootstrap_adds_missing_builtin_to_existing_manifest(tmp_path, monkeypatch):
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir(parents=True, exist_ok=True)
    first_path = builtin_dir / "first_pack.json"
    second_path = builtin_dir / "second_pack.json"
    first_path.write_text(json.dumps(_builtin_pack_payload("BUILTIN-STD-1")), encoding="utf-8")
    second_path.write_text(json.dumps(_builtin_pack_payload("BUILTIN-STD-2")), encoding="utf-8")

    pack_dir = tmp_path / "library"
    pack_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cli, "_builtin_pack_dir", lambda: builtin_dir)
    monkeypatch.setattr(
        cli,
        "BUILTIN_PACK_SPECS",
        (
            {
                "filename": "first_pack.json",
                "name": "First Pack",
                "description": "Existing bundled pack",
            },
            {
                "filename": "second_pack.json",
                "name": "Second Pack",
                "description": "New bundled pack",
            },
        ),
    )
    monkeypatch.delenv("ORACLE_DISABLE_BOOTSTRAP_PACKS", raising=False)

    cli.register_pack(first_path, pack_dir, name="First Pack", overwrite=True)
    cli._bootstrap_builtin_packs(pack_dir)

    manifest = cli._load_manifest(pack_dir)
    assert "first_pack" in manifest["packs"]
    assert "second_pack" in manifest["packs"]
