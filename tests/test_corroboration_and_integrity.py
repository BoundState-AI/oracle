"""Tests for vendor-corroboration annotation (A6) and referee ID integrity (A7)."""
from __future__ import annotations

from oracle.cli import _corroboration_note, format_findings_report
from oracle.oracle2 import OracleSession, ReviewRound, compute_metrics


def _session(rounds: list[ReviewRound]) -> OracleSession:
    return OracleSession(
        session_id="t", document_path="t.md",
        original_draft="d", canonical_draft="d",
        rounds=rounds, converged=True,
        convergence_reason="locked", consensus_type="full_agreement",
    )


def test_same_vendor_corroboration_is_annotated_as_weaker():
    # Fran and Codex both run on the openai provider in the roster.
    note = _corroboration_note(["Fran", "Codex"])

    assert note is not None
    assert "same-vendor" in note
    assert "weaker" in note


def test_cross_vendor_corroboration_is_annotated():
    note = _corroboration_note(["Fran", "Gemini"])

    assert note is not None
    assert "cross-vendor" in note


def test_single_source_has_no_corroboration_note():
    assert _corroboration_note(["Fran"]) is None


def test_report_header_discloses_vendor_diversity(tmp_path):
    session = _session([
        ReviewRound(round_number=1, normalized_issues={"normalized_issues": []},
                    coordinator_decisions={"revision_decisions": []}, valid=True)
    ])

    report = format_findings_report(session, pack_dir=tmp_path)

    assert "**Reviewer pool:**" in report
    assert "share openai" in report  # Fran + Codex


def test_report_annotates_same_vendor_issue_sources(tmp_path):
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={"normalized_issues": [
                {
                    "issue_id": "R1-ISSUE-001",
                    "title": "Corroborated issue",
                    "severity": "high",
                    "merged_from": [{"oracle": "Fran"}, {"oracle": "Codex"}],
                }
            ]},
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )
    ]

    report = format_findings_report(_session(rounds), pack_dir=tmp_path)

    assert "**Corroboration:** same-vendor" in report


def test_dangling_decision_ids_surface_in_metrics_and_report(tmp_path):
    rounds = [
        ReviewRound(
            round_number=1,
            normalized_issues={"normalized_issues": [
                {"issue_id": "R1-ISSUE-001", "title": "t", "severity": "high"}
            ]},
            coordinator_decisions={"revision_decisions": [
                {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"},
                {"issue_id": "R1-ISSUE-999", "decision": "accepted_defect", "reason": "r"},
            ]},
            valid=True,
        )
    ]
    session = _session(rounds)

    metrics = compute_metrics(session)
    report = format_findings_report(session, pack_dir=tmp_path)

    assert metrics["dangling_decision_ids"] == ["R1-ISSUE-999"]
    assert "## Data Integrity Warnings" in report
    assert "R1-ISSUE-999" in report


def test_issue_id_continuity_measures_referee_reuse():
    def _round(number: int, ids: list[str]) -> ReviewRound:
        return ReviewRound(
            round_number=number,
            normalized_issues={"normalized_issues": [
                {"issue_id": i, "title": i, "severity": "medium"} for i in ids
            ]},
            coordinator_decisions={"revision_decisions": []},
            valid=True,
        )

    # Round 2 keeps 1 of its 2 IDs from round 1 -> continuity 0.5
    session = _session([
        _round(1, ["R1-ISSUE-001", "R1-ISSUE-002"]),
        _round(2, ["R1-ISSUE-001", "R2-ISSUE-003"]),
    ])

    metrics = compute_metrics(session)

    assert metrics["issue_id_continuity"] == 0.5


def test_issue_id_continuity_is_none_when_unmeasurable():
    session = _session([
        ReviewRound(round_number=1, normalized_issues={"normalized_issues": []},
                    coordinator_decisions={"revision_decisions": []}, valid=True)
    ])

    assert compute_metrics(session)["issue_id_continuity"] is None
