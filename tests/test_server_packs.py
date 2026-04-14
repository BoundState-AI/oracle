"""Tests for server pack endpoints — list, show, import, and GPCM ID normalization on register."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

import server
from oracle.cli import register_pack


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


def _gpcm_pack_payload() -> dict:
    return {
        "schema_version": "gpcm_rulepack/v1",
        "rule_pack_id": "gpcm-test-pack",
        "standard_id": "NASA-STD-TEST",
        "version": "1.0.0",
        "generated_at": "2026-04-05T00:00:00Z",
        "source_document": "test.pdf",
        "source_extract": "test_shall.json",
        "extraction_status": "complete",
        "total_requirements": 1,
        "oracle_metadata": {
            "name": "GPCM Test Pack",
            "slug": "gpcm_test_pack",
            "description": "Test GPCM pack",
            "status": "draft",
            "added_at": "2026-04-05T00:00:00Z",
        },
        "requirements": [
            {
                "id": 1,
                "shall_text": "The system shall do the thing.",
                "page": "9, 11",
            }
        ],
    }


def _write_pack_json(path: Path) -> None:
    path.write_text(json.dumps(_generic_pack_payload()), encoding="utf-8")


def test_list_and_show_packs(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)

    source = workspace_tmp_path / "incoming.json"
    _write_pack_json(source)
    slug = register_pack(source, pack_dir)

    client = TestClient(server.app)

    listing = client.get("/oracle/packs")
    assert listing.status_code == 200
    packs = listing.json()["packs"]
    assert packs[0]["slug"] == slug
    assert packs[0]["rule_count"] == 1

    detail = client.get(f"/oracle/packs/{slug}?verbose=true")
    assert detail.status_code == 200
    body = detail.json()
    assert body["slug"] == slug
    assert body["schema"] == "generic"
    assert "Pack ID:" in body["rendered"]


def test_import_pack_endpoint(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)

    payload = json.dumps(_generic_pack_payload()).encode("utf-8")
    client = TestClient(server.app)

    response = client.post(
        "/oracle/packs/import",
        files={"file": ("test-pack.json", payload, "application/json")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["pack"]["slug"] == "test_std_1"


def test_register_pack_persists_normalized_gpcm_ids(workspace_tmp_path):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)

    source = workspace_tmp_path / "gpcm.json"
    source.write_text(json.dumps(_gpcm_pack_payload()), encoding="utf-8")

    slug = register_pack(source, pack_dir)
    stored = json.loads((pack_dir / f"{slug}.json").read_text(encoding="utf-8"))

    requirement = stored["requirements"][0]
    assert requirement["id"] == "1"
    assert requirement["page"] == 9
