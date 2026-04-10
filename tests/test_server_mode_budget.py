from __future__ import annotations

from server import UI_MAX_ROUNDS_CEILING, _clamp_user_rounds, _max_rounds_for_mode


def test_max_rounds_defaults_to_single_round_for_ui_modes(monkeypatch):
    monkeypatch.delenv("ORACLE_MAX_ROUNDS_POLISH", raising=False)
    monkeypatch.delenv("ORACLE_MAX_ROUNDS_REVIEW", raising=False)
    monkeypatch.delenv("ORACLE_MAX_ROUNDS_REWRITE", raising=False)

    assert _max_rounds_for_mode("polish") == 1
    assert _max_rounds_for_mode("review") == 1
    assert _max_rounds_for_mode("rewrite") == 1


def test_max_rounds_respects_env_override(monkeypatch):
    monkeypatch.setenv("ORACLE_MAX_ROUNDS_REVIEW", "2")
    assert _max_rounds_for_mode("review") == 2


def test_max_rounds_clamps_invalid_values(monkeypatch):
    monkeypatch.setenv("ORACLE_MAX_ROUNDS_REVIEW", "0")
    assert _max_rounds_for_mode("review") == 1

    monkeypatch.setenv("ORACLE_MAX_ROUNDS_REVIEW", "not-a-number")
    assert _max_rounds_for_mode("review") == 1


def test_max_rounds_env_override_caps_at_ui_ceiling(monkeypatch):
    monkeypatch.setenv("ORACLE_MAX_ROUNDS_REVIEW", "99")
    assert _max_rounds_for_mode("review") == UI_MAX_ROUNDS_CEILING


def test_clamp_user_rounds_falls_back_to_mode_default(monkeypatch):
    monkeypatch.delenv("ORACLE_MAX_ROUNDS_REVIEW", raising=False)
    assert _clamp_user_rounds(None, "review") == 1


def test_clamp_user_rounds_honors_in_range_value():
    assert _clamp_user_rounds(3, "review") == 3


def test_clamp_user_rounds_caps_above_ceiling():
    assert _clamp_user_rounds(99, "review") == UI_MAX_ROUNDS_CEILING


def test_clamp_user_rounds_floors_below_one():
    assert _clamp_user_rounds(0, "review") == 1
    assert _clamp_user_rounds(-5, "review") == 1


def test_clamp_user_rounds_accepts_exact_ceiling():
    assert _clamp_user_rounds(UI_MAX_ROUNDS_CEILING, "review") == UI_MAX_ROUNDS_CEILING
