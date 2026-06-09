"""Tests for metrics honesty — unmeasured rates report as None/n-a, never 0.0."""
from __future__ import annotations

from oracle.cli import format_findings_report
from oracle.oracle2 import OracleSession, ReviewRound, compute_metrics


def _session(rounds: list[ReviewRound], consensus_type: str = "full_agreement") -> OracleSession:
    return OracleSession(
        session_id="t",
        document_path="t.md",
        original_draft="d",
        canonical_draft="d",
        rounds=rounds,
        converged=True,
        convergence_reason="locked",
        consensus_type=consensus_type,
    )


def test_manual_workflow_rates_are_none_not_zero():
    """AUDIT D3: the manual workflow has no drop signal — rates are unmeasured."""
    rounds = [
        ReviewRound(
            round_number=1,
            reviewer_outputs={"Fran": {"findings": [{"title": "t", "severity": "low"}]}},
            # Manual workflow shape: no dropped_findings key at all
            normalized_issues={"normalized_issues": []},
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )
    ]

    metrics = compute_metrics(_session(rounds))

    assert metrics["duplicate_rate"] is None
    assert metrics["unsupported_claim_rate"] is None


def test_ledger_workflow_rates_are_measured():
    rounds = [
        ReviewRound(
            round_number=1,
            reviewer_outputs={
                "Fran": {"findings": [{"title": "a", "severity": "low"}]},
                "Codex": {"findings": [{"title": "b", "severity": "low"}]},
            },
            normalized_issues={
                "normalized_issues": [],
                "dropped_findings": [
                    {"oracle": "Codex", "title": "b", "reason": "duplicate"}
                ],
            },
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )
    ]

    metrics = compute_metrics(_session(rounds))

    assert metrics["duplicate_rate"] == 0.5
    assert metrics["unsupported_claim_rate"] == 0.0


def test_report_prints_na_for_unmeasured_duplicate_rate(tmp_path):
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={"normalized_issues": []},
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )
    ]

    report = format_findings_report(_session(rounds), pack_dir=tmp_path)

    assert "Duplicate rate: n/a (not measured in this workflow)" in report
    assert "Duplicate rate: 0.0%" not in report


def test_metrics_include_consensus_type():
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={"normalized_issues": []},
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )
    ]

    metrics = compute_metrics(_session(rounds, consensus_type="stable_with_notes"))

    assert metrics["consensus_type"] == "stable_with_notes"
