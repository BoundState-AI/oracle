"""Tests for the oracle2 pipeline ID-integrity fixes (run 20260729-153932).

FIX-1: coordinator decision IDs must be a subset of normalized issue IDs —
       violations are repaired by reconstruction, never metric'd past.
FIX-2: issues carry stable lineage across rounds (ID reuse or recurrence_of).
FIX-3: metrics count every severity class the report body uses.
FIX-4: coordinator acceptance telemetry with per-run alerts.
"""
from __future__ import annotations

from oracle.cli import format_findings_report
from oracle.oracle2 import (
    BETH_MANUAL_SYNTHESIS_PROMPT,
    SONNET_REFEREE_PROMPT,
    OracleSession,
    ReviewRound,
    _assign_issue_lineage,
    _check_convergence,
    _reconcile_decision_ids,
    compute_metrics,
)


def _session(rounds: list[ReviewRound], converged: bool = True) -> OracleSession:
    return OracleSession(
        session_id="t", document_path="t.md",
        original_draft="d", canonical_draft="d",
        rounds=rounds, converged=converged,
        convergence_reason="locked", consensus_type="full_agreement",
    )


def _round(number: int, issues: list[dict], decisions: list[dict]) -> ReviewRound:
    return ReviewRound(
        round_number=number,
        normalized_issues={"normalized_issues": issues},
        coordinator_decisions={"revision_decisions": decisions},
        valid=True,
    )


# ---------------------------------------------------------------------------
# FIX-1 — decision-ID ⊆ issue-ID reconciliation
# ---------------------------------------------------------------------------

