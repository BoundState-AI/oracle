"""Fixture loading and oracle mocking for the golden-case harness."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Sentinel value in a fixture round: this oracle's vendor is down and the
# call raises instead of returning a response. Used to simulate outages
# without reaching into provider internals — call_oracle is the external
# API seam, so raising here exercises the same path as a real exhausted
# retry loop.
VENDOR_OUTAGE = "__FAIL__"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a golden fixture transcript by case name (without .json)."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def golden_oracle(monkeypatch) -> Callable[[dict[str, Any]], list[tuple[str, int]]]:
    """Install a scripted call_oracle that replays a fixture transcript.

    Returns an installer: installer(fixture) -> call log of (oracle, round_idx).

    Responses are keyed by oracle display name (config.name) and indexed by
    a per-oracle call counter, so each oracle's Nth call receives the Nth
    round's scripted response. If a fixture has fewer rounds than the run
    requests, the last round's responses repeat — this models an oracle
    that has nothing new to say, which is the steady state convergence
    logic must handle.
    """
    from oracle import oracle2

    def install(fixture: dict[str, Any]) -> list[tuple[str, int]]:
        rounds: list[dict[str, Any]] = fixture["rounds"]
        counters: dict[str, int] = {}
        call_log: list[tuple[str, int]] = []

        def fake_call_oracle(config, user_message):  # noqa: ANN001 — mirrors oracle2.call_oracle
            idx = counters.get(config.name, 0)
            counters[config.name] = idx + 1
            call_log.append((config.name, idx))

            round_data = rounds[min(idx, len(rounds) - 1)]
            if config.name not in round_data:
                raise AssertionError(
                    f"Fixture {fixture.get('case', '?')} has no scripted response "
                    f"for {config.name} in round index {idx}"
                )
            response = round_data[config.name]
            if response == VENDOR_OUTAGE:
                raise RuntimeError(
                    f"[{config.name}] simulated vendor outage (golden fixture)"
                )
            # Deep-copy so orchestration code mutating the dict cannot
            # contaminate later rounds of the same transcript.
            return json.loads(json.dumps(response))

        monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)
        return call_log

    return install
