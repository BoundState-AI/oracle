"""Tests for degraded-quorum salvage and failure forensics (HEARTH zero-finding abort)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from oracle import oracle2
from oracle.cli import format_findings_report
from oracle.oracle2 import (
    OracleCallError,
    OracleConfig,
    PROVIDER_DISPATCH,
    _min_valid_reviewers,
    call_oracle,
    preflight_models,
)


def _reviewer_response(name: str, severity: str = "high") -> dict:
    return {
        "oracle_name": name,
        "role": "reviewer",
        "document_type": "spec",
        "overall_verdict": "revise",
        "findings": [
            {
                "title": f"{name} finding",
                "severity": severity,
                "category": "feasibility",
                "location": "Section 1",
                "evidence": "example",
                "problem": "real problem",
                "why_it_matters": "matters",
                "proposed_fix": "fix it",
                "confidence": 0.8,
                "speculative": False,
            }
        ],
        "top_3_must_fix": [f"{name} finding"],
    }


def _beth_lock(found_titles: list[str]) -> dict:
    return {
        "oracle_name": "Beth",
        "role": "coordinator",
        "revision_decisions": [
            {"issue_id": "BETH-R1-ISSUE-001", "decision": "accepted_defect", "reason": "real"}
        ],
        "serious_issues": [
            {
                "issue_id": "BETH-R1-ISSUE-001",
                "title": found_titles[0] if found_titles else "issue",
                "severity": "high",
                "source_reviewers": ["Fran"],
                "summary": "s",
                "resolution": "fixed",
            }
        ],
        "feedback_themes": [],
        "architectural_risks_remaining": [],
        "revised_sections": [],
        "open_questions": [],
        "convergence_status": "converging",
        "recommendation": "LOCK",
        "recommendation_reason": "clean",
        "revised_draft": None,
    }


def _single_outage_mock(monkeypatch, failing: str = "Grok") -> dict:
    """Mock where one vendor is hard-down; captures Beth's prompt."""
    captured: dict = {}

    def fake_call_oracle(config, user_message):
        if config.name == failing:
            raise OracleCallError(
                f"[{failing}] Failed after 3 attempts: ConnectTimeout: (exception carried no message)",
                attempt_log=[
                    {"attempt": 1, "elapsed_seconds": 10.02,
                     "failure_class": "ConnectTimeout", "status_code": None,
                     "error": "(exception carried no message)"},
                ],
            )
        if config.name == "Beth":
            captured["beth_message"] = user_message
            return _beth_lock(["Fran finding"])
        return _reviewer_response(config.name)

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)
    return captured


def test_single_vendor_outage_salvages_round_with_quorum(monkeypatch, tmp_path):
    """THE HEARTH FIX: one dead vendor must not discard three valid reviews."""
    captured = _single_outage_mock(monkeypatch, failing="Grok")

    session = oracle2.run_review(
        draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual",
    )

    assert session.converged is True, "Three valid reviewers must be a usable round"
    assert session.rounds[0].valid is True
    assert session.rounds[0].missing_reviewers == ["Grok"]
    # Nonzero findings survived (the failed run reported 0/0/0)
    assert session.rounds[0].normalized_issues["normalized_issues"]
    # Degraded quorum can never claim full agreement
    assert session.consensus_type == "stable_with_notes"
    assert "Degraded quorum" in session.convergence_reason
    assert "Grok" in session.convergence_reason


def test_failed_reviewer_content_never_reaches_synthesis(monkeypatch, tmp_path):
    """Fail-closed: the error placeholder is not a review and must not enter
    Beth's bundle; the absence is disclosed as an explicit note instead."""
    captured = _single_outage_mock(monkeypatch, failing="Grok")

    oracle2.run_review(draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual")

    beth_message = captured["beth_message"]
    assert "### Grok" not in beth_message
    assert "## Missing Reviewers" in beth_message
    assert "Do not infer agreement" in beth_message


def test_failure_forensics_persisted_in_round_telemetry(monkeypatch, tmp_path):
    """The matrix the HEARTH postmortem could not build: per-attempt class,
    status, and latency must survive in roundN_telemetry.json."""
    _single_outage_mock(monkeypatch, failing="Grok")

    oracle2.run_review(draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual")

    telemetry = json.loads((tmp_path / "round1_telemetry.json").read_text(encoding="utf-8"))
    grok = telemetry["Grok"]
    assert grok["failed"] is True
    assert grok["attempt_log"][0]["failure_class"] == "ConnectTimeout"
    assert grok["attempt_log"][0]["error"] == "(exception carried no message)"


def test_quorum_threshold_is_configurable(monkeypatch, tmp_path):
    """ORACLE_MIN_VALID_REVIEWERS=4 restores the strict all-or-nothing mode."""
    monkeypatch.setenv("ORACLE_MIN_VALID_REVIEWERS", "4")
    _single_outage_mock(monkeypatch, failing="Grok")

    session = oracle2.run_review(
        draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual",
    )

    assert session.converged is False
    assert all(not r.valid for r in session.rounds)


def test_quorum_floor_is_two(monkeypatch):
    """One reviewer is not a cross-check; configured values below 2 clamp."""
    monkeypatch.setenv("ORACLE_MIN_VALID_REVIEWERS", "1")
    assert _min_valid_reviewers() == 2


def test_two_failed_reviewers_still_salvage_at_default_quorum(monkeypatch, tmp_path):
    failing = {"Grok", "Gemini"}

    def fake_call_oracle(config, user_message):
        if config.name in failing:
            raise OracleCallError(f"[{config.name}] Failed after 3 attempts: down")
        if config.name == "Beth":
            return _beth_lock(["Fran finding"])
        return _reviewer_response(config.name)

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual",
    )

    assert session.converged is True
    assert session.rounds[0].missing_reviewers == ["Gemini", "Grok"]


def test_three_failed_reviewers_fall_below_default_quorum(monkeypatch, tmp_path):
    failing = {"Codex", "Grok", "Gemini"}

    def fake_call_oracle(config, user_message):
        if config.name in failing:
            raise OracleCallError(f"[{config.name}] Failed after 3 attempts: down")
        if config.name == "Beth":
            raise AssertionError("Beth must not run below quorum")
        return _reviewer_response(config.name)

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual",
    )

    assert session.converged is False
    assert all(not r.valid for r in session.rounds)


