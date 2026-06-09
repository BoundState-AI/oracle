"""Tests for dissent fidelity in the findings report (Dissent Summary, drops, open questions)."""
from __future__ import annotations

from oracle.cli import format_findings_report
from oracle.oracle2 import OracleSession, ReviewRound


def _session_with_rounds(rounds: list[ReviewRound]) -> OracleSession:
    return OracleSession(
        session_id="test",
        document_path="test.md",
        original_draft="d",
        canonical_draft="d",
        rounds=rounds,
        converged=True,
        convergence_reason="locked",
        consensus_type="stable_with_notes",
    )


def test_dissent_summary_lists_rejected_claim_with_full_reason(tmp_path):
    long_reason = "Rejected because " + ("x" * 250) + " END-OF-REASON"
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={
                "normalized_issues": [
                    {
                        "issue_id": "BETH-R1-ISSUE-001",
                        "title": "Lossy failover",
                        "severity": "critical",
                        "source_reviewers": ["Fran"],
                    }
                ]
            },
            coordinator_decisions={
                "revision_decisions": [
                    {
                        "issue_id": "BETH-R1-ISSUE-001",
                        "decision": "rejected_claim",
                        "reason": long_reason,
                    }
                ],
                "open_questions": [],
            },
            valid=True,
        )
    ]

    report = format_findings_report(_session_with_rounds(rounds), pack_dir=tmp_path)

    assert "## Dissent Summary" in report
    assert "[REJECTED BY COORDINATOR] Lossy failover" in report
    assert "Fran" in report
    assert "END-OF-REASON" in report, "Coordinator reasoning must not be truncated"


def test_dissent_summary_marks_reviewer_conflicts(tmp_path):
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={
                "normalized_issues": [
                    {
                        "issue_id": "R1-ISSUE-001",
                        "title": "Disputed cache design",
                        "severity": "high",
                        "merged_from": [{"oracle": "Fran"}, {"oracle": "Grok"}],
                        "conflict_flag": True,
                    }
                ]
            },
            coordinator_decisions={
                "revision_decisions": [
                    {
                        "issue_id": "R1-ISSUE-001",
                        "decision": "unresolved_question",
                        "reason": "Reviewers directly disagree.",
                    }
                ],
            },
            valid=True,
        )
    ]

    report = format_findings_report(_session_with_rounds(rounds), pack_dir=tmp_path)

    assert "[UNRESOLVED QUESTION] Disputed cache design" in report
    assert "Direct conflict between reviewers" in report
    assert "Fran, Grok" in report


def test_referee_dropped_findings_are_listed(tmp_path):
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={
                "normalized_issues": [],
                "dropped_findings": [
                    {"oracle": "Grok", "title": "Speculative edge case", "reason": "unsupported"}
                ],
            },
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )
    ]

    report = format_findings_report(_session_with_rounds(rounds), pack_dir=tmp_path)

    assert "## Findings Dropped by Referee" in report
    assert "Speculative edge case" in report
    assert "unsupported" in report


def test_open_questions_come_from_last_valid_round(tmp_path):
    """AUDIT A10: the final round's open questions are the live dissent."""
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={"normalized_issues": []},
            coordinator_decisions={
                "revision_decisions": [],
                "open_questions": ["Stale round-1 question?"],
            },
            valid=True,
        ),
        ReviewRound(
            round_number=2,
            normalized_issues={"normalized_issues": []},
            coordinator_decisions={
                "revision_decisions": [],
                "open_questions": ["Fresh round-2 question?"],
            },
            valid=True,
        ),
    ]

    report = format_findings_report(_session_with_rounds(rounds), pack_dir=tmp_path)

    assert "Fresh round-2 question?" in report
    assert "Stale round-1 question?" not in report


def test_report_without_dissent_has_no_dissent_section(tmp_path):
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={"normalized_issues": []},
            coordinator_decisions={
                "revision_decisions": [
                    {"issue_id": "X", "decision": "accepted_defect", "reason": "r"}
                ],
            },
            valid=True,
        )
    ]

    report = format_findings_report(_session_with_rounds(rounds), pack_dir=tmp_path)

    assert "## Dissent Summary" not in report
