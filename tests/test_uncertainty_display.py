"""Tests for uncertainty signal display — confidence and the speculative flag (AUDIT A9)."""
from __future__ import annotations

from oracle.cli import format_findings_report
from oracle.oracle2 import (
    OracleConfig,
    OracleSession,
    ReviewRound,
    _openai_reviewer_response_format,
)


def test_strict_schema_now_permits_and_requires_speculative_flag():
    """The contract demands marking speculative concerns; the strict schema
    previously forbade the marker (additionalProperties: false)."""
    config = OracleConfig(
        name="Fran", role="adversarial_logic", provider="openai",
        model="gpt-5.4", system_prompt="p",
    )

    schema = _openai_reviewer_response_format(config)
    finding_schema = schema["json_schema"]["schema"]["properties"]["findings"]["items"]

    assert finding_schema["properties"]["speculative"] == {"type": "boolean"}
    assert "speculative" in finding_schema["required"]


def _session_with_issue(issue: dict, decision: dict | None = None) -> OracleSession:
    return OracleSession(
        session_id="t", document_path="t.md",
        original_draft="d", canonical_draft="d",
        rounds=[ReviewRound(
            round_number=1,
            normalized_issues={"normalized_issues": [issue]},
            coordinator_decisions={"revision_decisions": [decision] if decision else []},
            valid=True,
        )],
        converged=True, convergence_reason="locked", consensus_type="full_agreement",
    )


def test_report_renders_confidence_and_speculative_marker(tmp_path):
    issue = {
        "issue_id": "R1-ISSUE-001",
        "title": "Possible scaling wall",
        "severity": "medium",
        "confidence": 0.35,
        "speculative": True,
    }

    report = format_findings_report(_session_with_issue(issue), pack_dir=tmp_path)

    assert "[SPECULATIVE] Possible scaling wall" in report
    assert "**Confidence (as reported):** 0.35" in report


def test_dissent_summary_shows_uncertainty_signals(tmp_path):
    issue = {
        "issue_id": "R1-ISSUE-001",
        "title": "Disputed claim",
        "severity": "high",
        "confidence": 0.4,
        "speculative": True,
        "source_reviewers": ["Grok"],
    }
    decision = {
        "issue_id": "R1-ISSUE-001",
        "decision": "rejected_claim",
        "reason": "Low-confidence speculation.",
    }

    report = format_findings_report(
        _session_with_issue(issue, decision), pack_dir=tmp_path
    )

    assert "confidence (as reported): 0.40" in report
    assert "marked SPECULATIVE by reviewer" in report


def test_report_omits_uncertainty_lines_when_absent(tmp_path):
    issue = {"issue_id": "R1-ISSUE-001", "title": "Plain issue", "severity": "low"}

    report = format_findings_report(_session_with_issue(issue), pack_dir=tmp_path)

    assert "Confidence (as reported)" not in report
    assert "SPECULATIVE" not in report
