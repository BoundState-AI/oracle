"""Tests for the /oracle/chat endpoint — grounded retrieval, multi-pack compare, streaming, and LLM fallback."""
import json
from typing import Any

from fastapi.testclient import TestClient

import server
import oracle.chat_engine as chat_engine
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


def _chat_multi_rule_pack_payload(
    *,
    standard_id: str,
    standard_title: str,
    rules: list[dict[str, Any]],
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
        "total_source_pages": 10,
        "extracted_pages": [4, 5, 6, 10],
        "failed_page_ranges": [],
        "chunk_failures": [],
        "total_rules": len(rules),
        "oracle_metadata": {
            "name": standard_title,
            "slug": standard_id.lower().replace("-", "_"),
            "description": f"{standard_title} pack",
            "status": "draft",
            "added_at": "2026-04-08T00:00:00Z",
        },
        "rules": rules,
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


def test_chat_review_only_mode_allows_packless_critique(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "The contractor shall provide appropriate support as needed.",
            "review_only": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["review_only"] is True
    assert body["selected_packs"] == []
    assert "Review-only assessment" in body["response"]
    assert "measurable" in body["response"].lower()
    assert any(citation.startswith("review-only/") for citation in body["citations"])


def test_chat_explicit_empty_pack_selection_clears_session_scope(workspace_tmp_path, monkeypatch):
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
    first = client.post(
        "/oracle/chat",
        json={
            "session_id": "chat-clear-scope",
            "message": "What does the selected standard say about pure tin finishes?",
            "selected_packs": [slug],
        },
    )
    assert first.status_code == 200
    assert first.json()["status"] == "PASS"

    second = client.post(
        "/oracle/chat",
        json={
            "session_id": "chat-clear-scope",
            "message": "What does the standard say now?",
            "selected_packs": [],
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "INSUFFICIENT_DATA"
    assert body["selected_packs"] == []
    assert "Select at least one authority pack" in body["response"]


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


def test_chat_matches_pure_sn_shorthand_to_pure_tin_rule(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
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
        "3012a_pure_tin.json",
    )

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "I have a part w pure Sn, what should i do",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert "Pure tin finishes shall be prohibited unless mitigation controls are documented." in body["response"]
    assert "MSFC-STD-3012A section 5.4.5 (p. 77)" in body["citations"][0]


def test_chat_synthesizes_pure_tin_workflow_from_multiple_3012a_rules(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_multi_rule_pack_payload(
            standard_id="MSFC-STD-3012A",
            standard_title="EEE Parts Management Requirements",
            rules=[
                {
                    "rule_id": "RULE-001",
                    "section": "Table IV Item 5",
                    "page": 30,
                    "obligation_type": "prohibition",
                    "obligation_keyword": "shall not",
                    "statement_text": "Pure tin plated parts or hardware are prohibited except where specifically approved.",
                    "subject": "Pure tin finish avoidance",
                    "requirement": "Pure tin finish is defined as less than 3% lead by mass and shall not be used as-is where prohibited by the cited hazard-avoidance clause.",
                    "keywords": ["pure tin", "3% lead", "hazard avoidance"],
                    "applies_to": ["eee parts"],
                },
                {
                    "rule_id": "RULE-002",
                    "section": "5.3.2.1",
                    "page": 28,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "shall",
                    "statement_text": "All DPA samples from non QPL/QML/QPD manufactured EEE part lots shall be tested internally and externally for pure tin.",
                    "subject": "Lot pure tin screening",
                    "requirement": "For non QPL/QML/QPD lots, DPA samples shall be tested internally and externally for pure tin.",
                    "keywords": ["pure tin", "DPA", "non QPL/QML/QPD"],
                    "applies_to": ["lot screening"],
                },
                {
                    "rule_id": "RULE-003",
                    "section": "5.4.4.1",
                    "page": 31,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "shall",
                    "statement_text": "Any EEE part where pure tin finish is not precluded by the military QPL/QML/QPD, or specification control document, shall be tested internally and externally for pure tin.",
                    "subject": "Pure tin finish avoidance",
                    "requirement": "If pure tin is not already precluded by the governing spec or control document, the part shall be tested internally and externally for pure tin.",
                    "keywords": ["pure tin", "tested internally and externally", "specification control document"],
                    "applies_to": ["eee parts"],
                },
                {
                    "rule_id": "RULE-004",
                    "section": "5.4.4.1",
                    "page": 31,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "shall",
                    "statement_text": "If parts fail to meet the 3% lead by mass requirement, the preferred method to mitigate pure tin risk is solder dip; if that is not practical, mitigation shall follow IPC J-STD-001ES.",
                    "subject": "Pure tin mitigation",
                    "requirement": "If the finish fails the 3% lead threshold, the preferred pure tin mitigation is solder dip, with IPC J-STD-001ES as the fallback path.",
                    "keywords": ["pure tin", "3% lead", "solder dip", "IPC J-STD-001ES"],
                    "applies_to": ["eee parts"],
                },
            ],
        ),
        "3012a_pure_tin_workflow.json",
    )

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "I have pure Sn, what should i do about it?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert "hazard-avoidance issue" in body["response"]
    assert "test internally and externally for pure tin" in body["response"]
    assert "solder dip" in body["response"]
    assert any("MSFC-STD-3012A section 5.4.4.1" in citation for citation in body["citations"])
    assert body["follow_ups"] == [
        "Show me the pure tin avoidance clause in MSFC-STD-3012A.",
        "List the test and mitigation steps for pure tin under MSFC-STD-3012A.",
    ]


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
    assert body["response"].startswith("Comparison across selected standards.")
    assert "NASA-STD-5009C:" in body["response"]
    assert "MSFC-STD-3012A:" in body["response"]
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
    assert '"review_only": false' in payload
    assert '"envelope_version": "1.0"' in payload


def test_chat_stream_review_only_returns_done_payload(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    client = TestClient(server.app)
    with client.stream(
        "POST",
        "/oracle/chat/stream",
        json={
            "message": "The team will obtain approval before release.",
            "review_only": True,
        },
    ) as response:
        payload = b"".join(response.iter_bytes()).decode("utf-8")

    assert response.status_code == 200
    assert "event: meta" in payload
    assert "event: done" in payload
    assert '"review_only": true' in payload
    assert "review-only/governance" in payload


def test_chat_synthesizes_scope_and_funding_answer(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_multi_rule_pack_payload(
            standard_id="ESSCA-II-J-21",
            standard_title="ESSCA II Attachment J-21",
            rules=[
                {
                    "rule_id": "RULE-001",
                    "section": "Fig J-21-1",
                    "page": 10,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "must",
                    "statement_text": "Scope or POP change with cost impact triggers the standard TOCR flow.",
                    "subject": "Scope change routing",
                    "requirement": "Any change involving scope with cost impact must follow the TOCR flow, not an informal path.",
                    "keywords": ["scope change", "cost impact", "TOCR flow"],
                    "applies_to": ["scope_changes"],
                },
                {
                    "rule_id": "RULE-002",
                    "section": "1.1-SubTask(c)",
                    "page": 5,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "required",
                    "statement_text": "CWBS, to include PSID, funding source, funding sub-source, and activity.",
                    "subject": "Sub-task CWBS and funding",
                    "requirement": "Each sub-task must have CWBS data with PSID and funding source information before the work can be authorized.",
                    "keywords": ["CWBS", "PSID", "funding source", "charge code"],
                    "applies_to": ["all_sub_tasks"],
                },
                {
                    "rule_id": "RULE-003",
                    "section": "1.1(k)",
                    "page": 4,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "must",
                    "statement_text": "Summary of changes must include the description of change and cost impact.",
                    "subject": "Summary of Changes",
                    "requirement": "Every TOCR summary must include the change description and cost impact.",
                    "keywords": ["summary of changes", "cost impact", "TOCR"],
                    "applies_to": ["all_task_order_changes"],
                },
                {
                    "rule_id": "RULE-004",
                    "section": "1.1-SubTask(g)",
                    "page": 5,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "required",
                    "statement_text": "Place of performance for the work if not onsite.",
                    "subject": "Place of performance",
                    "requirement": "Non-onsite work must specify place of performance.",
                    "keywords": ["place of performance"],
                    "applies_to": ["all_sub_tasks"],
                },
            ],
        ),
        "j21.json",
    )

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "if you insert scope and do not fund it, is that against the j21 rules?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["response"].startswith("ESSCA-II-J-21 routes this kind of scope-and-funding change into formal change control.")
    assert "TOCR" in body["response"]
    assert "funding" in body["response"].lower()
    assert "place of performance" not in body["response"].lower()
    assert len(body["citations"]) == 3


def test_chat_uses_llm_summary_when_available(workspace_tmp_path, monkeypatch):
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

    monkeypatch.setattr(
        chat_engine,
        "_maybe_run_llm_reasoning",
        lambda **kwargs: {
            "provider": "test",
            "model": "reasoner",
            "direct_answer": "No.",
            "bottom_line": "The retrieved rule prohibits pure tin on mission hardware connectors.",
            "why": ["The retrieved clause is a direct prohibition."],
            "gaps": [],
            "governing_citations": ["NASA-STD-5009C section Table V Note 6 (p. 42)"],
            "follow_ups": ["Show me the exact clause text."],
            "per_pack_findings": [],
        },
    )
    monkeypatch.setattr(
        chat_engine,
        "_maybe_run_llm_summary",
        lambda **kwargs: {
            "provider": "test",
            "model": "summarizer",
            "answer_text": "No. NASA-STD-5009C directly prohibits pure tin finishes on mission hardware connectors.",
            "citations": ["NASA-STD-5009C section Table V Note 6 (p. 42)"],
            "follow_ups": ["Show me the exact clause text."],
        },
    )

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "Is pure tin allowed on mission hardware connectors?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["response"].startswith("No.")
    assert body["citations"] == ["NASA-STD-5009C section Table V Note 6 (p. 42)"]
    assert body["stage_artifacts"]["summary"]["llm_model"] == "summarizer"


def test_chat_returns_insufficient_data_for_weak_single_token_overlap(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_multi_rule_pack_payload(
            standard_id="NASA-STD-5009C",
            standard_title="NASA Fracture Control Standard",
            rules=[
                {
                    "rule_id": "RULE-001",
                    "section": "4.1.4.2.2",
                    "page": 19,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "shall",
                    "statement_text": "The final penetrant inspection can be performed prior to metal finishing operations such as buffing or sanding.",
                    "subject": "Final penetrant inspection timing",
                    "requirement": "The final penetrant inspection may occur before certain metal finishing operations.",
                    "keywords": ["penetrant inspection", "metal finishing operations"],
                    "applies_to": ["nde_process"],
                },
                {
                    "rule_id": "RULE-002",
                    "section": "4.1.5.5",
                    "page": 24,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "shall",
                    "statement_text": "The process shall be subject to review and approval of the RFCB.",
                    "subject": "Standard NDE review",
                    "requirement": "The process requires RFCB review and approval.",
                    "keywords": ["review", "approval", "NDE"],
                    "applies_to": ["nde_process"],
                },
            ],
        ),
        "5009c_nde.json",
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
    assert body["status"] == "INSUFFICIENT_DATA"
    assert "did not find a grounded requirement match" in body["response"]
    assert body["citations"] == ["NASA-STD-5009C"]


def test_chat_stream_insufficient_data_payload_is_json_serializable(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_multi_rule_pack_payload(
            standard_id="NASA-STD-5009C",
            standard_title="NASA Fracture Control Standard",
            rules=[
                {
                    "rule_id": "RULE-001",
                    "section": "4.1.4.2.2",
                    "page": 19,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "shall",
                    "statement_text": "The final penetrant inspection can be performed prior to metal finishing operations such as buffing or sanding.",
                    "subject": "Final penetrant inspection timing",
                    "requirement": "The final penetrant inspection may occur before certain metal finishing operations.",
                    "keywords": ["penetrant inspection", "metal finishing operations"],
                    "applies_to": ["nde_process"],
                }
            ],
        ),
        "5009c_stream.json",
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
    assert "event: error" not in payload
    assert "event: done" in payload

    done_payload = payload.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0]
    body = json.loads(done_payload)
    assert body["status"] == "INSUFFICIENT_DATA"
    assert body["stage_artifacts"]["retrieval"]["pack"]["standard_id"] == "NASA-STD-5009C"
    assert body["stage_artifacts"]["retrieval"]["pack"]["rule_count"] == 1


def test_chat_falls_back_when_summary_validation_fails(workspace_tmp_path, monkeypatch):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "_pack_dir", lambda: pack_dir)
    server._chat_sessions.clear()

    slug = _register_pack(
        workspace_tmp_path,
        pack_dir,
        _chat_multi_rule_pack_payload(
            standard_id="ESSCA-II-J-21",
            standard_title="ESSCA II Attachment J-21",
            rules=[
                {
                    "rule_id": "RULE-001",
                    "section": "Fig J-21-1",
                    "page": 10,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "must",
                    "statement_text": "Scope or POP change with cost impact triggers the standard TOCR flow.",
                    "subject": "Scope change routing",
                    "requirement": "Any change involving scope with cost impact must follow the TOCR flow, not an informal path.",
                    "keywords": ["scope change", "cost impact", "TOCR flow"],
                    "applies_to": ["scope_changes"],
                },
                {
                    "rule_id": "RULE-002",
                    "section": "1.1-SubTask(c)",
                    "page": 5,
                    "obligation_type": "mandatory",
                    "obligation_keyword": "required",
                    "statement_text": "CWBS, to include PSID, funding source, funding sub-source, and activity.",
                    "subject": "Sub-task CWBS and funding",
                    "requirement": "Each sub-task must have CWBS data with PSID and funding source information before the work can be authorized.",
                    "keywords": ["CWBS", "PSID", "funding source", "charge code"],
                    "applies_to": ["all_sub_tasks"],
                },
            ],
        ),
        "j21.json",
    )

    monkeypatch.setattr(
        chat_engine,
        "_maybe_run_llm_reasoning",
        lambda **kwargs: {
            "provider": "test",
            "model": "reasoner",
            "direct_answer": "Likely yes.",
            "bottom_line": "The retrieved rules point the change into TOCR handling.",
            "why": ["The retrieved clauses require TOCR routing and funding data."],
            "gaps": [],
            "governing_citations": [
                "ESSCA-II-J-21 section Fig J-21-1 (p. 10)",
                "ESSCA-II-J-21 section 1.1-SubTask(c) (p. 5)",
            ],
            "follow_ups": ["Show me the exact clause text."],
            "per_pack_findings": [],
        },
    )
    monkeypatch.setattr(
        chat_engine,
        "_maybe_run_llm_summary",
        lambda **kwargs: {
            "provider": "test",
            "model": "summarizer",
            "answer_text": "Approved. This change is fine.",
            "citations": ["ESSCA-II-J-21 section Fig J-21-1 (p. 10)"],
            "follow_ups": ["Close this item."],
        },
    )

    client = TestClient(server.app)
    response = client.post(
        "/oracle/chat",
        json={
            "message": "if you insert scope and do not fund it, is that against the j21 rules?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["response"].startswith("Likely yes.")
    assert body["diagnostics"]["fallback_used"] is True
    assert body["diagnostics"]["fallback_reason"] == "stage_4_validation_failure"
    assert "stage_4_prohibited_decision_language" in body["diagnostics"]["validation_failures"]
    assert body["stage_artifacts"]["reasoning"]["llm_model"] == "reasoner"
    assert "summary" not in body["stage_artifacts"]
