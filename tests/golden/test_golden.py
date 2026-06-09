"""Golden-case tests for the ORACLE consensus path (G1-G5).

These tests encode the DESIRED behavior agreed in the Phase 2 handoff,
not the current behavior. On first commit all five FAIL by design; each
subsequent fix commit flips exactly one green:

  G3 -> A2  convergence semantics (stable disagreement is not consensus)
  G4 -> F1  adapter/workflow filename sync + severity preservation
  G5 -> F2+C2  honest deliverables (refuse generation of unreviewed docs)
  G2 -> A1  dissent summary in the findings report
  G1 -> A3  unanimous reviewer major_revision hard-blocks coordinator LOCK
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import server
from oracle import cli as oracle_cli
from oracle import oracle2
from oracle.oracle2_adapter import build_review_result

from .conftest import load_fixture


def _run_fixture(install, fixture, output_dir: Path, max_rounds: int = 4):
    """Replay a fixture transcript through the real run_review loop."""
    install(fixture)
    return oracle2.run_review(
        draft=fixture["document"],
        document_path="golden.md",
        max_rounds=max_rounds,
        output_dir=output_dir,
        workflow=fixture["workflow"],
    )


def test_g1_unanimous_critical_blocks_lock(golden_oracle, tmp_path):
    """All four reviewers verdict major_revision; Beth says LOCK anyway.

    Desired: the run must NOT report convergence. A unanimous reviewer
    verdict cannot be silently overridden by one coordinator model —
    the session escalates to human review and says why.
    """
    fixture = load_fixture("g1_unanimous_critical")
    session = _run_fixture(golden_oracle, fixture, tmp_path)

    assert session.converged is False, (
        "Coordinator LOCK overrode a unanimous major_revision verdict "
        "but the session still reported convergence"
    )
    assert "major_revision" in session.convergence_reason, (
        "The convergence reason must disclose the overridden reviewer verdicts"
    )


def test_g2_disagreement_surfaces_or_rejected(golden_oracle, tmp_path):
    """A rejected critical claim and an unresolved question must reach the report.

    Desired: the findings report carries a Dissent Summary section with
    (a) the rejected claim, attributed to its source oracle, with Beth's
    FULL untruncated reasoning, and (b) the unresolved question.
    """
    fixture = load_fixture("g2_reviewer_disagreement")
    session = _run_fixture(golden_oracle, fixture, tmp_path)

    report = oracle_cli.format_findings_report(session, pack_dir=tmp_path)

    assert "## Dissent Summary" in report, (
        "Findings report has no Dissent Summary section — rejected and "
        "unresolved findings are not surfaced as dissent"
    )
    # The distinctive tail of Beth's rejection reason sits beyond the
    # 200-char truncation point — if truncation survives, this fails.
    assert "signed SLA addendum dated 2026-03-02" in report, (
        "Beth's rejection reasoning was truncated or omitted"
    )
    assert "Fran" in report, "Rejected claim lost its source-oracle attribution"
    assert "Should sessions be stateless tokens or server-side state?" in report, (
        "The unresolved question did not surface in the report"
    )


def test_g3_repeated_tradeoff_not_converged(golden_oracle, tmp_path):
    """Ledger workflow: the same open tradeoff repeats across two rounds.

    Desired: the loop stops (correct) but reports blocked-on-tradeoff,
    NOT convergence. A standing disagreement is the opposite of consensus.
    """
    fixture = load_fixture("g3_repeated_tradeoff")
    session = _run_fixture(golden_oracle, fixture, tmp_path)

    assert len(session.rounds) == 2, "Loop should stop once the tradeoff repeats"
    assert session.converged is False, (
        "A repeated unresolved tradeoff was reported as convergence"
    )
    assert "tradeoff" in session.convergence_reason.lower(), (
        "The stop reason must name the blocking tradeoff"
    )
    assert getattr(session, "consensus_type", "") == "blocked", (
        "Session must classify this outcome as blocked, not agreement"
    )


def test_g4_adapter_preserves_severity(golden_oracle, tmp_path):
    """An accepted CRITICAL defect must survive adapter reconstruction.

    Desired: build_review_result reads the manual workflow's session
    files (round*_beth_normalized.json) and reports the accepted defect
    at its true severity with source-oracle attribution intact.
    """
    fixture = load_fixture("g4_adapter_sync")
    session = _run_fixture(golden_oracle, fixture, tmp_path)
    assert session.converged is True  # sanity: the fixture run locks cleanly

    result = build_review_result(tmp_path)

    assert result.rounds, "Adapter reconstructed zero rounds from a valid session"
    issues = result.rounds[0].normalized_issues
    assert issues, (
        "Adapter found no normalized issues — manual workflow files "
        "(round*_beth_normalized.json) were not read"
    )
    assert result.metrics.accepted_by_severity.get("critical") == 1, (
        f"Accepted critical defect was downgraded: "
        f"accepted_by_severity={result.metrics.accepted_by_severity}"
    )
    assert any("Fran" in issue.source_oracles for issue in issues), (
        "Source-oracle attribution lost in adapter reconstruction"
    )


def test_g6_abandoned_finding_surfaces_as_drift(golden_oracle, tmp_path):
    """Fran drops a critical finding with no draft change between rounds.

    Desired: the findings report carries a drift disclosure naming the
    oracle and the abandoned finding (AUDIT A5). Report-only — the run's
    convergence outcome is untouched.
    """
    fixture = load_fixture("g6_reviewer_drift")
    session = _run_fixture(golden_oracle, fixture, tmp_path)

    report = oracle_cli.format_findings_report(session, pack_dir=tmp_path)

    assert "## Position Changes (Drift Watch)" in report, (
        "Abandoned critical finding produced no drift disclosure"
    )
    assert "Fran" in report
    assert "Admin endpoint lacks authentication" in report


def test_g5_outage_refuses_generation(golden_oracle, tmp_path):
    """Grok is down all run; every round is invalid; nothing was reviewed.

    Desired: the session explains the failure, and the server refuses to
    generate a polished deliverable from the unreviewed input instead of
    shipping it with a flattering subtitle.
    """
    fixture = load_fixture("g5_vendor_outage")
    output_dir = tmp_path / "session"
    output_dir.mkdir()
    session = _run_fixture(golden_oracle, fixture, output_dir, max_rounds=2)

    assert session.converged is False
    # Sanity: this is exactly the hazard — the "final draft" is the input.
    assert session.canonical_draft == fixture["document"]
    assert session.convergence_reason, (
        "A fully failed run must explain itself in convergence_reason"
    )

    review_result = build_review_result(output_dir)
    assert review_result.rounds == [], "No round produced valid data"

    session_id = "golden-g5-outage"
    server._sessions.pop(session_id, None)
    server._sessions[session_id] = {
        "session_id": session_id,
        "job_type": "review",
        "mode": "review",
        "original_name": "golden.md",
        "file_path": str(tmp_path / "golden.md"),
        "output_dir": str(output_dir),
        "review_result": review_result,
        "pack_names": [],
        "pack_parts": {},
        "log_messages": [],
        "status": "ready_to_generate",
        "error": None,
    }
    try:
        client = TestClient(server.app)

        generate = client.post(
            "/oracle/generate",
            json={"session_id": session_id, "approved": True},
        )
        assert generate.status_code == 409, (
            f"/oracle/generate must refuse a zero-valid-round session, "
            f"got {generate.status_code}"
        )

        download = client.get(f"/oracle/download/{session_id}/docx")
        assert download.status_code == 409, (
            f"docx download must refuse a zero-valid-round session, "
            f"got {download.status_code}"
        )
    finally:
        server._sessions.pop(session_id, None)
