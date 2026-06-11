"""P1-B acceptance gate: the Grey Rock BDB24-6-24 document IS the unit test
(spec v0.3 §2.5, §12 P1-B).

Required minimum findings: fee/warn (pre-filled 3%), scope/flag
(region-wide), backstop/flag with exposure_usd = 3% x $700,000 = $21,000,
default_trap/flag (fee survives buyer default). Golden-file comparison pins
the full output; regenerate deliberately with HEARTH_UPDATE_GOLDEN=1."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hearth.core.scrubber.engine import scrub_document
from hearth.packs.loader import load_pack

from .conftest import GREYROCK_FIXTURE, RUN_DATE

GOLDEN = Path(__file__).parent / "golden" / "greyrock_findings.json"
TARGET_PRICE = 700_000


@pytest.fixture(scope="module")
def greyrock_run():
    loaded = load_pack("CO-Larimer")
    return scrub_document(
        GREYROCK_FIXTURE, loaded.pack, target_price_usd=TARGET_PRICE, run_date=RUN_DATE
    )


def _run_payload(run) -> dict:
    return {
        "document": run.document_name,
        "pack": run.pack_id,
        "run_date": run.run_date.isoformat(),
        "target_price_usd": run.target_price_usd,
        "refused": run.refused,
        "contributing_rule_ids": run.contributing_rule_ids,
        "findings": [f.to_json_dict() for f in run.findings],
    }


def test_greyrock_fixture_exists_and_is_marked_synthetic():
    assert GREYROCK_FIXTURE.exists(), "fixture #1 missing (handoff rule 3)"
    assert "SYNTHETIC" in GREYROCK_FIXTURE.name


def test_greyrock_minimum_required_findings(greyrock_run):
    """The §12 P1-B ACCEPT list, asserted explicitly and independently of
    the golden file so a careless regeneration cannot weaken the gate."""
    run = greyrock_run
    assert run.refused is False
    by_rule = {f.jurisdiction_basis: f for f in run.findings}

    fee = by_rule["CO-LAR-BDB-FEE-001"]
    assert (fee.category, fee.severity) == ("fee", "warn")
    assert "3%" in fee.found

    scope = by_rule["CO-LAR-BDB-SCOPE-001"]
    assert (scope.category, scope.severity) == ("scope", "flag")

    backstop = by_rule["CO-LAR-BDB-BACKSTOP-001"]
    assert (backstop.category, backstop.severity) == ("backstop", "flag")
    assert backstop.exposure_usd == 21_000  # 3% x $700,000

    default_trap = by_rule["CO-LAR-BDB-DEFAULT-001"]
    assert (default_trap.category, default_trap.severity) == ("default_trap", "flag")

    # Findings-only mode (§8 blocking gate): nothing generative, ever.
    assert all(f.suggested_template is None for f in run.findings)
    assert all(f.requires_human_review is True for f in run.findings)


def test_greyrock_golden_file(greyrock_run):
    actual = _run_payload(greyrock_run)
    if os.environ.get("HEARTH_UPDATE_GOLDEN") == "1":  # pragma: no cover
        GOLDEN.write_text(
            json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected, (
        "Grey Rock output drifted from golden file. If the change is "
        "deliberate, regenerate with HEARTH_UPDATE_GOLDEN=1 and review the diff."
    )


def test_exposure_absent_without_target_price():
    """No --target-price => exposure_usd None, never a fabricated number
    (§6: no advice past the data)."""
    loaded = load_pack("CO-Larimer")
    run = scrub_document(GREYROCK_FIXTURE, loaded.pack, run_date=RUN_DATE)
    by_rule = {f.jurisdiction_basis: f for f in run.findings}
    assert by_rule["CO-LAR-BDB-BACKSTOP-001"].exposure_usd is None
    assert len(run.findings) == 4
