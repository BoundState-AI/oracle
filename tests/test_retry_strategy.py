"""Tests for retry backoff strategy — Retry-After honoring, 429 handling, jitter."""
from __future__ import annotations

from types import SimpleNamespace

from oracle import oracle2
from oracle.oracle2 import (
    MAX_RETRY_DELAY_SECONDS,
    RATE_LIMIT_BACKOFF_MULTIPLIER,
    RETRY_BACKOFF,
    _retry_delay,
)


def _error_with_retry_after(value) -> SimpleNamespace:
    return SimpleNamespace(response=SimpleNamespace(headers={"retry-after": value}))


def test_retry_after_header_is_honored():
    delay = _retry_delay(1, _error_with_retry_after("30"))

    assert delay == 30.0


def test_retry_after_below_base_is_raised_to_base():
    """A vendor saying 'retry in 0s' still gets at least the local base."""
    delay = _retry_delay(1, _error_with_retry_after("0"))

    assert delay == float(RETRY_BACKOFF[0])


def test_pathological_retry_after_is_capped():
    delay = _retry_delay(1, _error_with_retry_after("99999"))

    assert delay == MAX_RETRY_DELAY_SECONDS


def test_non_numeric_retry_after_falls_back_to_schedule(monkeypatch):
    monkeypatch.setattr(oracle2.random, "uniform", lambda a, b: 0.0)

    delay = _retry_delay(1, _error_with_retry_after("soon"))

    assert delay == float(RETRY_BACKOFF[0])


def test_rate_limit_errors_get_multiplied_backoff(monkeypatch):
    monkeypatch.setattr(oracle2.random, "uniform", lambda a, b: 0.0)

    delay = _retry_delay(1, RuntimeError("API error 429: rate limited"))

    assert delay == float(RETRY_BACKOFF[0]) * RATE_LIMIT_BACKOFF_MULTIPLIER


def test_transient_errors_use_base_schedule_with_bounded_jitter():
    base = float(RETRY_BACKOFF[1])

    delay = _retry_delay(2, RuntimeError("connection reset"))

    assert base <= delay <= base * 1.25


def test_string_failures_from_parse_errors_still_detect_429(monkeypatch):
    """Parse/schema failures carry strings, not exceptions — 429 still counts."""
    monkeypatch.setattr(oracle2.random, "uniform", lambda a, b: 0.0)

    delay = _retry_delay(1, "Gemini API error 429")

    assert delay == float(RETRY_BACKOFF[0]) * RATE_LIMIT_BACKOFF_MULTIPLIER
