"""Banner policy render tests (spec v0.3 §8, §12 P1-C; DoD: provisional-
banner render test)."""

from __future__ import annotations

import subprocess
import sys
import os

from hearth.core.scrubber.engine import refusal_run, scrub_document
from hearth.packs.loader import load_pack
from hearth.utils.render import render_report

from .conftest import GREYROCK_FIXTURE, REPO_ROOT, RUN_DATE


def _greyrock_report() -> str:
    loaded = load_pack("CO-Larimer")
    run = scrub_document(
        GREYROCK_FIXTURE, loaded.pack, target_price_usd=700_000, run_date=RUN_DATE
    )
    return render_report(run, loaded.pack)


def test_legal_banner_always_present():
    report = _greyrock_report()
    assert "NOT LEGAL ADVICE" in report
    assert "NOT A LICENSED BROKERAGE" in report


def test_provisional_rules_render_with_provisional_banner():
    """P1-C ACCEPT: provisional rules render with provisional banner."""
    report = _greyrock_report()
    assert "PROVISIONAL BASIS: 4 of 4 findings" in report
    # Per-finding markers as well as the banner.
    assert report.count("(PROVISIONAL)") == 4
    assert report.count("[P]") == 4


def test_exposure_rendered_with_amount():
    report = _greyrock_report()
    assert "$21,000" in report
    assert "Target price: $700,000" in report


def test_refusal_renders_unmissably():
    run = refusal_run("nope.pdf", reason="synthetic refusal for render test")
    report = render_report(run, None)
    assert "SCRUB REFUSED" in report
    assert "FAILING CLOSED" in report
    assert "NOT LEGAL ADVICE" in report  # banner survives refusals too


def test_cli_renders_provisional_banner_end_to_end(tmp_path):
    """The banner reaches the actual CLI surface, not just the renderer."""
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hearth",
            "scrub",
            str(GREYROCK_FIXTURE),
            "--pack",
            "CO-Larimer",
            "--target-price",
            "700000",
            "--audit-dir",
            str(tmp_path / "audit"),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROVISIONAL BASIS" in result.stdout
    assert "$21,000" in result.stdout
    assert "audit artifact:" in result.stdout
