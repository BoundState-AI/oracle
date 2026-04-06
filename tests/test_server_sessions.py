import json
from pathlib import Path

from fastapi.testclient import TestClient

import server


def _write_session_manifest(base: Path, session_id: str, payload: dict) -> None:
    session_dir = base / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / server.SESSION_STATE_FILE).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_session_status_marks_interrupted_processing_session(tmp_path, monkeypatch):
    session_id = "deadbeef1234"
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path)
    server._sessions.pop(session_id, None)

    _write_session_manifest(
        tmp_path,
        session_id,
        {
            "session_id": session_id,
            "mode": "review",
            "status": "processing",
            "error": None,
            "original_name": "draft.docx",
            "file_path": str(tmp_path / session_id / "draft.docx"),
            "output_dir": str(tmp_path / session_id / "oracle_output"),
        },
    )

    client = TestClient(server.app)
    response = client.get(f"/oracle/session/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "interrupted" in data["error"].lower()


def test_session_status_rehydrates_completed_session(tmp_path, monkeypatch):
    session_id = "feedface5678"
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path)
    server._sessions.pop(session_id, None)

    output_dir = tmp_path / session_id / "oracle_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "session_summary.json").write_text(
        json.dumps({"session_id": session_id, "total_rounds": 0, "converged": False}),
        encoding="utf-8",
    )
    (output_dir / "final_draft.md").write_text("Final draft", encoding="utf-8")

    _write_session_manifest(
        tmp_path,
        session_id,
        {
            "session_id": session_id,
            "mode": "review",
            "status": "ready_to_generate",
            "error": None,
            "critique": "Issues found",
            "original_name": "draft.docx",
            "file_path": str(tmp_path / session_id / "draft.docx"),
            "output_dir": str(output_dir),
        },
    )

    client = TestClient(server.app)
    response = client.get(f"/oracle/session/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready_to_generate"
    assert data["docx_url"] == f"/oracle/download/{session_id}/docx"
    assert data["pptx_url"] == f"/oracle/download/{session_id}/pptx"


def test_session_status_returns_persisted_log_messages(tmp_path, monkeypatch):
    session_id = "cafefeed9012"
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path)
    server._sessions.pop(session_id, None)

    _write_session_manifest(
        tmp_path,
        session_id,
        {
            "session_id": session_id,
            "job_type": "pack_generate",
            "status": "processing",
            "error": None,
            "original_name": "source.pdf",
            "file_path": str(tmp_path / session_id / "source.pdf"),
            "output_dir": str(tmp_path / session_id / "oracle_output"),
            "log_messages": [
                "Page 48/55 (p.66): 3/3 enriched (16.5s, ETA ~115s)",
                "Anthropic responded",
            ],
        },
    )

    client = TestClient(server.app)
    response = client.get(f"/oracle/session/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert data["log_messages"] == [
        "Page 48/55 (p.66): 3/3 enriched (16.5s, ETA ~115s)",
        "Anthropic responded",
    ]
