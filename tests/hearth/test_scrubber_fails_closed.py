"""P1-B fail-closed contract — written BEFORE the scrubber per handoff
ground rule 2 (spec v0.3 §3.3, §6, §12 P1-B).

The scrubber FAILS CLOSED. An unparseable document is a `refuse` finding
with exit code 2 — never an empty success, never silence. A scrub that
fails OPEN (silently passes a document) is the cardinal failure mode
(§1.1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from hearth.core.scrubber.engine import scrub_document
from hearth.data import FAIL_CLOSED_BASIS

from .conftest import REPO_ROOT, RUN_DATE, make_pack, make_rule

EXIT_REFUSE = 2


def _assert_refusal(run, *, expect_in_reason: str | None = None):
    """A refusal is exactly one refuse finding, never an empty success."""
    assert run.refused is True
    assert len(run.findings) == 1, "refusal must be a single refuse finding"
    finding = run.findings[0]
    assert finding.severity == "refuse"
    assert finding.category == "integrity"
    assert finding.requires_human_review is True
    assert finding.jurisdiction_basis == FAIL_CLOSED_BASIS
    assert finding.suggested_template is None
    if expect_in_reason:
        assert expect_in_reason in finding.default_analysis.lower()


def test_missing_file_refuses(fee_rule_pack, tmp_path):
    run = scrub_document(
        tmp_path / "does_not_exist.txt", fee_rule_pack, run_date=RUN_DATE
    )
    _assert_refusal(run)


def test_empty_txt_refuses(fee_rule_pack, tmp_path):
    doc = tmp_path / "empty.txt"
    doc.write_text("", encoding="utf-8")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    _assert_refusal(run)


def test_whitespace_only_txt_refuses(fee_rule_pack, tmp_path):
    doc = tmp_path / "blank.txt"
    doc.write_text("   \n\n\t  \n", encoding="utf-8")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    _assert_refusal(run)


def test_undecodable_txt_refuses(fee_rule_pack, tmp_path):
    doc = tmp_path / "mojibake.txt"
    doc.write_bytes(b"\xff\xfe\x00garbage\x9c\x81")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    _assert_refusal(run)


def test_garbage_pdf_refuses(fee_rule_pack, tmp_path):
    doc = tmp_path / "broken.pdf"
    doc.write_bytes(b"%PDF-1.7\nthis is not actually a pdf body\x00\x01\x02")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    _assert_refusal(run)


def test_garbage_docx_refuses(fee_rule_pack, tmp_path):
    doc = tmp_path / "broken.docx"
    doc.write_bytes(b"PK\x03\x04 not a real docx archive")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    _assert_refusal(run)


def test_unsupported_extension_refuses(fee_rule_pack, tmp_path):
    doc = tmp_path / "spreadsheet.xlsx"
    doc.write_bytes(b"PK\x03\x04whatever")
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    _assert_refusal(run, expect_in_reason="unsupported")


def test_directory_instead_of_file_refuses(fee_rule_pack, tmp_path):
    run = scrub_document(tmp_path, fee_rule_pack, run_date=RUN_DATE)
    _assert_refusal(run)


def test_pack_with_no_executable_rules_refuses(tmp_path):
    # A pack whose every rule is a data_query landmine spec has nothing the
    # deterministic stage can execute against a document: refusing is the
    # only honest answer (fail closed, never a hollow "0 findings" pass).
    pack = make_pack(
        [
            make_rule(
                "CO-TEST-LM-001",
                "landmine",
                {
                    "summary": "metro district mills",
                    "detection": {"type": "data_query", "query": "mill_levy"},
                    "finding": {
                        "category": "deadline",
                        "severity": "warn",
                        "default_analysis": "n/a",
                        "exposure": None,
                    },
                },
            )
        ]
    )
    doc = tmp_path / "fine.txt"
    doc.write_text("1. A perfectly parseable clause.", encoding="utf-8")
    run = scrub_document(doc, pack, run_date=RUN_DATE)
    _assert_refusal(run, expect_in_reason="executable")


def test_no_rule_effective_on_run_date_refuses(fee_rule_pack, tmp_path):
    from datetime import date

    doc = tmp_path / "fine.txt"
    doc.write_text("1. COMPENSATION. The fee is 3% of the price.", encoding="utf-8")
    run = scrub_document(doc, fee_rule_pack, run_date=date(2020, 1, 1))
    _assert_refusal(run)


def test_exploding_analyzer_fails_closed(fee_rule_pack, tmp_path):
    """An unexpected internal error must refuse, not crash and not pass."""

    class ExplodingAnalyzer:
        def analyze(self, clauses, pack):
            raise RuntimeError("synthetic analyzer failure")

    doc = tmp_path / "fine.txt"
    doc.write_text("1. COMPENSATION. The fee is 3% of the price.", encoding="utf-8")
    run = scrub_document(
        doc, fee_rule_pack, run_date=RUN_DATE, analyzer=ExplodingAnalyzer()
    )
    _assert_refusal(run)


def test_parseable_document_is_not_refused(fee_rule_pack, tmp_path):
    """Fail-closed must not become fail-always: a clean parse scrubs."""
    doc = tmp_path / "fine.txt"
    doc.write_text(
        "1. COMPENSATION. Buyer agrees the Success Fee shall be 3% of the price.",
        encoding="utf-8",
    )
    run = scrub_document(doc, fee_rule_pack, run_date=RUN_DATE)
    assert run.refused is False
    assert [f.category for f in run.findings] == ["fee"]


# ---------------------------------------------------------------------------
# CLI-level contract: exit code 2, refusal rendered, audit trail persists.
# ---------------------------------------------------------------------------


def _run_cli(args: list[str], cwd) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run(
        [sys.executable, "-m", "hearth", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=120,
    )


def test_cli_missing_file_exits_2(tmp_path):
    result = _run_cli(
        ["scrub", "nope_not_here.txt", "--pack", "CO-Larimer"], cwd=tmp_path
    )
    assert result.returncode == EXIT_REFUSE, result.stdout + result.stderr
    assert "REFUSED" in result.stdout


def test_cli_garbage_pdf_exits_2_with_refuse_finding_and_audit(tmp_path):
    doc = tmp_path / "broken.pdf"
    doc.write_bytes(b"%PDF-1.7\n\x00\x01 not a pdf")
    out_json = tmp_path / "findings.json"
    result = _run_cli(
        [
            "scrub",
            str(doc),
            "--pack",
            "CO-Larimer",
            "--json",
            str(out_json),
            "--audit-dir",
            str(tmp_path / "audit"),
        ],
        cwd=tmp_path,
    )
    assert result.returncode == EXIT_REFUSE, result.stdout + result.stderr
    assert "REFUSED" in result.stdout

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["refused"] is True
    assert [f["severity"] for f in payload["findings"]] == ["refuse"]

    # §11: every run — including a refusal — leaves an audit artifact.
    artifacts = list((tmp_path / "audit").glob("*.json"))
    assert len(artifacts) == 1


def test_cli_unknown_pack_exits_2(tmp_path):
    doc = tmp_path / "fine.txt"
    doc.write_text("1. COMPENSATION. Fee is 3% of price.", encoding="utf-8")
    result = _run_cli(["scrub", str(doc), "--pack", "XX-Nowhere"], cwd=tmp_path)
    assert result.returncode == EXIT_REFUSE
    assert "REFUSED" in result.stdout


def test_cli_help_works():
    result = _run_cli(["scrub", "--help"], cwd=REPO_ROOT)
    assert result.returncode == 0
    assert "--pack" in result.stdout
