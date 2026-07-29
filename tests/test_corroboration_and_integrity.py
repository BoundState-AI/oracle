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


def _round_with_issues(number: int, issues: list[dict]) -> ReviewRound:
    return ReviewRound(
        round_number=number,
        normalized_issues={"normalized_issues": issues},
        coordinator_decisions={"revision_decisions": []},
        valid=True,
    )


def test_issue_id_continuity_counts_only_non_novel_issues():
    """FIX-2: a genuinely novel later-round issue must not drag continuity
    down — the old ID-set-overlap definition read 0% for every renumbering
    referee and therefore alerted on nothing."""
    session = _session([
        _round_with_issues(1, [
            {"issue_id": "R1-ISSUE-001", "title": "a", "severity": "medium"},
            {"issue_id": "R1-ISSUE-002", "title": "b", "severity": "medium"},
        ]),
        _round_with_issues(2, [
            # Reused ID -> non-novel, parent trivially resolved
            {"issue_id": "R1-ISSUE-001", "title": "a", "severity": "medium"},
            # No reuse, no recurrence claim -> novel, excluded from the metric
            {"issue_id": "R2-ISSUE-003", "title": "c", "severity": "medium"},
        ]),
    ])

    assert compute_metrics(session)["issue_id_continuity"] == 1.0


def test_issue_id_continuity_resolves_recurrence_links():
    """A renumbered issue linked via recurrence_of counts as continuous;
    a claimed parent that resolves to nothing counts against the metric."""
    session = _session([
        _round_with_issues(1, [
            {"issue_id": "R1-ISSUE-003", "title": "a", "severity": "high"},
        ]),
        _round_with_issues(2, [
            {"issue_id": "R2-ISSUE-001", "title": "a again", "severity": "high",
             "recurrence_of": "R1-ISSUE-003"},
            {"issue_id": "R2-ISSUE-002", "title": "ghost", "severity": "medium",
             "recurrence_of": "R1-ISSUE-999"},
        ]),
    ])

    assert compute_metrics(session)["issue_id_continuity"] == 0.5


def test_issue_id_continuity_is_none_when_all_later_issues_are_novel():
    session = _session([
        _round_with_issues(1, [
            {"issue_id": "R1-ISSUE-001", "title": "a", "severity": "medium"},
        ]),
        _round_with_issues(2, [
            {"issue_id": "R2-ISSUE-001", "title": "b", "severity": "medium"},
        ]),
    ])

    assert compute_metrics(session)["issue_id_continuity"] is None


def test_novel_issue_count_uses_lineage_roots():
    """Two sightings of one issue (linked by lineage_id) are one issue."""
    session = _session([
        _round_with_issues(1, [
            {"issue_id": "R1-ISSUE-001", "title": "a", "severity": "high",
             "lineage_id": "R1-ISSUE-001"},
        ]),
        _round_with_issues(2, [
            {"issue_id": "R2-ISSUE-001", "title": "a again", "severity": "high",
             "recurrence_of": "R1-ISSUE-001", "lineage_id": "R1-ISSUE-001"},
            {"issue_id": "R2-ISSUE-002", "title": "new", "severity": "medium",
             "lineage_id": "R2-ISSUE-002"},
        ]),
    ])

    assert compute_metrics(session)["novel_issue_count"] == 2


def test_issue_id_continuity_is_none_when_unmeasurable():
    session = _session([
        ReviewRound(round_number=1, normalized_issues={"normalized_issues": []},
                    coordinator_decisions={"revision_decisions": []}, valid=True)
    ])

    assert compute_metrics(session)["issue_id_continuity"] is None
