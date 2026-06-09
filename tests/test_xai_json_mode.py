"""Tests for the opt-in xAI structured-output flag (default off until live-verified)."""
from __future__ import annotations

from types import SimpleNamespace

import openai

from oracle.oracle2 import OracleConfig, _call_xai


def _dummy_openai(captured: dict):
    class DummyOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"oracle_name":"Grok","findings":[]}'
                        )
                    )
                ]
            )

    return DummyOpenAI


def _config() -> OracleConfig:
    return OracleConfig(
        name="Grok", role="contrarian", provider="xai",
        model="grok-4.20", system_prompt="p",
    )


def test_xai_json_mode_off_by_default(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(openai, "OpenAI", _dummy_openai(captured))
    monkeypatch.delenv("ORACLE_XAI_JSON_MODE", raising=False)

    result = _call_xai(_config(), "review this")

    assert result["oracle_name"] == "Grok"
    assert "response_format" not in captured


def test_xai_json_mode_opt_in_sends_strict_schema(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(openai, "OpenAI", _dummy_openai(captured))
    monkeypatch.setenv("ORACLE_XAI_JSON_MODE", "1")

    _call_xai(_config(), "review this")

    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
