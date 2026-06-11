"""Tests for vendor-outage handling: round-loop abort and deliverable refusal."""
from __future__ import annotations

from oracle import oracle2


def _reviewer_response(name: str) -> dict:
    return {
        "oracle_name": name,
        "role": "reviewer",
        "document_type": "spec",
        "overall_verdict": "revise",
        "findings": [],
        "top_3_must_fix": [],
    }


def test_run_review_aborts_after_consecutive_invalid_rounds(monkeypatch, tmp_path):
    """A TOTAL vendor outage must stop the loop early, not burn all rounds.

    (A single-vendor outage now salvages on degraded quorum — see
    tests/test_quorum_salvage.py. The abort path is for rounds below
    quorum.)
    """
    def fake_call_oracle(config, user_message):
        if config.name == "Beth":
            raise AssertionError("Beth must not be called when a round is below quorum")
        raise RuntimeError("simulated total vendor outage")

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="spec",
        max_rounds=4,
        output_dir=tmp_path,
        workflow="manual",
    )

    assert len(session.rounds) == 2, "Loop must abort after 2 consecutive invalid rounds"
    assert session.converged is False
    assert session.consensus_type == "blocked"
    assert "NOT fully reviewed" in session.convergence_reason


def test_run_review_recovers_when_outage_is_transient(monkeypatch, tmp_path):
    """A below-quorum round followed by a healthy one resets the abort counter."""
    round_counter = {"n": 0}

    def fake_call_oracle(config, user_message):
        if config.name == "Fran":
            round_counter["n"] += 1
        if config.name == "Beth":
            return {
                "oracle_name": "Beth",
                "role": "coordinator",
                "revision_decisions": [],
                "serious_issues": [],
                "feedback_themes": [],
                "architectural_risks_remaining": [],
                "revised_sections": [],
                "open_questions": [],
                "convergence_status": "converging",
                "recommendation": "LOCK",
                "recommendation_reason": "clean",
                "revised_draft": None,
            }
        # Round 1: every reviewer fails (below quorum). Round 2: healthy.
        if round_counter["n"] == 1:
            raise RuntimeError("transient total outage")
        return _reviewer_response(config.name)

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="spec",
        max_rounds=4,
        output_dir=tmp_path,
        workflow="manual",
    )

    assert session.converged is True
    assert len(session.rounds) == 2  # round 1 below quorum, round 2 valid + LOCK


def test_non_converged_run_always_has_a_reason(monkeypatch, tmp_path):
    """A run must never end with converged=False and an empty reason."""
    def fake_call_oracle(config, user_message):
        raise RuntimeError("everything is down")

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="spec",
        max_rounds=1,  # ends by exhaustion before the abort threshold
        output_dir=tmp_path,
        workflow="manual",
    )

    assert session.converged is False
    assert session.convergence_reason, "Failed run ended without explaining itself"
    assert session.consensus_type == "blocked"


def test_review_status_label_is_honest():
    """AUDIT F2: deliverable labels state the real outcome, no euphemisms."""
    import server

    class _Result:
        def __init__(self, converged: bool, consensus_type: str):
            self.converged = converged
            self.consensus_type = consensus_type

    assert server._review_status_label(_Result(True, "full_agreement")) == "Converged"
    assert "unresolved notes" in server._review_status_label(_Result(True, "stable_with_notes"))
    blocked = server._review_status_label(_Result(False, "blocked"))
    assert "NOT CONVERGED" in blocked
    incomplete = server._review_status_label(_Result(False, ""))
    assert "NOT CONVERGED" in incomplete
    assert "Maximum Reasoning" not in blocked + incomplete
