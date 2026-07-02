"""Pinning tests for Oracle chat engine internals.

Covers:
- _compare_packs with zero loadable packs degrades to INSUFFICIENT_DATA
  instead of IndexError-ing into a 500.
- The LLM reasoning payload and the audit stage artifacts serialize the SAME
  capped retrieval bundle (one shared helper — they must never drift apart).
"""
from oracle.chat_engine import (
    ChatPack,
    ChatRule,
    _build_llm_reasoning_payload,
    _build_stage_artifacts,
    _compare_packs,
)


def _rule(rule_id: str, statement: str, score_hint: str = "") -> ChatRule:
    return ChatRule(
        pack_slug="nasa_std_5009c",
        standard_id="NASA-STD-5009C",
        standard_title="NASA Fracture Control Standard",
        rule_id=rule_id,
        section="4.2",
        page=10,
        obligation_type="prohibition",
        obligation_keyword="shall not",
        statement_text=statement,
        subject=f"Connector plating {score_hint}".strip(),
        requirement=statement,
        justification="",
        keywords=("pure tin", "connector plating"),
        applies_to=("connectors",),
    )


def _pack(rules: tuple[ChatRule, ...]) -> ChatPack:
    return ChatPack(
        pack_slug="nasa_std_5009c",
        standard_id="NASA-STD-5009C",
        standard_title="NASA Fracture Control Standard",
        rules=rules,
    )


def _gatekeeper(compare_mode: bool) -> dict:
    return {
        "intent": "comparison" if compare_mode else "yes_no",
        "compare_mode": compare_mode,
        "filters": {"section": None, "table_note": None},
    }


def test_compare_packs_with_no_loadable_packs_returns_insufficient_data():
    result = _compare_packs("Compare pure tin requirements.", [])

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["compare_only"] is True
    assert result["selected_packs"] == []


def test_stage_artifact_matches_equal_llm_payload_matches_single_pack():
    rules = tuple(
        _rule(f"RULE-{index:03d}", f"Statement {index} about pure tin finish {index}.")
        for index in range(7)
    )
    retrieval = {
        "compare_mode": False,
        "packs_queried": [{"pack_slug": "nasa_std_5009c", "load_status": "ok"}],
        "matches": [(rule, 10 - index) for index, rule in enumerate(rules)],
    }
    gatekeeper = _gatekeeper(compare_mode=False)
    reasoning = {
        "answer_type": "yes_no",
        "retrieval_coverage": "complete",
        "evidence_assessment": "supported",
    }

    payload = _build_llm_reasoning_payload("Is pure tin prohibited?", gatekeeper, retrieval)
    artifacts = _build_stage_artifacts(gatekeeper, retrieval, reasoning)

    # The audit trail must record exactly the evidence the model saw.
    assert artifacts["retrieval"]["matches"] == payload["matches"]
    assert len(payload["matches"]) <= 5


def test_stage_artifact_matches_equal_llm_payload_matches_compare_mode():
    rules_a = tuple(_rule(f"A-{index}", f"Pack A statement {index}.") for index in range(4))
    rules_b = tuple(_rule(f"B-{index}", f"Pack B statement {index}.") for index in range(4))
    retrieval = {
        "compare_mode": True,
        "packs_queried": [
            {"pack_slug": "nasa_std_5009c", "load_status": "ok"},
            {"pack_slug": "nasa_std_5009c", "load_status": "ok"},
        ],
        "pack_findings": [
            {"pack": _pack(rules_a), "matches": [(rule, 8) for rule in rules_a]},
            {"pack": _pack(rules_b), "matches": [(rule, 6) for rule in rules_b]},
        ],
    }
    gatekeeper = _gatekeeper(compare_mode=True)
    reasoning = {
        "answer_type": "comparison",
        "retrieval_coverage": "complete",
        "evidence_assessment": "supported",
    }

    payload = _build_llm_reasoning_payload("Compare pure tin rules.", gatekeeper, retrieval)
    artifacts = _build_stage_artifacts(gatekeeper, retrieval, reasoning)

    assert artifacts["retrieval"]["matches_by_pack"] == payload["matches_by_pack"]
