"""Tests for ledger-workflow convergence logic (_check_convergence)."""
from __future__ import annotations

from oracle.oracle2 import OracleSession, ReviewRound, _check_convergence


def _session(rounds: list[ReviewRound]) -> OracleSession:
    return OracleSession(
        session_id="test",
        document_path="test.md",
        original_draft="draft",
        canonical_draft="draft",
        rounds=rounds,
    )


def _round(
    number: int,
    issues: list[dict] | None = None,
    open_questions: list[str] | None = None,
    valid: bool = True,
) -> ReviewRound:
    return ReviewRound(
        round_number=number,
        normalized_issues={"normalized_issues": issues or []},
        coordinator_decisions={"open_questions": open_questions or []},
        valid=valid,
    )


def _issue(issue_id: str, severity: str, title: str = "t") -> dict:
    return {"issue_id": issue_id, "severity": severity, "title": title}


def test_check_convergence_single_round_does_not_stop():
    session = _session([_round(1)])
    stop, converged, consensus_type, reason = _check_convergence(session)
    assert stop is False
    assert converged is False
    assert "2 valid rounds" in reason


def test_check_convergence_invalid_rounds_are_skipped():
    # Two rounds exist but only one is valid — not enough to compare.
    session = _session([_round(1), _round(2, valid=False)])
    stop, converged, _, reason = _check_convergence(session)
    assert stop is False
    assert "2 valid rounds" in reason


def test_check_convergence_critical_findings_continue_loop():
    issues = [_issue("R1-ISSUE-001", "critical")]
    session = _session([_round(1, issues), _round(2, issues)])
    stop, converged, _, reason = _check_convergence(session)
    assert stop is False
    assert converged is False
    assert "critical" in reason


def test_check_convergence_two_high_findings_continue_loop():
    issues = [_issue("R1-ISSUE-001", "high"), _issue("R1-ISSUE-002", "high")]
    session = _session([_round(1, issues), _round(2, issues)])
    stop, converged, _, reason = _check_convergence(session)
    assert stop is False
    assert "high" in reason


def test_check_convergence_unstable_issue_set_continues_loop():
    prev = [_issue("R1-ISSUE-001", "medium")]
    curr = [_issue("R2-ISSUE-007", "medium")]  # 0% overlap
    session = _session([_round(1, prev), _round(2, curr)])
    stop, converged, _, reason = _check_convergence(session)
    assert stop is False
    assert "unstable" in reason.lower()


def test_check_convergence_repeated_tradeoff_stops_as_blocked_not_converged():
    """AUDIT A2: a standing disagreement must stop the loop WITHOUT consensus."""
    issues = [_issue("R1-ISSUE-001", "medium")]
    question = "Batch or streaming?"
    session = _session([
        _round(1, issues, open_questions=[question]),
        _round(2, issues, open_questions=[question]),
    ])
    stop, converged, consensus_type, reason = _check_convergence(session)
    assert stop is True
    assert converged is False
    assert consensus_type == "blocked"
    assert "tradeoff" in reason.lower()
    assert question in reason


def test_check_convergence_clean_pass_is_full_agreement():
    issues = [_issue("R1-ISSUE-001", "medium")]
    session = _session([_round(1, issues), _round(2, issues)])
    stop, converged, consensus_type, reason = _check_convergence(session)
    assert stop is True
    assert converged is True
    assert consensus_type == "full_agreement"


def test_check_convergence_one_high_finding_is_stable_with_notes():
    """AUDIT A4: converging with an outstanding high finding must say so."""
    issues = [_issue("R1-ISSUE-001", "high", title="Residual auth gap")]
    session = _session([_round(1, issues), _round(2, issues)])
    stop, converged, consensus_type, reason = _check_convergence(session)
    assert stop is True
    assert converged is True
    assert consensus_type == "stable_with_notes"
    assert "Residual auth gap" in reason


def test_check_convergence_all_issues_resolved_converges():
    prev = [_issue("R1-ISSUE-001", "medium")]
    session = _session([_round(1, prev), _round(2, issues=[])])
    stop, converged, consensus_type, _ = _check_convergence(session)
    assert stop is True
    assert converged is True
    assert consensus_type == "full_agreement"


def test_check_convergence_new_open_question_does_not_block():
    """A question seen only once is not yet a standing tradeoff."""
    issues = [_issue("R1-ISSUE-001", "medium")]
    session = _session([
        _round(1, issues, open_questions=[]),
        _round(2, issues, open_questions=["New question?"]),
    ])
    stop, converged, consensus_type, _ = _check_convergence(session)
    assert stop is True
    assert converged is True
    assert consensus_type == "stable_with_notes"
