"""Tests for malformed-response recovery flagging (_parse_json / _recover_truncated_json)."""
from __future__ import annotations

from oracle.cli import format_findings_report
from oracle.oracle2 import OracleSession, ReviewRound, _parse_json


def test_clean_json_response_is_not_flagged_as_recovered():
    text = '{"oracle_name": "Fran", "findings": [{"title": "t", "severity": "high"}]}'

    result = _parse_json(text, "Fran")

    assert result["findings"][0]["title"] == "t"
    assert "recovered_partial" not in result


def test_truncated_findings_array_is_salvaged_and_flagged():
    """A response cut mid-finding keeps the parseable findings and says so."""
    text = (
        '{\n'
        '  "oracle_name": "Fran",\n'
        '  "findings": [\n'
        '    {"title": "First finding", "severity": "high"},\n'
        '    {"title": "Second finding", "sev'
    )

    result = _parse_json(text, "Fran")

    assert [f["title"] for f in result["findings"]] == ["First finding"]
    assert result["recovered_partial"] is True
    assert "salvaged" in result["recovery_note"]
    assert "error" not in result


def test_truncated_beth_draft_is_salvaged_and_flagged():
    text = (
        '{"oracle_name": "Beth", "revision_decisions": [], '
        '"revised_draft": "# Spec\\nLine one\\nLine tw'
    )

    result = _parse_json(text, "Beth")

    assert result["revised_draft"].startswith("# Spec")
    assert result["recovered_partial"] is True


def test_unrecoverable_response_reports_error_not_recovery():
    result = _parse_json("{ this is not json at all", "Grok")

    assert result["error"] == "Malformed JSON, no recoverable content"
    assert "recovered_partial" not in result


def test_findings_report_discloses_degraded_rounds(tmp_path):
    """AUDIT B2: a partially recovered reviewer must be disclosed to readers."""
    rounds = [
        ReviewRound(
            round_number=1,
            reviewer_outputs={
                "Fran": {
                    "oracle_name": "Fran",
                    "findings": [{"title": "t", "severity": "high"}],
                    "recovered_partial": True,
                    "recovery_note": "salvaged {'findings': 1}",
                },
                "Codex": {"oracle_name": "Codex", "findings": []},
            },
            normalized_issues={"normalized_issues": []},
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )
    ]
    session = OracleSession(
        session_id="t",
        document_path="t.md",
        original_draft="d",
        canonical_draft="d",
        rounds=rounds,
        converged=True,
        convergence_reason="locked",
        consensus_type="full_agreement",
    )

    report = format_findings_report(session, pack_dir=tmp_path)

    assert "Degraded data" in report
    assert "Fran" in report
    assert "may be incomplete" in report
