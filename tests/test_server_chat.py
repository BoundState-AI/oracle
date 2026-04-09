import json

from fastapi.testclient import TestClient

import server
from oracle.cli import register_pack


def _chat_pack_payload(
    *,
    standard_id: str,
    standard_title: str,
    statement_text: str,
    section: str,
    page: int,
    keywords: list[str],
) -> dict:
    return {
        "schema_version": "oracle_generic/v1",
        "rule_pack_id": f"{standard_id.lower()}-pack",
        "standard_id": standard_id,
        "standard_title": standard_title,
        "version": "1.0.0",
        "generated_at": "2026-04-08T00:00:00Z",
        "source_document": f"{standard_id}.pdf",
        "extraction_method": "test",
        "extraction_status": "complete",
        "total_source_pages": page,
        "extracted_pages": [page],
        "failed_page_ranges": [],
        "chunk_failures": [],
        "total_rules": 1,
        "oracle_metadata": {
            "name": standard_title,
            "slug": standard_id.lower().replace("-", "_"),
            "description": f"{standard_title} pack",
            "status": "draft",
            "added_at": "2026-04-08T00:00:00Z",
        },
        "rules": [
            {
                "rule_id": "RULE-001",
                "section": section,
                "page": page,
                "obligation_type": "mandatory",
                "obligation_keyword": "shall",
                "statement_text": statement_text,
                "subject": "Connector plating",
                "requirement": statement_text,
                "keywords": keywords,
            }
        ],
    }


def _register_pack(workspace_tmp_path, pack_dir, payload: dict, filename: str) -> str:
    source = workspace_tmp_path / filename
    source.write_text(json.dumps(payload), encoding="utf-8")
    return register_pack(source, pack_dir)


def test_chat_requires_selected_pack(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    client = TestClient(server.app)
    response = client.post("/oracle/chat", json={"message": "What does the standard say?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INSUFFICIENT_DATA"
    assert "Select at least one authority pack" in body["response"]
    assert body["advisory_only"] is True


def test_chat_returns_grounded_clause_for_selected_pack(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_pack_payload(
            standard_id="NASA-STD-5009C",
            standard_title="NASA Fracture Control Standard",
            statement_text="Pure tin finishes shall not be used on mission hardware connectors.",
            section="Table V Note 6",
            page=42,
            keywords=["pure tin", "connector plating"],
        ),
        "5009c.json",
    )

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "What does the selected standard say about pure tin finishes?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert "Pure tin finishes shall not be used" in body["response"]
    assert "NASA-STD-5009C" in body["citations"][0]
    assert body["selected_packs"] == [slug]


def test_chat_compare_only_uses_multiple_packs(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    first_slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_pack_payload(
            standard_id="NASA-STD-5009C",
            standard_title="NASA Fracture Control Standard",
            statement_text="Pure tin finishes shall not be used on mission hardware connectors.",
            section="Table V Note 6",
            page=42,
            keywords=["pure tin", "connector plating"],
        ),
        "5009c.json",
    )
    second_slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_pack_payload(
            standard_id="MSFC-STD-3012A",
            standard_title="EEE Parts Management Requirements",
            statement_text="Pure tin finishes shall be prohibited unless mitigation controls are documented.",
            section="5.4.5",
            page=77,
            keywords=["pure tin", "mitigation controls"],
        ),
        "3012a.json",
    )

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "Compare the selected standards on pure tin finishes.",
            "selected_packs": [first_slug, second_slug],
            "compare_only": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["compare_only"] is True
    assert "Oracle comparison across selected standards" in body["response"]
    assert len(body["selected_packs"]) == 2
    assert any("NASA-STD-5009C" in citation for citation in body["citations"])
    assert any("MSFC-STD-3012A" in citation for citation in body["citations"])


def test_chat_stream_returns_done_payload(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_pack_payload(
            standard_id="NASA-STD-5009C",
            standard_title="NASA Fracture Control Standard",
            statement_text="Pure tin finishes shall not be used on mission hardware connectors.",
            section="Table V Note 6",
            page=42,
            keywords=["pure tin", "connector plating"],
        ),
        "5009c.json",
    )

    client = TestClient(server.app)
    with client.stream(
        "POST",
        "/oracle/chat/stream",
        json={
            "message": "What does the selected standard say about pure tin finishes?",
            "selected_packs": [slug],
        },
    ) as response:
        payload = b"".join(response.iter_bytes()).decode("utf-8")

    assert response.status_code == 200
    assert "event: meta" in payload
    assert "event: text" in payload
    assert "event: done" in payload
    assert '"advisory_only": true' in payload
