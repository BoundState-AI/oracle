"""Tests for the Oracle chat grader gate, fallback re-grading, JSON parsing,
and the broadened approval-refusal pattern.

Style note: these tests inject crafted envelopes/rules through public entry
points (grade_chat_response, _emit_envelope, answer_query) rather than
monkeypatching engine internals.
"""
from pathlib import Path

import pytest

from oracle.chat_contract import OracleChatEnvelope, OracleEvidenceItem
from oracle.chat_engine import (
    ChatRule,
    _citation,
    _emit_envelope,
    _parse_model_json,
    _validate_llm_reasoning_output,
    answer_query,
    read_env_int,
)
from oracle.chat_grader import grade_chat_response, strip_verbatim_spans

RFCB_STATEMENT = "The process shall be subject to review and approval of the RFCB."
RFCB_SUMMARY = "The process requires RFCB review and approval."


def _rfcb_envelope(**overrides) -> OracleChatEnvelope:
    fields = {
        "status": "PASS",
        "query": "What does the standard say about NDE process review?",
        "intent": "lookup",
        "selected_packs": ["nasa_std_5009c"],
        "authority_basis": ["NASA-STD-5009C"],
        "citations": ["NASA-STD-5009C section 4.1.5.5 (p. 24)"],
        "evidence": [
            OracleEvidenceItem(
                citation="NASA-STD-5009C section 4.1.5.5 (p. 24)",
                summary=RFCB_SUMMARY,
                statement_text=RFCB_STATEMENT,
                standard_id="NASA-STD-5009C",
            )
        ],
    }
    fields.update(overrides)
    return OracleChatEnvelope(**fields)


def test_grader_passes_verbatim_rule_quote_containing_approval():
    envelope = _rfcb_envelope()
    text = f"NASA-STD-5009C says: {RFCB_STATEMENT}"
    grade = grade_chat_response(text, envelope)
    assert grade.passed
    assert grade.failures == []


def test_grader_passes_quote_with_lowercased_leading_letter():
    envelope = _rfcb_envelope()
    text = "In the selected clauses, the process shall be subject to review and approval of the RFCB."
    grade = grade_chat_response(text, envelope)
    assert grade.passed


def test_grader_blocks_asserted_decision_language():
    envelope = _rfcb_envelope()
    grade = grade_chat_response("This is approved, proceed with the change.", envelope)
    assert not grade.passed
    assert "prohibited_decision_language" in grade.failures


def test_grader_blocks_asserted_decision_language_even_next_to_a_quote():
    envelope = _rfcb_envelope()
    text = f"{RFCB_STATEMENT} This is approved, proceed."
    grade = grade_chat_response(text, envelope)
    assert not grade.passed
    assert "prohibited_decision_language" in grade.failures


def test_strip_verbatim_spans_ignores_short_fragments():
    # A trivial evidence fragment must not blanket-exempt decision language.
    assert strip_verbatim_spans("Approved.", ["Approved"]) == "Approved."


def test_envelope_status_fails_closed_on_typo():
    with pytest.raises(ValueError, match="Invalid Oracle chat envelope status"):
        _rfcb_envelope(status="REFUSED")


def test_emit_envelope_regrades_fallback_and_terminates_citations_only():
    # Draft answer asserts decision language, and the reformatted fallback
    # would too (via a non-evidence assumption line) — the terminal response
    # must be citations-only with no free prose.
    envelope = _rfcb_envelope(
        draft_answer_text="You can waive this requirement and proceed.",
        assumptions=["The waiver was already approved by the program office."],
    )
    result = _emit_envelope(envelope)

    assert result["status"] == "PASS"
    assert result["response"].startswith("Oracle could not produce a compliant prose answer")
    assert "NASA-STD-5009C section 4.1.5.5 (p. 24)" in result["response"]
    assert "waive" not in result["response"].lower()
    assert "approved" not in result["response"].lower()
    assert result["diagnostics"]["fallback_used"] is True
    assert result["diagnostics"]["fallback_reason"] == "grader_terminal_citations_only"
    assert "prohibited_decision_language" in result["diagnostics"]["validation_failures"]
    assert "fallback_prohibited_decision_language" in result["diagnostics"]["validation_failures"]


