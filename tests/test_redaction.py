"""Tests for credential redaction in persisted artifacts and logs."""
from __future__ import annotations

import httpx

from oracle.oracle2 import OracleConfig, _call_gemini, _parse_json
from oracle.redact import REDACTED, redact_secrets


def test_redact_secrets_strips_vendor_key_shapes():
    text = (
        "openai sk-proj-abcdefghijklmnop1234 and "
        "anthropic sk-ant-abcdefghijklmnop1234 and "
        "google AIzaSyAbCdEfGhIjKlMnOp and "
        "xai xai-abcdefghijklmnop1234 and "
        "Authorization: Bearer abcdefghijklmnop.12345"
    )

    redacted = redact_secrets(text)

    assert "sk-" not in redacted.replace(REDACTED, "")
    assert "AIza" not in redacted
    assert "xai-" not in redacted.replace(REDACTED, "")
    assert "abcdefghijklmnop" not in redacted
    assert redacted.count(REDACTED) == 5


def test_redact_secrets_leaves_prose_alone():
    text = "We use sk-learn and the xai-style prompt format in section 3."

    assert redact_secrets(text) == text


def test_parse_json_failure_redacts_persisted_raw():
    text = "Error: request failed with key sk-abcdefghijklmnopqrstuvwx no json here"

    result = _parse_json(text, "Fran")

    assert result["error"] == "No JSON found"
    assert "sk-abcdefghijklmnopqrstuvwx" not in result["raw"]
    assert REDACTED in result["raw"]


def test_gemini_http_error_body_is_redacted(monkeypatch):
    class DummyResponse:
        status_code = 403
        text = '{"error": "bad key AIzaSyAbCdEfGhIjKlMnOpQr provided"}'

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, *, headers, json):
            return DummyResponse()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "Client", DummyClient)

    config = OracleConfig(
        name="Gemini",
        role="domain_context",
        provider="gemini",
        model="gemini-2.5-pro",
        system_prompt="p",
    )

    result = _call_gemini(config, "review this")

    assert "AIza" not in result["raw"]
    assert REDACTED in result["raw"]
