"""Exercise the installed SDK contract that failed in production."""
import inspect
import httpx
from anthropic import Anthropic
from oracle.cli import _format_reviewer_pool_note


def test_real_sdk_accepts_oracle_timeout_and_stream_arguments():
    with Anthropic(api_key="fixture-not-real", timeout=httpx.Timeout(120, connect=10)) as client:
        assert client.timeout.connect == 10
        assert client.timeout.read == 120
        inspect.signature(client.messages.stream).bind(
            model="claude-opus-4-8", max_tokens=256,
            messages=[{"role": "user", "content": "fixture"}],
            temperature=1, thinking={"type": "adaptive"},
        )


def test_report_counts_active_reviewers_only():
    note = "\n".join(_format_reviewer_pool_note(None))
    assert "3 oracles across 2 vendors" in note
    assert "Gemini" not in note
