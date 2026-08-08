"""Phase 5 — Integrations: local evidence connector, QMS fail-closed. BoundState AI 2026."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle.disposition.integrations import LocalEvidenceConnector, NullQmsConnector


def test_phase5_local_connector_manifest(tmp_path):
    root = tmp_path / "evroot"
    root.mkdir()
    man = root / "manifest.jsonl"
    man.write_text(
        json.dumps(
            {
                "id": "ext-1",
                "doc_id": "AMCP-001",
                "revision": "B",
                "title": "AMCP",
                "path": str(root / "amcp.pdf"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    conn = LocalEvidenceConnector(root)
    refs = conn.list_references("AMCP")
    assert len(refs) == 1
    assert refs[0].doc_id == "AMCP-001"
    assert refs[0].system == "local_filesystem"
    one = conn.fetch_metadata("ext-1")
    assert one is not None and one.revision == "B"


def test_phase5_local_connector_files(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    (root / "QMS_r3.pdf").write_bytes(b"%PDF-fake")
    conn = LocalEvidenceConnector(root)
    refs = conn.list_references()
    assert any(r.doc_id == "QMS" and r.revision == "3" for r in refs)


def test_phase5_qms_fail_closed():
    q = NullQmsConnector(enabled=False)
    h = q.health()
    assert h["writeback"] is False
    assert h["enabled"] is False
    with pytest.raises(RuntimeError, match="disabled"):
        q.list_controlled_docs()