def test_reconcile_reconstructs_missing_issue_records():
    rr = _round(
        1,
        [{"issue_id": "R1-ISSUE-001", "title": "real", "severity": "high"}],
        [
            {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"},
            {"issue_id": "R1-ISSUE-010", "decision": "accepted_defect",
             "reason": "custodian bus factor"},
        ],
    )

    reconstructed = _reconcile_decision_ids(rr)

    assert reconstructed == ["R1-ISSUE-010"]
    issues = {i["issue_id"]: i for i in rr.normalized_issues["normalized_issues"]}
    assert issues["R1-ISSUE-010"]["reconstructed"] is True
    assert issues["R1-ISSUE-010"]["severity"] == "unknown"
    assert "custodian bus factor" in issues["R1-ISSUE-010"]["title"]
    # The real issue is untouched
    assert "reconstructed" not in issues["R1-ISSUE-001"]
    assert rr.normalized_issues["reconstructed_issue_ids"] == ["R1-ISSUE-010"]


def test_reconcile_is_noop_when_subset_invariant_holds():
    rr = _round(
        1,
        [{"issue_id": "R1-ISSUE-001", "title": "t", "severity": "high"}],
        [{"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"}],
    )

    assert _reconcile_decision_ids(rr) == []
    assert "reconstructed_issue_ids" not in rr.normalized_issues


def test_metrics_clean_after_reconciliation():
    """A reconciled round has no dangling IDs; the reconstructed acceptance
    lands in the unknown-severity bucket instead of vanishing."""
    rr = _round(
        1,
        [{"issue_id": "R1-ISSUE-001", "title": "t", "severity": "critical"}],
        [
            {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"},
            {"issue_id": "R1-ISSUE-010", "decision": "accepted_defect", "reason": "r"},
        ],
    )
    _reconcile_decision_ids(rr)

    metrics = compute_metrics(_session([rr]))

    assert metrics["dangling_decision_ids"] == []
    assert metrics["metrics_integrity"] == "ok"
    assert metrics["accepted_critical_count"] == 1
    assert metrics["accepted_unknown_count"] == 1
    assert metrics["reconstructed_issue_count"] == 1


def test_metrics_suppress_severity_counts_on_subset_violation():
    """An unreconciled (legacy) session must never emit severity counts the
    dangling decisions make unverifiable — n/a, not an understated number."""
    session = _session([
        _round(
            1,
            [{"issue_id": "R1-ISSUE-001", "title": "t", "severity": "critical"}],
            [
                {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"},
                {"issue_id": "R1-ISSUE-999", "decision": "accepted_defect", "reason": "r"},
            ],
        )
    ])

    metrics = compute_metrics(session)

    assert metrics["metrics_integrity"] == "id_subset_violation"
    assert metrics["accepted_critical_count"] is None
    assert metrics["accepted_high_count"] is None
    assert metrics["accepted_medium_count"] is None
    # Decision totals are counted from decisions alone and stay verifiable
    assert metrics["total_accepted_defects"] == 2


def test_report_discloses_suppression_and_reconstruction(tmp_path):
    reconciled = _round(
        1,
        [{"issue_id": "R1-ISSUE-001", "title": "t", "severity": "high"}],
        [
            {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"},
            {"issue_id": "R1-ISSUE-010", "decision": "accepted_defect", "reason": "r"},
        ],
    )
    _reconcile_decision_ids(reconciled)

    report = format_findings_report(_session([reconciled]), pack_dir=tmp_path)

    assert "## Data Integrity Warnings" in report
    assert "reconstructed by the" in report
    assert "R1-ISSUE-010" in report
    assert "[RECONSTRUCTED]" in report

    unreconciled = _session([
        _round(
            1,
            [{"issue_id": "R1-ISSUE-001", "title": "t", "severity": "high"}],
            [{"issue_id": "R1-ISSUE-999", "decision": "accepted_defect", "reason": "r"}],
        )
    ])
    report2 = format_findings_report(unreconciled, pack_dir=tmp_path)

    assert "suppressed" in report2
    assert "Accepted critical defects: n/a (suppressed" in report2


# ---------------------------------------------------------------------------
# FIX-2 — cross-round lineage
# ---------------------------------------------------------------------------

def test_lineage_carries_through_reuse_and_recurrence():
    r1 = _round(1, [{"issue_id": "R1-ISSUE-003", "title": "a", "severity": "high"}], [])
    _assign_issue_lineage([], r1)
    assert r1.normalized_issues["normalized_issues"][0]["lineage_id"] == "R1-ISSUE-003"

    r2 = _round(2, [
        {"issue_id": "R2-ISSUE-001", "title": "a again", "severity": "high",
         "recurrence_of": "R1-ISSUE-003"},
        {"issue_id": "R2-ISSUE-002", "title": "novel", "severity": "medium"},
    ], [])
    _assign_issue_lineage([r1], r2)
    issues2 = {i["issue_id"]: i for i in r2.normalized_issues["normalized_issues"]}
    assert issues2["R2-ISSUE-001"]["lineage_id"] == "R1-ISSUE-003"
    assert issues2["R2-ISSUE-002"]["lineage_id"] == "R2-ISSUE-002"

    # Round 3 reuses R2's ID — the lineage root must still be R1's ID
    r3 = _round(3, [
        {"issue_id": "R2-ISSUE-001", "title": "a still", "severity": "high"},
    ], [])
    _assign_issue_lineage([r1, r2], r3)
    assert r3.normalized_issues["normalized_issues"][0]["lineage_id"] == "R1-ISSUE-003"


def test_lineage_records_unresolved_parent_claim():
    r2 = _round(2, [
        {"issue_id": "R2-ISSUE-001", "title": "ghost", "severity": "medium",
         "recurrence_of": "R1-ISSUE-404"},
    ], [])

    _assign_issue_lineage([], r2)

    issue = r2.normalized_issues["normalized_issues"][0]
    assert issue["lineage_id"] == "R2-ISSUE-001"
    assert issue["lineage_unresolved_parent"] == "R1-ISSUE-404"


def test_convergence_stability_uses_lineage_not_raw_ids():
    """Renumbered-but-linked issues must not read as issue-set churn."""
    r1 = _round(1, [
        {"issue_id": "R1-ISSUE-001", "title": "a", "severity": "medium",
         "lineage_id": "R1-ISSUE-001"},
    ], [])
    r2 = _round(2, [
        {"issue_id": "R2-ISSUE-001", "title": "a again", "severity": "medium",
         "recurrence_of": "R1-ISSUE-001", "lineage_id": "R1-ISSUE-001"},
    ], [])
    session = _session([r1, r2], converged=False)

    stop, converged, consensus_type, reason = _check_convergence(session)

    assert stop and converged
    assert "unstable" not in reason


def test_prompts_require_recurrence_and_drop_signal():
    """The schema contracts the harness now enforces must be in the prompts."""
    assert "recurrence_of" in SONNET_REFEREE_PROMPT
    assert "recurrence_of" in BETH_MANUAL_SYNTHESIS_PROMPT
    assert "dropped_findings" in BETH_MANUAL_SYNTHESIS_PROMPT


# ---------------------------------------------------------------------------
# FIX-3 — full severity buckets
# ---------------------------------------------------------------------------

def test_metrics_count_medium_and_low_accepted_defects(tmp_path):
    session = _session([
        _round(
            1,
            [
                {"issue_id": "R1-ISSUE-001", "title": "c", "severity": "critical"},
                {"issue_id": "R1-ISSUE-002", "title": "m", "severity": "medium"},
                {"issue_id": "R1-ISSUE-003", "title": "l", "severity": "low"},
            ],
            [
                {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"},
                {"issue_id": "R1-ISSUE-002", "decision": "accepted_defect", "reason": "r"},
                {"issue_id": "R1-ISSUE-003", "decision": "accepted_defect", "reason": "r"},
            ],
        )
    ])

    metrics = compute_metrics(session)
    report = format_findings_report(session, pack_dir=tmp_path)

    assert metrics["accepted_medium_count"] == 1
    assert metrics["accepted_low_count"] == 1
    assert "Accepted medium defects: 1" in report
    assert "Accepted low defects: 1" in report


def test_manual_normalizer_drop_signal_measures_rates():
    """With Beth's dropped_findings wired through, the manual workflow's
    duplicate/unsupported rates are measured instead of permanently n/a."""
    rr = ReviewRound(
        round_number=1,
        reviewer_outputs={
            "Fran": {"findings": [{"title": "a"}, {"title": "b"}]},
        },
        normalized_issues={
            "oracle_name": "Beth",
            "role": "manual_normalizer",
            "normalized_issues": [],
            "dropped_findings": [
                {"oracle": "Fran", "title": "b", "reason": "duplicate"},
            ],
        },
        coordinator_decisions={"revision_decisions": []},
        valid=True,
    )

    metrics = compute_metrics(_session([rr]))

    assert metrics["duplicate_rate"] == 0.5
    assert metrics["unsupported_claim_rate"] == 0.0


# ---------------------------------------------------------------------------
# FIX-4 — coordinator telemetry
# ---------------------------------------------------------------------------

def _telemetry_session() -> OracleSession:
    # Fran+Gemini = cross-vendor (openai + gemini); Grok alone = single source
    return _session([
        _round(
            1,
            [
                {"issue_id": "R1-ISSUE-001", "title": "corroborated",
                 "severity": "critical",
                 "merged_from": [{"oracle": "Fran"}, {"oracle": "Gemini"}]},
                {"issue_id": "R1-ISSUE-002", "title": "solo critical",
                 "severity": "critical",
                 "merged_from": [{"oracle": "Grok"}]},
                {"issue_id": "R1-ISSUE-003", "title": "downgraded high",
                 "severity": "high",
                 "merged_from": [{"oracle": "Fran"}]},
            ],
            [
                {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"},
                {"issue_id": "R1-ISSUE-002", "decision": "accepted_defect", "reason": "r"},
                {"issue_id": "R1-ISSUE-003", "decision": "preference_only", "reason": "r"},
            ],
        )
    ])


def test_coordinator_telemetry_rates_and_corroboration_split():
    tel = compute_metrics(_telemetry_session())["coordinator_telemetry"]

    assert tel["decided_count"] == 3
    assert tel["acceptance_rate"] == 2 / 3
    assert tel["preference_only_rate"] == 1 / 3
    assert tel["accepted_cross_vendor_count"] == 1
    assert tel["accepted_single_source_count"] == 1
    # 1 of the 3 critical/high decisions was downgraded to preference_only
    assert tel["severe_downgrade_rate"] == 1 / 3


def test_coordinator_telemetry_per_reviewer_acceptance():
    tel = compute_metrics(_telemetry_session())["coordinator_telemetry"]

    per = tel["per_reviewer_acceptance"]
    assert per["Fran"] == {"decided": 2, "accepted": 1, "acceptance_rate": 0.5}
    assert per["Grok"] == {"decided": 1, "accepted": 1, "acceptance_rate": 1.0}


def test_coordinator_telemetry_alerts(tmp_path):
    session = _telemetry_session()
    tel = compute_metrics(session)["coordinator_telemetry"]

    # Single-reviewer critical accepted without corroboration must alert
    assert any("R1-ISSUE-002" in a for a in tel["alerts"])

    report = format_findings_report(session, pack_dir=tmp_path)
    assert "### Coordinator Telemetry" in report
    assert "Coordinator alert:" in report


def test_blanket_acceptance_alert_requires_full_slate():
    issues = [
        {"issue_id": f"R1-ISSUE-{n:03d}", "title": "t", "severity": "medium",
         "merged_from": [{"oracle": "Fran"}, {"oracle": "Gemini"}]}
        for n in range(1, 6)
    ]
    decisions = [
        {"issue_id": i["issue_id"], "decision": "accepted_defect", "reason": "r"}
        for i in issues
    ]
    session = _session([_round(1, issues, decisions)])

    tel = compute_metrics(session)["coordinator_telemetry"]

    assert any("100%" in a for a in tel["alerts"])
