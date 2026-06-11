"""Tests for live-eval scoring functions (no API access — pure scoring logic)."""
from __future__ import annotations

from eval.live.scoring import (
    collect_raised_issues,
    collect_surfaced_issues,
    defect_matches,
    score_detection,
    score_false_positives,
    score_retention,
)
from oracle.oracle2 import OracleSession, ReviewRound


def _expected(keywords: list[str], min_severity: str = "high") -> dict:
    return {"id": "D1", "required_keywords": keywords, "min_severity": min_severity}


def test_defect_matches_requires_all_keywords():
    issue = {"title": "Admin endpoint lacks authentication", "severity": "critical"}

    assert defect_matches(_expected(["admin", "authentication"]), issue) is True
    assert defect_matches(_expected(["admin", "idempotency"]), issue) is False


def test_defect_matches_enforces_severity_floor():
    issue = {"title": "Missing idempotency key", "severity": "medium"}

    assert defect_matches(_expected(["idempotency"], "high"), issue) is False
    assert defect_matches(_expected(["idempotency"], "medium"), issue) is True


def test_defect_matches_searches_problem_and_evidence_fields():
    issue = {
        "title": "Charging weakness",
        "severity": "high",
        "core_problem": "No idempotency contract on the charge API.",
    }

    assert defect_matches(_expected(["idempotency"]), issue) is True


def test_score_detection_splits_detected_and_missed():
    expected = [
        {"id": "D-AUTH", "required_keywords": ["authentication"], "min_severity": "high"},
        {"id": "D-ROLLBACK", "required_keywords": ["rollback"], "min_severity": "high"},
    ]
    issues = [{"title": "No authentication on admin", "severity": "critical"}]

    result = score_detection(expected, issues)

    assert result["detected"] == ["D-AUTH"]
    assert result["missed"] == ["D-ROLLBACK"]
    assert result["detection_rate"] == 0.5


def test_score_false_positives_counts_critical_and_high_only():
    issues = [
        {"title": "a", "severity": "critical"},
        {"title": "b", "severity": "high"},
        {"title": "c", "severity": "medium"},
        {"title": "d", "severity": "low"},
    ]

    result = score_false_positives(issues, max_critical_high=1)

    assert result["critical_high_count"] == 2
    assert result["within_budget"] is False


def _round(number: int, findings_by_oracle: dict[str, list[dict]],
           normalized: list[dict] | None = None, valid: bool = True) -> ReviewRound:
    return ReviewRound(
        round_number=number,
        reviewer_outputs={
            name: {"oracle_name": name, "findings": findings}
            for name, findings in findings_by_oracle.items()
        },
        normalized_issues={"normalized_issues": normalized or []},
        valid=valid,
    )


def _session(rounds: list[ReviewRound]) -> OracleSession:
    return OracleSession(
        session_id="t", document_path="t.md",
        original_draft="text", canonical_draft="text", rounds=rounds,
    )


def test_score_retention_reports_per_oracle_counts():
    rounds = [
        _round(1, {"Fran": [{"title": "a", "severity": "low"},
                            {"title": "b", "severity": "low"}]}),
        _round(2, {"Fran": [{"title": "a", "severity": "low"}]}),
    ]

    result = score_retention(_session(rounds))

    assert result["per_oracle"]["Fran"]["round1_findings"] == 2
    assert result["per_oracle"]["Fran"]["retention"] == 0.5


def test_collectors_separate_raised_from_surfaced():
    rounds = [
        _round(
            1,
            {"Fran": [{"title": "raised only", "severity": "high"}]},
            normalized=[{"issue_id": "I1", "title": "surfaced", "severity": "high"}],
        ),
        _round(2, {"Fran": [{"title": "invalid round", "severity": "high"}]}, valid=False),
    ]
    session = _session(rounds)

    raised = collect_raised_issues(session)
    surfaced = collect_surfaced_issues(session)

    assert [i["title"] for i in raised] == ["raised only"]
    assert [i["title"] for i in surfaced] == ["surfaced"]
