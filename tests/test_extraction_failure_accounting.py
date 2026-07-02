"""Failure accounting for paid extraction loops (spec §5.4/§5.5).

Covers:
  - chunk failures recorded in ExtractionResult metadata (never silently
    absorbed) for both detect_implicit_obligations and enrich_with_sonnet
  - consecutive-failure abort (max 3) with the unprocessed tail recorded
  - immediate abort on auth errors (no doomed retry storm)
  - malformed-JSON re-prompt ladder (strip fences -> re-prompt -> max 2)
  - 1-page chunk overlap in implicit detection
  - GPCM tag reconciliation: unmatched tags emit a block-text fallback
    requirement plus a warning, never a silent skip
  - targeted vision repair capping / target selection

All model interactions go through injected fake clients — no monkeypatching
of engine internals, no network.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

import fitz
import pytest

from oracle.gpcm_rulepack_adapter import (
    _resolve_max_vision_repairs,
    build_tagged_requirements,
    select_targeted_vision_targets,
    warn_unmatched_tags,
)
from oracle.shall_extractor import (
    ExtractionResult,
    ShallStatement,
    _attribute_statement_page,
    detect_implicit_obligations,
    enrich_with_sonnet,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Content:
    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str):
        self.content = [_Content(text)]


class FakeAnthropicClient:
    """Stub for anthropic.Anthropic exposing messages.create.

    ``outcomes`` is a list of str payloads (returned as response text) or
    Exception instances (raised).  When exhausted, the last outcome repeats.
    """

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes[min(len(self.calls) - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)


class AuthenticationError(Exception):
    """Name-matched by the extractor's API-error triage (like anthropic's)."""


def _make_pdf(tmp_path: Path, page_texts: list[str], name: str = "fixture.pdf") -> Path:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((60, 60), text, fontsize=9)
    pdf_path = tmp_path / name
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _empty_result(total_pages: int) -> ExtractionResult:
    return ExtractionResult(
        source_file="fixture.pdf",
        total_pages=total_pages,
        extraction_date="2026-01-01",
        total_statements=0,
    )


_PAGE_TEXT = (
    "The facility operates continuously and all reports are archived daily "
    "in the central records library for later review by the program office."
)


# ---------------------------------------------------------------------------
# Chunk-failure accounting (detect_implicit_obligations)
# ---------------------------------------------------------------------------


def test_implicit_chunk_failure_is_recorded_in_result_metadata(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT, _PAGE_TEXT])
    client = FakeAnthropicClient([RuntimeError("simulated API failure")])
    result = _empty_result(2)

    result = detect_implicit_obligations(
        result, pdf_path, client=client, retry_base_delay=0.0,
    )

    assert result.extraction_status == "partial"
    assert result.failed_page_ranges == ["1-2"]
    assert len(result.chunk_failures) == 1
    failure = result.chunk_failures[0]
    assert failure["page_start"] == 1
    assert failure["page_end"] == 2
    assert failure["retries_used"] == 2  # 3 attempts = 2 retries
    assert failure["extraction_mode"] == "text_implicit"
    assert "simulated API failure" in failure["final_error"]
    # Transient errors are retried before the chunk is declared failed.
    assert len(client.calls) == 3


def test_failure_fields_serialize_into_result_json(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT])
    client = FakeAnthropicClient([RuntimeError("boom")])
    result = detect_implicit_obligations(
        _empty_result(1), pdf_path, client=client, retry_base_delay=0.0,
    )

    payload = json.loads(json.dumps(asdict(result)))
    assert payload["extraction_status"] == "partial"
    assert payload["failed_page_ranges"] == ["1-1"]
    assert payload["chunk_failures"][0]["final_error"].endswith("boom")


def test_implicit_success_keeps_status_complete(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT])
    payload = json.dumps({
        "obligations": [{
            "statement_text": "All reports are archived daily in the central records library",
            "requirement": "Archive reports daily",
            "subject": "contractor",
            "section": "1.1",
            "confidence": 0.9,
            "keywords": ["reports"],
            "context": "recurring duty",
        }]
    })
    client = FakeAnthropicClient([payload])

    result = detect_implicit_obligations(
        _empty_result(1), pdf_path, client=client, retry_base_delay=0.0,
    )

    assert result.extraction_status == "complete"
    assert result.chunk_failures == []
    implicit = [s for s in result.statements if s.obligation_type == "implicit"]
    assert len(implicit) == 1
    assert implicit[0].page == 1
    assert implicit[0].page_uncertain is False


# ---------------------------------------------------------------------------
# Consecutive-failure abort + auth abort
# ---------------------------------------------------------------------------


def test_consecutive_failures_abort_run_and_record_tail(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT] * 25)
    client = FakeAnthropicClient([RuntimeError("persistent outage")])

    result = detect_implicit_obligations(
        _empty_result(25), pdf_path, client=client,
        retry_base_delay=0.0, max_consecutive_failures=3,
    )

    assert result.extraction_status == "partial"
    # 3 failed chunks (1-page overlap: 1-5, 5-9, 9-13), then the unprocessed
    # tail recorded as a single not-attempted range.
    assert result.failed_page_ranges == ["1-5", "5-9", "9-13", "13-25"]
    assert result.chunk_failures[-1]["final_error"].startswith("not attempted:")
    # 3 chunks x 3 API attempts each — NOT one attempt per remaining chunk.
    assert len(client.calls) == 9


def test_auth_error_aborts_immediately_without_retry_storm(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT] * 25)
    client = FakeAnthropicClient([AuthenticationError("invalid x-api-key")])

    result = detect_implicit_obligations(
        _empty_result(25), pdf_path, client=client, retry_base_delay=0.0,
    )

    # A revoked key must not burn one attempt per chunk for 25 pages.
    assert len(client.calls) == 1
    assert result.extraction_status == "partial"
    assert result.failed_page_ranges == ["1-25"]
    assert "invalid x-api-key" in result.chunk_failures[0]["final_error"]


def test_rate_limit_errors_are_retried_not_aborted(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT])

    class RateLimitError(Exception):
        status_code = 429

    client = FakeAnthropicClient([
        RateLimitError("slow down"),
        json.dumps({"obligations": []}),
    ])

    result = detect_implicit_obligations(
        _empty_result(1), pdf_path, client=client, retry_base_delay=0.0,
    )

    assert len(client.calls) == 2
    assert result.extraction_status == "complete"


# ---------------------------------------------------------------------------
# Malformed-JSON re-prompt ladder (spec §5.4)
# ---------------------------------------------------------------------------


def test_malformed_json_triggers_reprompt_then_succeeds(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT])
    good_payload = json.dumps({
        "obligations": [{
            "statement_text": "All reports are archived daily in the central records library",
            "requirement": "Archive reports daily",
            "subject": "contractor",
            "confidence": 0.8,
        }]
    })
    client = FakeAnthropicClient(["this is { not valid json", good_payload])

    result = detect_implicit_obligations(
        _empty_result(1), pdf_path, client=client, retry_base_delay=0.0,
    )

    assert len(client.calls) == 2
    # Second call must carry the malformed output + valid-JSON-only re-prompt.
    reprompt_messages = client.calls[1]["messages"]
    assert len(reprompt_messages) == 3
    assert reprompt_messages[1]["role"] == "assistant"
    assert "not valid json" in reprompt_messages[1]["content"]
    assert "valid JSON only" in reprompt_messages[2]["content"]
    assert result.extraction_status == "complete"
    assert sum(1 for s in result.statements if s.obligation_type == "implicit") == 1


def test_persistently_malformed_json_becomes_chunk_failure(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT])
    client = FakeAnthropicClient(["still } not json"])

    result = detect_implicit_obligations(
        _empty_result(1), pdf_path, client=client, retry_base_delay=0.0,
    )

    # Initial call + 2 re-prompts, then the chunk is recorded as failed.
    assert len(client.calls) == 3
    assert result.extraction_status == "partial"
    assert "invalid JSON" in result.chunk_failures[0]["final_error"]
    assert result.chunk_failures[0]["retries_used"] == 2


def test_fenced_json_is_accepted_without_reprompt(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT])
    fenced = "```json\n" + json.dumps({"obligations": []}) + "\n```"
    client = FakeAnthropicClient([fenced])

    result = detect_implicit_obligations(
        _empty_result(1), pdf_path, client=client, retry_base_delay=0.0,
    )

    assert len(client.calls) == 1
    assert result.extraction_status == "complete"


# ---------------------------------------------------------------------------
# Chunk overlap (fix: disjoint chunks despite overlap-parity comment)
# ---------------------------------------------------------------------------


def test_implicit_chunks_overlap_by_one_page(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT] * 7)
    client = FakeAnthropicClient([json.dumps({"obligations": []})])

    detect_implicit_obligations(
        _empty_result(7), pdf_path, client=client, retry_base_delay=0.0,
    )

    def _pages_in_call(call) -> list[int]:
        content = call["messages"][0]["content"]
        return [int(m) for m in
                __import__("re").findall(r"--- PAGE (\d+) ---", content)]

    chunk_pages = [_pages_in_call(call) for call in client.calls]
    assert chunk_pages == [[1, 2, 3, 4, 5], [5, 6, 7]]


# ---------------------------------------------------------------------------
# Page attribution (fix: fabricated page precision)
# ---------------------------------------------------------------------------


def test_page_attribution_refuses_to_fabricate_page():
    chunk_pages = [(3, "totally unrelated page text about welding processes")]
    page, uncertain = _attribute_statement_page(
        "Deliverables follow the electronic submission portal cadence", chunk_pages,
    )
    assert page == 0
    assert uncertain is True


def test_page_attribution_fuzzy_matches_light_paraphrase():
    chunk_pages = [
        (4, "irrelevant narrative about coatings and plating controls"),
        (6, "All deliverables are submitted through the electronic portal each month."),
    ]
    page, uncertain = _attribute_statement_page(
        "all deliverables are submitted through the electronic portal", chunk_pages,
    )
    assert page == 6
    assert uncertain is False


# ---------------------------------------------------------------------------
# enrich_with_sonnet failure accounting
# ---------------------------------------------------------------------------


def _mpr_statement(id_: int, page: int) -> ShallStatement:
    return ShallStatement(
        id=id_,
        page=page,
        section="4.1",
        obligation_keyword="shall",
        obligation_type="mandatory",
        statement_text="Programs shall verify fracture-critical parts.",
        subject="Programs",
        requirement="verify fracture-critical parts",
        context="",
        mpr_id=f"MPR {id_}",
    )


def test_enrich_with_sonnet_records_page_failures(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT])
    result = _empty_result(1)
    result.statements = [_mpr_statement(1, page=1)]
    result.total_statements = 1
    client = FakeAnthropicClient([RuntimeError("vision backend down")])

    result = enrich_with_sonnet(
        result, pdf_path, client=client, retry_base_delay=0.0,
    )

    assert result.extraction_status == "partial"
    assert result.failed_page_ranges == ["1-1"]
    failure = result.chunk_failures[0]
    assert failure["extraction_mode"] == "vision_enrichment"
    assert failure["retries_used"] == 2
    assert "vision backend down" in failure["final_error"]


def test_enrich_with_sonnet_auth_error_aborts_run(tmp_path):
    pdf_path = _make_pdf(tmp_path, [_PAGE_TEXT] * 3)
    result = _empty_result(3)
    result.statements = [_mpr_statement(i, page=i) for i in (1, 2, 3)]
    result.total_statements = 3
    client = FakeAnthropicClient([AuthenticationError("revoked key")])

    result = enrich_with_sonnet(
        result, pdf_path, client=client, retry_base_delay=0.0,
    )

    assert len(client.calls) == 1
    assert result.extraction_status == "partial"
    assert result.failed_page_ranges == ["1-3"]


# ---------------------------------------------------------------------------
# GPCM tag reconciliation (fix: silently skipped tags)
# ---------------------------------------------------------------------------


def _tag_block(tag: str = "MPR 7") -> dict:
    return {
        "tag": tag,
        "page": 4,
        "section": "4.2",
        "text": f"[{tag}] The program shall maintain a materials identification and usage list.",
    }


def test_unmatched_tag_emits_block_text_fallback_requirement():
    requirements = build_tagged_requirements(
        statements=[],  # no extractor statement matches the tag block
        tag_blocks=[_tag_block()],
        frequent_lines=set(),
        inline_rationales={},
    )

    assert len(requirements) == 1
    req = requirements[0]
    assert req["source_tag"] == "MPR 7"
    assert req["match_source"] == "block_text_fallback"
    assert req["shall_text"] == (
        "The program shall maintain a materials identification and usage list."
    )
    assert req["page"] == 4
    assert req["section"] == "4.2"
    assert req["id"] == "7"


def test_boilerplate_filtered_statement_still_yields_fallback(caplog):
    block = _tag_block("NER 3")
    statement = {
        "id": 9,
        "page": 4,
        "section": "4.2",
        "statement_text": "The program shall maintain a materials identification and usage list.",
        "context": "",
    }
    with caplog.at_level(logging.WARNING, logger="oracle.gpcm_rulepack_adapter"):
        requirements = build_tagged_requirements(
            statements=[statement],
            tag_blocks=[block],
            # The only candidate statement is boilerplate-filtered...
            frequent_lines={"the program shall maintain a materials identification and usage list."},
            inline_rationales={},
        )

    # ...but the tag is still emitted via the block-text fallback, loudly.
    assert [r["source_tag"] for r in requirements] == ["NER 3"]
    assert requirements[0]["match_source"] == "block_text_fallback"
    assert any("block-text fallback" in rec.message for rec in caplog.records)


def test_warn_unmatched_tags_logs_each_missing_tag(caplog):
    blocks = [_tag_block("MPR 7"), _tag_block("MPR 8")]
    emitted = [{"source_tag": "MPR 7"}]

    with caplog.at_level(logging.WARNING, logger="oracle.gpcm_rulepack_adapter"):
        missing = warn_unmatched_tags(blocks, emitted)

    assert missing == ["MPR 8"]
    assert any("MPR 8" in rec.message for rec in caplog.records)


def test_warn_unmatched_tags_quiet_when_reconciled():
    blocks = [_tag_block("MPR 7")]
    emitted = [{"source_tag": "MPR 7"}]
    assert warn_unmatched_tags(blocks, emitted) == []


# ---------------------------------------------------------------------------
# Targeted vision repair capping / target selection
# ---------------------------------------------------------------------------


def test_missing_justification_only_requirements_are_skipped():
    healthy = {
        "source_tag": "MPR 1",
        "shall_text": "Programs shall verify fracture-critical parts before flight.",
        "justification": "",
    }
    broken = {
        "source_tag": "MPR 2",
        "shall_text": "e",
        "justification": "",
    }
    untagged_broken = {
        "source_tag": None,
        "shall_text": "e",
        "justification": "",
    }

    targets = select_targeted_vision_targets([healthy, broken, untagged_broken])

    # `healthy` is weak ONLY for missing_justification -> not worth a paid
    # vision call; `untagged_broken` cannot be repaired without a tag.
    assert targets == [broken]


def test_max_vision_repairs_explicit_parameter_wins():
    assert _resolve_max_vision_repairs(7) == 7
    assert _resolve_max_vision_repairs(0) == 0


def test_max_vision_repairs_defaults_without_env_override():
    import os

    if "ORACLE_MAX_VISION_REPAIRS" not in os.environ:
        assert _resolve_max_vision_repairs(None) == 25
