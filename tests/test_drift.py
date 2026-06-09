"""Tests for reviewer drift detection (abandoned findings without draft changes)."""
from __future__ import annotations

from oracle.drift import detect_drift
from oracle.oracle2 import OracleSession, ReviewRound


def _finding(title: str, severity: str = "critical", evidence: str = "") -> dict:
    return {"title": title, "severity": severity, "evidence": evidence}


def _round(number: int, findings_by_oracle: dict[str, list[dict]],
           revised_draft: str = "", valid: bool = True) -> ReviewRound:
    return ReviewRound(
        round_number=number,
        reviewer_outputs={
            name: {"oracle_name": name, "findings": findings}
            for name, findings in findings_by_oracle.items()
        },
        revised_draft=revised_draft,
        valid=valid,
    )


def _session(rounds: list[ReviewRound], draft: str) -> OracleSession:
    return OracleSession(
        session_id="t",
        document_path="t.md",
        original_draft=draft,
        canonical_draft=draft,
        rounds=rounds,
    )


def test_dropped_critical_with_no_revision_is_drift():
    draft = "The admin endpoint requires no authentication."
    rounds = [
        _round(1, {"Fran": [_finding("Admin endpoint lacks authentication")]}),
        _round(2, {"Fran": []}),
    ]

    events = detect_drift(_session(rounds, draft))

    assert len(events) == 1
    assert events[0].oracle == "Fran"
    assert "not revised" in events[0].reason


def test_dropped_finding_with_cited_text_unchanged_is_drift():
    evidence = "retries failed charges indefinitely"
    draft_v1 = f"# Spec\n\nThe service {evidence} and has a typo.\n"
    draft_v2 = f"# Spec\n\nThe service {evidence} and the typo is fixed.\n"
    rounds = [
        _round(
            1,
            {"Codex": [_finding("Unbounded retry", evidence=evidence)]},
            revised_draft=draft_v2,
        ),
        _round(2, {"Codex": []}),
    ]

    events = detect_drift(_session(rounds, draft_v1))

    assert len(events) == 1
    assert "unchanged" in events[0].reason


def test_dropped_finding_is_presumed_addressed_when_cited_text_changed():
    evidence = "retries failed charges indefinitely"
    draft_v1 = f"# Spec\n\nThe service {evidence}.\n"
    draft_v2 = "# Spec\n\nThe service retries at most 3 times with backoff.\n"
    rounds = [
        _round(
            1,
            {"Codex": [_finding("Unbounded retry", evidence=evidence)]},
            revised_draft=draft_v2,
        ),
        _round(2, {"Codex": []}),
    ]

    assert detect_drift(_session(rounds, draft_v1)) == []


def test_rephrased_finding_is_not_drift():
    draft = "The ingestion mode is unspecified."
    rounds = [
        _round(1, {"Fran": [_finding("Ingestion mode is undefined", "high")]}),
        _round(2, {"Fran": [_finding("Ingestion mode is still undefined", "high")]}),
    ]

    assert detect_drift(_session(rounds, draft)) == []


def test_dropped_low_severity_finding_is_not_drift():
    """Round-3+ prompts instruct dropping low-risk items — that is not drift."""
    draft = "Some spec text that never changes."
    rounds = [
        _round(1, {"Grok": [_finding("Minor naming nit", severity="low")]}),
        _round(2, {"Grok": []}),
    ]

    assert detect_drift(_session(rounds, draft)) == []


def test_invalid_rounds_are_skipped():
    draft = "Stable text."
    rounds = [
        _round(1, {"Fran": [_finding("Real issue")]}),
        _round(2, {"Fran": []}, valid=False),
        _round(3, {"Fran": [_finding("Real issue")]}),
    ]

    assert detect_drift(_session(rounds, draft)) == []