def test_report_discloses_degraded_quorum(monkeypatch, tmp_path):
    _single_outage_mock(monkeypatch, failing="Grok")
    session = oracle2.run_review(
        draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual",
    )

    report = format_findings_report(session, pack_dir=tmp_path)

    assert "Degraded quorum:" in report
    assert "3/4 reviewers" in report
    assert "Grok" in report
    assert "not agreement" in report


def test_call_oracle_raises_with_attempt_log(monkeypatch):
    """Empty-message network exceptions must still classify by class name."""
    import httpx

    def dead_dispatch(config, user_message):
        raise httpx.ConnectTimeout("")

    monkeypatch.setitem(PROVIDER_DISPATCH, "xai", dead_dispatch)
    monkeypatch.setattr(oracle2.time, "sleep", lambda _s: None)

    config = OracleConfig(
        name="Grok", role="contrarian", provider="xai",
        model="grok-4.20", system_prompt="p",
    )

    with pytest.raises(OracleCallError) as exc_info:
        call_oracle(config, "msg")

    log = exc_info.value.attempt_log
    assert len(log) == 3  # one entry per attempt
    assert all(entry["failure_class"] == "ConnectTimeout" for entry in log)
    assert all(entry["error"] == "(exception carried no message)" for entry in log)
    assert "ConnectTimeout" in str(exc_info.value)


def test_preflight_passes_when_models_respond_with_prose(monkeypatch):
    def pong_dispatch(config, user_message):
        # Prose reply -> _parse_json error "No JSON found" -> still proves
        # transport + auth + model ID are all fine.
        return {"oracle_name": config.name, "error": "No JSON found", "raw": "pong"}

    for provider in ("anthropic", "openai", "xai", "gemini"):
        monkeypatch.setitem(PROVIDER_DISPATCH, provider, pong_dispatch)

    assert preflight_models() == []


def test_preflight_names_the_failing_vendor_and_model(monkeypatch):
    def dispatch(config, user_message):
        if config.provider == "xai":
            raise RuntimeError("404 model grok-4.5 does not exist")
        return {"oracle_name": config.name, "error": "No JSON found", "raw": "pong"}

    for provider in ("anthropic", "openai", "xai", "gemini"):
        monkeypatch.setitem(PROVIDER_DISPATCH, provider, dispatch)

    failures = preflight_models()

    assert len(failures) == 1
    assert failures[0]["provider"] == "xai"
    # Default roster model — keep in sync with oracle2's ORACLE_GROK_MODEL default
    assert failures[0]["model"] == "grok-4.5"
    assert "does not exist" in failures[0]["error"]


def test_preflight_gate_aborts_run_before_any_review_call(monkeypatch, tmp_path):
    monkeypatch.setenv("ORACLE_PREFLIGHT", "1")
    review_calls: list[str] = []

    def dead_preflight():
        return [{"oracle": "Grok", "provider": "xai", "model": "grok-4.20",
                 "failure_class": "ConnectError", "error": "(exception carried no message)"}]

    def tracking_call_oracle(config, user_message):
        review_calls.append(config.name)
        return _reviewer_response(config.name)

    monkeypatch.setattr(oracle2, "preflight_models", dead_preflight)
    monkeypatch.setattr(oracle2, "call_oracle", tracking_call_oracle)

    with pytest.raises(OracleCallError, match="Preflight failed"):
        oracle2.run_review(draft="spec", max_rounds=2, output_dir=tmp_path, workflow="manual")

    assert review_calls == [], "No review spend after a failed preflight"