def test_emit_envelope_fallback_that_passes_regrade_is_used():
    # Draft fails, but the evidence-only fallback is clean — it ships as-is.
    envelope = _rfcb_envelope(draft_answer_text="Consider this certified and closed.")
    result = _emit_envelope(envelope)

    assert result["diagnostics"]["fallback_used"] is True
    assert result["diagnostics"]["fallback_reason"] == "formatter_grader_failure"
    assert RFCB_SUMMARY in result["response"]
    assert "certified" not in result["response"]


def test_parse_model_json_accepts_plain_and_fenced_objects():
    assert _parse_model_json('{"a": 1}') == {"a": 1}
    assert _parse_model_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_model_json('```\n{"a": 1}\n```') == {"a": 1}


def test_parse_model_json_rejects_non_object_json():
    with pytest.raises(ValueError, match="non-object JSON"):
        _parse_model_json("[1, 2, 3]")
    with pytest.raises(ValueError, match="non-object JSON"):
        _parse_model_json('```json\n"just a string"\n```')


def _rfcb_rule() -> ChatRule:
    return ChatRule(
        pack_slug="nasa_std_5009c",
        standard_id="NASA-STD-5009C",
        standard_title="NASA Fracture Control Standard",
        rule_id="RULE-001",
        section="4.1.5.5",
        page=24,
        obligation_type="mandatory",
        obligation_keyword="shall",
        statement_text=RFCB_STATEMENT,
        subject="Standard NDE review",
        requirement=RFCB_SUMMARY,
        justification="",
        keywords=("review", "approval", "NDE"),
        applies_to=("nde_process",),
    )


def _reasoning_payload(rule: ChatRule, **overrides) -> dict:
    payload = {
        "direct_answer": "The process requires RFCB review.",
        "bottom_line": "The retrieved clause routes the process through the RFCB.",
        "why": [],
        "gaps": [],
        "governing_citations": [_citation(rule)],
        "follow_ups": [],
        "per_pack_findings": [],
    }
    payload.update(overrides)
    return payload


def test_stage3_screen_blocks_asserted_decision_language():
    rule = _rfcb_rule()
    retrieval = {"compare_mode": False, "matches": [(rule, 9)]}
    reasoning = _reasoning_payload(rule, bottom_line="This part is approved for flight.")
    failures = _validate_llm_reasoning_output(reasoning, retrieval)
    assert "stage_3_prohibited_decision_language" in failures


def test_stage3_screen_exempts_verbatim_rule_quotes():
    rule = _rfcb_rule()
    retrieval = {"compare_mode": False, "matches": [(rule, 9)]}
    reasoning = _reasoning_payload(rule, why=[RFCB_STATEMENT])
    failures = _validate_llm_reasoning_output(reasoning, retrieval)
    assert failures == []


@pytest.mark.parametrize(
    "message",
    [
        "Please approve the change for flight use.",
        "Can you approve it?",
        "I need a waiver for this part.",
        "What is the final disposition for this nonconformance?",
        "Please sign-off on this design.",
    ],
)
def test_broadened_approval_pattern_refuses_decision_requests(tmp_path, message):
    result = answer_query(
        message=message,
        pack_names=["some_pack"],
        pack_dir=tmp_path,
    )
    assert result["status"] == "REFUSE"


def test_informational_query_is_not_refused_by_approval_pattern(tmp_path):
    result = answer_query(
        message="What tests are required for pure tin finishes?",
        pack_names=["some_pack"],
        pack_dir=tmp_path,
    )
    assert result["status"] != "REFUSE"


def test_read_env_int_defaults_on_garbage(monkeypatch):
    monkeypatch.setenv("ORACLE_TEST_INT", "not-a-number")
    assert read_env_int("ORACLE_TEST_INT", 7) == 7
    monkeypatch.setenv("ORACLE_TEST_INT", "-3")
    assert read_env_int("ORACLE_TEST_INT", 7) == 7
    monkeypatch.setenv("ORACLE_TEST_INT", " 12 ")
    assert read_env_int("ORACLE_TEST_INT", 7) == 12
    monkeypatch.delenv("ORACLE_TEST_INT")
    assert read_env_int("ORACLE_TEST_INT", 7) == 7
