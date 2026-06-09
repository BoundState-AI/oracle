"""Tests for oracle2_adapter session reconstruction across both workflows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle.oracle2_adapter import build_review_result, verify_session_dir


def _write(session_dir: Path, name: str, payload) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    data = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    (session_dir / name).write_text(data, encoding="utf-8")


def _write_summary(session_dir: Path, total_rounds: int, converged: bool) -> None:
    _write(session_dir, "session_summary.json", {
        "session_id": "test-session",
        "total_rounds": total_rounds,
        "converged": converged,
    })


def _manual_session(session_dir: Path) -> None:
    """A converged manual-workflow session with one accepted critical defect."""
    _write_summary(session_dir, total_rounds=1, converged=True)
    _write(session_dir, "final_draft.md", "# Revised\n")
    _write(session_dir, "round1_beth_normalized.json", {
        "oracle_name": "Beth",
        "role": "manual_normalizer",
        "normalized_issues": [
            {
                "issue_id": "BETH-R1-ISSUE-001",
                "title": "No failover region",
                "severity": "critical",
                "source_reviewers": ["Fran", "Codex"],
                "summary": "Regional outage loses telemetry.",
                "resolution": "Accepted; replication added.",
            }
        ],
    })
    _write(session_dir, "round1_beth_decisions.json", {
        "revision_decisions": [
            {
                "issue_id": "BETH-R1-ISSUE-001",
                "decision": "accepted_defect",
                "reason": "Real data-loss risk.",
            }
        ],
    })


def test_build_review_result_reads_manual_workflow_files(tmp_path):
    _manual_session(tmp_path)

    result = build_review_result(tmp_path)

    assert len(result.rounds) == 1
    issues = result.rounds[0].normalized_issues
    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].source_oracles == ["Fran", "Codex"]
    assert issues[0].core_problem == "Regional outage loses telemetry."
    assert issues[0].recommended_fix == "Accepted; replication added."
    assert result.metrics.accepted_by_severity == {"critical": 1}


def test_build_review_result_reads_ledger_workflow_files(tmp_path):
    _write_summary(tmp_path, total_rounds=1, converged=True)
    _write(tmp_path, "final_draft.md", "# Revised\n")
    _write(tmp_path, "round1_sonnet_normalized.json", {
        "normalized_issues": [
            {
                "issue_id": "R1-ISSUE-001",
                "title": "Ambiguous ingestion mode",
                "severity": "high",
                "category": "ambiguity",
                "merged_from": [{"oracle": "Fran", "title": "x"}],
                "core_problem": "Batch vs streaming undecided.",
                "best_evidence": "Events are ingested",
                "recommended_fix": "Pick one.",
            }
        ],
    })
    _write(tmp_path, "round1_beth_decisions.json", {
        "revision_decisions": [
            {"issue_id": "R1-ISSUE-001", "decision": "accepted_defect", "reason": "r"}
        ],
    })

    result = build_review_result(tmp_path)

    issues = result.rounds[0].normalized_issues
    assert issues[0].source_oracles == ["Fran"]
    assert issues[0].evidence_text == "Events are ingested"
    assert result.metrics.accepted_by_severity == {"high": 1}


def test_converged_session_without_normalized_files_raises(tmp_path):
    """AUDIT F1: convergence with zero normalized files = adapter out of sync."""
    _write_summary(tmp_path, total_rounds=2, converged=True)
    _write(tmp_path, "final_draft.md", "# Draft\n")

    with pytest.raises(ValueError, match="out of sync"):
        build_review_result(tmp_path)


def test_failed_session_without_normalized_files_is_tolerated(tmp_path):
    """A run where every round was invalid has no files — that is honest."""
    _write_summary(tmp_path, total_rounds=2, converged=False)
    _write(tmp_path, "final_draft.md", "# Unreviewed input\n")

    result = build_review_result(tmp_path)

    assert result.rounds == []
    assert result.converged is False


def test_accepted_defect_with_unmatched_issue_id_counts_as_unknown(tmp_path):
    """A dangling decision ID must surface as unknown, not be minted medium."""
    _manual_session(tmp_path)
    _write(tmp_path, "round1_beth_decisions.json", {
        "revision_decisions": [
            {"issue_id": "DANGLING-ID", "decision": "accepted_defect", "reason": "r"}
        ],
    })

    result = build_review_result(tmp_path)

    assert result.metrics.accepted_by_severity == {"unknown": 1}


def test_verify_session_dir_accepts_manual_workflow_files(tmp_path):
    _manual_session(tmp_path)

    errors = verify_session_dir(tmp_path)

    assert errors == []
