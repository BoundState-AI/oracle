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


def _write_pack_json(path: Path) -> None:
    path.write_text(json.dumps(_generic_pack_payload()), encoding="utf-8")


def test_list_and_show_packs(tmp_path, monkeypatch):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)

    source = tmp_path / "incoming.json"
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


def test_import_pack_endpoint(tmp_path, monkeypatch):
    pack_dir = tmp_path / "packs"
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
