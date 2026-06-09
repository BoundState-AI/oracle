"""Tests for run telemetry: usage capture, round telemetry files, and the run manifest."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import openai

from oracle import oracle2
from oracle.oracle2 import OracleConfig, PROVIDER_DISPATCH, _call_openai, call_oracle


def _reviewer_response(name: str) -> dict:
    return {
        "oracle_name": name,
        "role": "reviewer",
        "document_type": "spec",
        "overall_verdict": "revise",
        "findings": [],
        "top_3_must_fix": [],
        "_telemetry": {
            "response_model": f"{name.lower()}-model-2026-01-01",
            "input_tokens": 100,
            "output_tokens": 25,
        },
    }


def test_call_openai_captures_usage_and_model(monkeypatch):
    class DummyOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return SimpleNamespace(
                model="gpt-5.4-2026-03-01",
                usage=SimpleNamespace(prompt_tokens=1234, completion_tokens=567),
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            content='{"oracle_name":"Fran","findings":[]}',
                            refusal=None,
                        ),
                    )
                ],
            )

    monkeypatch.setattr(openai, "OpenAI", DummyOpenAI)

    config = OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model="gpt-5.4",
        system_prompt="Return JSON only.",
    )

    result = _call_openai(config, "review this")

    telemetry = result["_telemetry"]
    assert telemetry["response_model"] == "gpt-5.4-2026-03-01"
    assert telemetry["input_tokens"] == 1234
    assert telemetry["output_tokens"] == 567


def test_call_oracle_enriches_telemetry_with_call_facts(monkeypatch):
    def fake_dispatch(config, user_message):
        return {
            "oracle_name": "Fran",
            "findings": [{"title": "t", "severity": "low"}],
            "_telemetry": {"response_model": "actual-model", "input_tokens": 10},
        }

    monkeypatch.setitem(PROVIDER_DISPATCH, "openai", fake_dispatch)

    config = OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model="gpt-5.4",
        system_prompt="p",
    )

    result = call_oracle(config, "msg")

    telemetry = result["_telemetry"]
    assert telemetry["oracle"] == "Fran"
    assert telemetry["provider"] == "openai"
    assert telemetry["configured_model"] == "gpt-5.4"
    assert telemetry["response_model"] == "actual-model"  # provider data kept
    assert telemetry["attempts"] == 1
    assert isinstance(telemetry["latency_seconds"], float)


def test_run_review_persists_telemetry_and_manifest(monkeypatch, tmp_path):
    def fake_call_oracle(config, user_message):
        if config.name == "Beth":
            return {
                "oracle_name": "Beth",
                "role": "coordinator",
                "revision_decisions": [],
                "serious_issues": [],
                "feedback_themes": [],
                "architectural_risks_remaining": [],
                "revised_sections": [],
                "open_questions": [],
                "convergence_status": "converging",
                "recommendation": "LOCK",
                "recommendation_reason": "clean",
                "revised_draft": None,
                "_telemetry": {
                    "response_model": "claude-opus-4-8-actual",
                    "input_tokens": 500,
                    "output_tokens": 200,
                    "latency_seconds": 3.2,
                },
            }
        return _reviewer_response(config.name)

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    draft = "the spec"
    session = oracle2.run_review(
        draft=draft,
        document_path="spec.md",
        max_rounds=2,
        output_dir=tmp_path,
        workflow="manual",
    )
    assert session.converged is True

    # --- Run manifest (AUDIT D2) ---
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["workflow"] == "manual"
    expected_hash = "sha256:" + hashlib.sha256(draft.encode("utf-8")).hexdigest()
    assert manifest["document_sha256"] == expected_hash
    assert set(manifest["oracle_roster"]) == {
        "beth", "fran", "codex", "grok", "gemini", "sonnet",
    }
    for entry in manifest["oracle_roster"].values():
        assert entry["model"]
        assert entry["system_prompt_sha256"].startswith("sha256:")
    assert all(k.startswith("ORACLE_") for k in manifest["env_overrides"])
    assert not any("API_KEY" in k for k in manifest["env_overrides"]), (
        "API keys must never be persisted in the run manifest"
    )

    # --- Round telemetry file (AUDIT C1/D1) ---
    telemetry = json.loads(
        (tmp_path / "round1_telemetry.json").read_text(encoding="utf-8")
    )
    assert telemetry["Fran"]["input_tokens"] == 100
    assert telemetry["Fran"]["response_model"] == "fran-model-2026-01-01"
    assert telemetry["Beth"]["output_tokens"] == 200

    # --- Telemetry must NOT leak into oracle output files/prompt inputs ---
    fran_output = json.loads((tmp_path / "round1_fran.json").read_text(encoding="utf-8"))
    assert "_telemetry" not in fran_output
    beth_output = json.loads(
        (tmp_path / "round1_beth_decisions.json").read_text(encoding="utf-8")
    )
    assert "_telemetry" not in beth_output

    # --- Aggregated usage totals in the session summary ---
    summary = json.loads((tmp_path / "session_summary.json").read_text(encoding="utf-8"))
    totals = summary["usage_totals"]
    assert totals["Fran"]["calls"] == 1
    assert totals["Fran"]["input_tokens"] == 100
    assert totals["Beth"]["models"] == ["claude-opus-4-8-actual"]


def test_run_review_telemetry_tolerates_mocks_without_telemetry(monkeypatch, tmp_path):
    """Oracles that return no telemetry (tests, older code) must not break runs."""
    def fake_call_oracle(config, user_message):
        if config.name == "Beth":
            return {
                "oracle_name": "Beth",
                "role": "coordinator",
                "revision_decisions": [],
                "serious_issues": [],
                "feedback_themes": [],
                "architectural_risks_remaining": [],
                "revised_sections": [],
                "open_questions": [],
                "convergence_status": "converging",
                "recommendation": "LOCK",
                "recommendation_reason": "clean",
                "revised_draft": None,
            }
        response = _reviewer_response(config.name)
        response.pop("_telemetry")
        return response

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="spec",
        max_rounds=1,
        output_dir=tmp_path,
        workflow="manual",
    )

    assert session.converged is True
    telemetry = json.loads(
        (tmp_path / "round1_telemetry.json").read_text(encoding="utf-8")
    )
    assert telemetry["Fran"] == {}
