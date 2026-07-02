"""Golden tests for Oracle chat yes/no question polarity and retrieval filters.

Covers:
- Yes/No answers must match the polarity of the QUESTION ("Is X prohibited?"
  vs "Is X allowed?"), not merely restate the matched rule's stance.
- Open questions containing compliance vocabulary must not get a yes/no shape.
- Ambiguous material tokens ("lead") must not hard-filter retrieval outside a
  materials context, and explicit section references bypass the filter.
"""
from fastapi.testclient import TestClient

import server
from tests.test_server_chat import (
    _chat_multi_rule_pack_payload,
    _chat_pack_payload,
    _register_pack,
)


def _client_with_pack(workspace_tmp_path, monkeypatch, payload: dict, filename: str):
    pack_dir = workspace_tmp_path / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    # WHY the env seam: server._pack_dir -> oracle.cli._resolve_pack_dir reads
    # ORACLE_PACK_DIR at call time, so pointing the env var at the fixture dir
    # exercises the real resolution path instead of stubbing the function.
    monkeypatch.setenv("ORACLE_PACK_DIR", str(pack_dir))
    monkeypatch.setenv("ORACLE_SECONDARY_RATIONALE_JSON", "")
    server._chat_sessions.clear()
    slug = _register_pack(workspace_tmp_path, pack_dir, payload, filename)
    return TestClient(server.app), slug


def _pure_tin_prohibition_payload() -> dict:
    return _chat_pack_payload(
        standard_id="NASA-STD-5009C",
        standard_title="NASA Fracture Control Standard",
        statement_text="Pure tin finishes shall not be used on mission hardware connectors.",
        section="Table V Note 6",
        page=42,
        keywords=["pure tin", "connector plating"],
    )


def test_asking_if_prohibited_against_prohibition_rule_answers_yes(workspace_tmp_path, monkeypatch):
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _pure_tin_prohibition_payload(), "polarity_yes.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "Is pure tin prohibited on mission hardware connectors?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["response"].startswith("Yes.")
    assert "Pure tin finishes shall not be used" in body["response"]


def test_asking_if_allowed_against_prohibition_rule_answers_no(workspace_tmp_path, monkeypatch):
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _pure_tin_prohibition_payload(), "polarity_no.json"
    )

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
    assert "Pure tin finishes shall not be used" in body["response"]


def test_why_query_asking_if_prohibited_leads_with_yes(workspace_tmp_path, monkeypatch):
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _pure_tin_prohibition_payload(), "polarity_why.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "Why is pure tin prohibited on mission hardware connectors?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    # "Why is X prohibited?" implies the binary question "is X prohibited",
    # which a prohibition rule answers affirmatively.
    assert body["response"].startswith("Yes.")


def test_polarity_term_in_conditional_clause_gets_non_binary_lead(
    workspace_tmp_path, monkeypatch
):
    """WHY: "prohibited" here sits in a conditional premise ("... if lead is
    prohibited in my contract"), not the question. Bag-of-words polarity used
    to flip the question to prohibited-polarity and answer "Yes." against a
    prohibition rule — an inverted compliance answer."""
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _pure_tin_prohibition_payload(), "polarity_conditional.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "Can I use pure tin if lead is prohibited in my contract?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert not body["response"].startswith("Yes")
    assert not body["response"].startswith("No.")


def test_negated_prohibition_question_gets_correct_polarity(workspace_tmp_path, monkeypatch):
    """"Is X not prohibited?" asks about permission; against a prohibition
    rule the correct binary answer is "No." (it IS prohibited)."""
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _pure_tin_prohibition_payload(), "polarity_negated.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "Is pure tin not prohibited on mission hardware connectors?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["response"].startswith("No.")


def test_both_polarity_vocabularies_get_non_binary_lead(workspace_tmp_path, monkeypatch):
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _pure_tin_prohibition_payload(), "polarity_both.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "Is pure tin allowed or prohibited on mission hardware connectors?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    # Both vocabularies appear, so the polarity is ambiguous — never guess.
    assert not body["response"].startswith("Yes")
    assert not body["response"].startswith("No.")


def test_open_question_with_compliance_vocabulary_is_not_yes_no_shaped(
    workspace_tmp_path, monkeypatch
):
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _pure_tin_prohibition_payload(), "polarity_open.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "What requirements apply to pure tin finishes on connectors?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert not body["response"].startswith("Yes")
    assert not body["response"].startswith("No.")


def _lead_time_pack_payload() -> dict:
    return _chat_multi_rule_pack_payload(
        standard_id="ESSCA-II-J-21",
        standard_title="ESSCA II Attachment J-21",
        rules=[
            {
                "rule_id": "RULE-001",
                "section": "5.1",
                "page": 12,
                "obligation_type": "mandatory",
                "obligation_keyword": "shall",
                "statement_text": "Deliverable lead time shall not exceed 30 days from task order award.",
                "subject": "Deliverable lead time",
                "requirement": "Deliverable lead time shall not exceed 30 days from task order award.",
                "keywords": ["lead time", "deliverables"],
                "applies_to": ["deliverables"],
            },
            {
                "rule_id": "RULE-002",
                "section": "7.2",
                "page": 30,
                "obligation_type": "mandatory",
                "obligation_keyword": "shall",
                "statement_text": "Tin and lead alloy plating shall contain at least 3% lead by mass.",
                "subject": "Plating lead content",
                "requirement": "Tin and lead alloy plating shall contain at least 3% lead by mass.",
                "keywords": ["lead", "tin plating"],
                "applies_to": ["plating"],
            },
        ],
    )


def test_lead_time_query_with_section_reference_retrieves_section_rule(
    workspace_tmp_path, monkeypatch
):
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _lead_time_pack_payload(), "lead_time_section.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "What is the lead time in section 5.1 for deliverables?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert "Deliverable lead time shall not exceed 30 days" in body["response"]
    assert "section 5.1" in body["citations"][0]


def test_lead_time_query_without_materials_context_is_not_material_filtered(
    workspace_tmp_path, monkeypatch
):
    client, slug = _client_with_pack(
        workspace_tmp_path, monkeypatch, _lead_time_pack_payload(), "lead_time_plain.json"
    )

    response = client.post(
        "/oracle/chat",
        json={
            "message": "How long is the lead time for deliverables?",
            "selected_packs": [slug],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    # "lead" here is schedule vocabulary, not the metal — the deliverable rule
    # must win instead of being discarded by the material hard-filter.
    assert "Deliverable lead time shall not exceed 30 days" in body["response"]
    assert "section 5.1" in body["citations"][0]
