"""P1-D runtime boundary canary (spec v0.3 §1.1, §6, §12 P1-D) — fixture #2.

A BuyerPack full of unique sentinel values is held in memory while every
Phase-1 workflow runs under (a) a mocked network layer, (b) full log
capture, and (c) a filesystem watch. If any canary reaches any of those
surfaces, this suite is red. The *_red_on_leak tests prove the detectors
actually fire by leaking deliberately inside the test (handoff ACCEPT:
"canary test red when a deliberate leak is introduced")."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hearth.audit.artifact import build_artifact, write_artifact
from hearth.core.boundary import collect_canaries, find_leaks
from hearth.core.scrubber.engine import scrub_document
from hearth.data import BuyerPack
from hearth.packs.loader import load_pack
from hearth.utils.render import render_report

from .conftest import CANARY_BUYERPACK, GREYROCK_FIXTURE, RUN_DATE
from .netguard import BoundaryViolation, NetworkSentry


@pytest.fixture()
def canary_pack() -> BuyerPack:
    return BuyerPack.model_validate_json(
        CANARY_BUYERPACK.read_text(encoding="utf-8")
    )


@pytest.fixture()
def canaries(canary_pack) -> frozenset[str]:
    return collect_canaries(canary_pack)


def _all_log_text(caplog) -> str:
    return "\n".join(
        f"{record.name} {record.getMessage()}" for record in caplog.records
    )


def test_canary_fixture_is_actually_canaried(canaries):
    """Fixture #2 must stay discriminating; schema vocab must stay out."""
    assert "CANARY-HOUSEHOLD-9f3b1a" in canaries
    assert "CANARY-ANCHOR-URSA-MAJOR Berthoud CO" in canaries
    assert "7654321" in canaries and "7,654,321" in canaries
    assert "98765" in canaries  # max_appraisal_gap_usd
    assert "CANARYSHIRE-ALPHA-9q" in canaries
    assert "conventional" not in canaries  # schema vocabulary, not data
    assert "reveal_nothing" not in canaries
    assert len(canaries) >= 12


def test_phase1_workflows_leak_no_canary(canary_pack, canaries, caplog, tmp_path):
    """The headline P1-D assertion: full workload, zero canaries anywhere."""
    caplog.set_level(logging.DEBUG)
    with NetworkSentry() as sentry:
        # BuyerPack operations that exist in Phase 1: parse + round-trip.
        canary_pack.to_json_dict()
        canary_pack.model_dump_json()
        # The full scrub workflow, BuyerPack held in memory throughout.
        loaded = load_pack("CO-Larimer")
        run = scrub_document(
            GREYROCK_FIXTURE, loaded.pack, target_price_usd=700_000, run_date=RUN_DATE
        )
        rendered = render_report(run, loaded.pack)
        artifact = build_artifact(run, loaded, rendered, exit_code=0)
        write_artifact(artifact, tmp_path / "audit")

    assert sentry.attempts == [], "no outbound call may even be attempted"
    assert find_leaks(_all_log_text(caplog), canaries) == []
    assert find_leaks(rendered, canaries) == []
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written, "audit artifact should exist"
    for path in written:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert find_leaks(text, canaries) == [], f"canary in {path}"


def test_log_leak_turns_red_on_leak(canary_pack, canaries, caplog):
    """Deliberate leak class 1: a BuyerPack field reaches a log call."""
    caplog.set_level(logging.DEBUG)
    leaky_logger = logging.getLogger("hearth.tests.deliberate_leak")
    leaky_logger.info("household=%s", canary_pack.identity.household)

    leaks = find_leaks(_all_log_text(caplog), canaries)
    assert leaks == ["CANARY-HOUSEHOLD-9f3b1a"], (
        "log-capture detector failed to catch a deliberate leak — "
        "the boundary scaffold is broken"
    )


def test_network_leak_turns_red_on_leak(canary_pack):
    """Deliberate leak class 2: an outbound call carrying pack data."""
    import socket

    with NetworkSentry() as sentry:
        with pytest.raises(BoundaryViolation):
            socket.create_connection(("203.0.113.7", 443))
        with pytest.raises(BoundaryViolation):
            socket.getaddrinfo(canary_pack.identity.household, 443)
    assert len(sentry.attempts) == 2


def test_file_leak_turns_red_on_leak(canary_pack, canaries, tmp_path):
    """Deliberate leak class 3: pack data written to a non-store file."""
    leaky_file = tmp_path / "innocuous_cache.json"
    leaky_file.write_text(
        canary_pack.model_dump_json(), encoding="utf-8"
    )
    leaks = find_leaks(leaky_file.read_text(encoding="utf-8"), canaries)
    assert "CANARY-HOUSEHOLD-9f3b1a" in leaks
    assert "7654321" in leaks


def test_number_canaries_catch_formatted_renderings(canaries):
    """Budget leaking as '$7,654,321' is still the budget leaking."""
    assert find_leaks("monthly cap implies $7,654,321 ceiling", canaries) == [
        "7,654,321"
    ]


def test_allow_list_is_explicit_and_narrow(canaries):
    leaked_then_allowed = find_leaks(
        "ceiling 7654321", canaries, allow=frozenset({"7654321", "7,654,321"})
    )
    assert leaked_then_allowed == []
