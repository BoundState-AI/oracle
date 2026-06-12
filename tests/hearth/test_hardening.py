"""Hardening regression tests from the Phase-1 adversarial review
(spec v0.3 §3.3 fail-closed, §6 integrity, §12 P1-D)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hearth.cli import build_parser
from hearth.core.scrubber.engine import scrub_document
from hearth.core.scrubber.extraction import MAX_DOCUMENT_BYTES

from .conftest import RUN_DATE, make_pack, make_rule


def test_cli_rejects_zero_and_negative_target_price(capsys):
    parser = build_parser()
    for bad in ("0", "-5"):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["scrub", "doc.txt", "--pack", "CO-Larimer",
                               "--target-price", bad])
        assert excinfo.value.code == 2
    assert "positive integer" in capsys.readouterr().err


def test_duplicate_rule_ids_rejected():
    rule = make_rule(
        "CO-TEST-DUP-001",
        "form",
        {
            "summary": "dup",
            "detection": {"type": "clause_regex", "all_of": ["x"]},
            "finding": {
                "category": "scope",
                "severity": "info",
                "default_analysis": "n/a",
                "exposure": None,
            },
        },
    )
    with pytest.raises(ValidationError, match="duplicate rule_ids"):
        make_pack([rule, dict(rule)])


def test_oversized_document_refuses(fee_rule_pack, tmp_path):
    """A multi-gigabyte 'contract' is the wrong file or an attack; either
    way the answer is a refusal, not an OOM. Sparse file keeps this fast."""
    doc = tmp_path / "huge.txt"
    with doc.open("wb") as handle:
        handle.seek(MAX_DOCUMENT_BYTES + 1)
        handle.write(b"\0")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    assert run.refused is True
    assert run.findings[0].severity == "refuse"
    assert "limit" in run.findings[0].default_analysis


def test_uppercase_extension_still_parses(fee_rule_pack, tmp_path):
    doc = tmp_path / "SHOUTY.TXT"
    doc.write_text("1. COMPENSATION. The Success Fee is 3% of the price.",
                   encoding="utf-8")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    assert run.refused is False
    assert [f.category for f in run.findings] == ["fee"]
