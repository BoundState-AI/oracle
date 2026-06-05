"""Tests for provider integrations — strict schema enforcement and API error handling."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai

from oracle.oracle2 import _call_gemini, _call_openai, OracleConfig


def _make_response(
    *,
    content: str | None = None,
    refusal: str | None = None,
    finish_reason: str = "stop",
):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content, refusal=refusal),
            )
        ]
    )


def test_call_openai_uses_strict_schema_for_reasoning_models(monkeypatch):
    captured: dict[str, object] = {}

    class DummyOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured.update(kwargs)
            return _make_response(
                content=(
                    '{"oracle_name":"Fran","role":"adversarial_logic",'
                    '"document_type":"spec","overall_verdict":"revise",'
                    '"findings":[],"top_3_must_fix":[]}'
                )
            )

    monkeypatch.setattr(openai, "OpenAI", DummyOpenAI)

    config = OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model="gpt-5.4",
        system_prompt="Return JSON only.",
        max_tokens=24576,
    )

    result = _call_openai(config, "review this")

    assert result["oracle_name"] == "Fran"
    assert result["findings"] == []
    assert captured["max_completion_tokens"] == 24576
    assert captured["reasoning_effort"] in {"high", "medium", "low", "minimal"}
    assert captured["verbosity"] in {"low", "medium", "high"}
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True


def test_call_openai_returns_refusal_as_error(monkeypatch):
    class DummyOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return _make_response(refusal="Cannot comply.")

    monkeypatch.setattr(openai, "OpenAI", DummyOpenAI)

    config = OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model="gpt-5.4",
        system_prompt="Return JSON only.",
    )

    result = _call_openai(config, "review this")

    assert result["oracle_name"] == "Fran"
    assert result["error"] == "Model refusal"
    assert "Cannot comply." in result["raw"]


def test_call_openai_returns_empty_response_error(monkeypatch):
    class DummyOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return _make_response(content=None, finish_reason="length")

    monkeypatch.setattr(openai, "OpenAI", DummyOpenAI)

    config = OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model="gpt-5.4",
        system_prompt="Return JSON only.",
    )

    result = _call_openai(config, "review this")

    assert result["oracle_name"] == "Fran"
    assert result["error"] == "Empty response (finish_reason=length)"


def test_call_gemini_uses_generate_content_json_mode(monkeypatch):
    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"oracle_name":"Gemini","role":"domain_context",'
                                        '"document_type":"spec","overall_verdict":"revise",'
                                        '"findings":[],"top_3_must_fix":[]}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return DummyResponse()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "Client", DummyClient)

    config = OracleConfig(
        name="Gemini",
        role="domain_context",
        provider="gemini",
        model="gemini-2.5-pro",
        system_prompt="Return JSON only.",
        max_tokens=8192,
    )

    result = _call_gemini(config, "review this")

    assert result["oracle_name"] == "Gemini"
    assert result["findings"] == []
    assert "gemini-2.5-pro:generateContent" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_call_gemini_returns_missing_key_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    config = OracleConfig(
        name="Gemini",
        role="domain_context",
        provider="gemini",
        model="gemini-2.5-pro",
        system_prompt="Return JSON only.",
    )

    result = _call_gemini(config, "review this")

    assert result["oracle_name"] == "Gemini"
    assert result["error"] == "GEMINI_API_KEY or GOOGLE_API_KEY not set"
    assert result["findings"] == []
