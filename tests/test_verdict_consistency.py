"""Tests for reviewer-verdict consistency checks on consensus claims (AUDIT A3)."""
from __future__ import annotations

from oracle.cli import format_findings_report
from oracle.oracle2 import (
    OracleSession,
    ReviewRound,
    _apply_verdict_consistency,
)


def _round_with_verdicts(verdicts: dict[str, str]) -> ReviewRound:
    return ReviewRound(
        round_number=1,
        reviewer_outputs={
            name: {"oracle_name": name, "overall_verdict": verdict, "findings": []}
            for name, verdict in verdicts.items()
        },
        normalized_issues={"normalized_issues": []},
        coordinator_decisions={"revision_decisions": []},
        valid=True,
    )


def test_unanimous_major_revision_hard_blocks_consensus():
    round_ = _round_with_verdicts({
        "Fran": "major_revision",
        "Codex": "major_revision",
        "Grok": "major_revision",
        "Gemini": "major_revision",
    })
    converged, consensus_type, reason = _apply_verdict_consistency(
        round_, True, "full_agreement", "Beth recommended LOCK"
    )
    assert converged is False
    assert consensus_type == "blocked"
    assert "major_revision" in reason
    assert "human review" in reason


def test_partial_major_revision_discloses_override_but_keeps_consensus():
    round_ = _round_with_verdicts({
        "Fran": "major_revision",
        "Codex": "revise",
        "Grok": "approve_with_minor_changes",
        "Gemini": "revise",
    })
    converged, consensus_type, reason = _apply_verdict_consistency(
        round_, True, "full_agreement", "Beth recommended LOCK"
    )
    assert converged is True
    assert consensus_type == "stable_with_notes"
    assert "Fran" in reason
    assert "overridden" in reason


def test_no_major_revision_verdicts_leave_consensus_untouched():
    round_ = _round_with_verdicts({
        "Fran": "revise",
        "Codex": "revise",
        "Grok": "approve_with_minor_changes",
        "Gemini": "revise",
    })
    converged, consensus_type, reason = _apply_verdict_consistency(
        round_, True, "full_agreement", "Beth recommended LOCK"
    )
    assert converged is True
    assert consensus_type == "full_agreement"
    assert reason == "Beth recommended LOCK"


def test_missing_verdicts_prevent_unanimity_hard_block():
    """A reviewer that reported no verdict breaks unanimity — disclose only.

    Absence of a verdict is not a verdict; hard-blocking on incomplete
    data would let one malformed response veto a legitimate consensus.
    """
    round_ = ReviewRound(
        round_number=1,
        reviewer_outputs={
            "Fran": {"overall_verdict": "major_revision", "findings": []},
            "Codex": {"overall_verdict": "major_revision", "findings": []},
            "Grok": {"findings": []},  # no verdict reported
        },
        valid=True,
    )
    converged, consensus_type, reason = _apply_verdict_consistency(
        round_, True, "full_agreement", "r"
    )
    assert converged is True
    assert consensus_type == "stable_with_notes"
    assert "overridden" in reason


def test_non_consensus_outcomes_pass_through_unchanged():
    round_ = _round_with_verdicts({"Fran": "major_revision"})
    converged, consensus_type, reason = _apply_verdict_consistency(
        round_, False, "blocked", "already blocked"
    )
    assert (converged, consensus_type, reason) == (False, "blocked", "already blocked")


def test_report_shows_final_round_verdicts_and_override_warning(tmp_path):
    round_ = _round_with_verdicts({
        "Fran": "major_revision",
        "Codex": "revise",
    })
    session = OracleSession(
        session_id="t",
        document_path="t.md",
        original_draft="d",
        canonical_draft="d",
        rounds=[round_],
        converged=True,
        convergence_reason="locked",
        consensus_type="stable_with_notes",
    )

    report = format_findings_report(session, pack_dir=tmp_path)

    assert "## Reviewer Verdicts (final round)" in report
    assert "- **Fran**: major_revision" in report
    assert "- **Codex**: revise" in report
    assert "consensus was reported although Fran" in report
