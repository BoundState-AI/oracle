"""Tests for Oracle manual workflow orchestration."""
from __future__ import annotations

from pathlib import Path

from oracle import oracle2


def _reviewer_response(name: str) -> dict:
    return {
        "oracle_name": name,
        "role": "reviewer",
        "document_type": "spec",
        "overall_verdict": "revise",
        "findings": [
            {
                "title": f"{name} finding",
                "severity": "high",
                "category": "feasibility",
                "location": "Section 1",
                "evidence": "example",
                "problem": "missing edge case",
                "why_it_matters": "it can fail",
                "proposed_fix": "define the edge case",
                "confidence": 0.9,
            }
        ],
        "top_3_must_fix": [f"{name} finding"],
    }


def test_manual_workflow_sends_raw_reviews_to_beth_and_skips_sonnet(
    monkeypatch,
    tmp_path: Path,
):
    calls: list[str] = []

    def fake_call_oracle(config, user_message):
        calls.append(config.name)
        if config.name == "Sonnet":
            raise AssertionError("manual workflow must not call Sonnet")
        if config.name == "Beth":
            assert "## Blind Review Bundle" in user_message
            assert "### Fran" in user_message
            assert "### Gemini" not in user_message
            return {
                "oracle_name": "Beth",
                "role": "coordinator",
                "revision_decisions": [
                    {
                        "issue_id": "BETH-R1-ISSUE-001",
                        "decision": "accepted_defect",
                        "reason": "real issue",
                    }
                ],
                "serious_issues": [
                    {
                        "issue_id": "BETH-R1-ISSUE-001",
                        "title": "Define edge case",
                        "severity": "high",
                        "source_reviewers": ["Fran"],
                        "summary": "The spec needs an edge case.",
                        "resolution": "Added it.",
                    }
                ],
                "feedback_themes": ["feasibility"],
                "architectural_risks_remaining": [],
                "revised_sections": ["Section 1"],
                "open_questions": [],
                "convergence_status": "converging",
                "recommendation": "LOCK",
                "recommendation_reason": "serious issue resolved",
                "revised_draft": "revised spec",
            }
        return _reviewer_response(config.name)

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="initial spec",
        document_path="spec.md",
        max_rounds=4,
        output_dir=tmp_path,
        workflow="manual",
    )

    assert session.converged is True
    assert session.convergence_reason == "serious issue resolved"
    assert session.canonical_draft == "revised spec"
    assert "Sonnet" not in calls
    assert calls.count("Beth") == 1
    assert {name for name in calls if name != "Beth"} == {"Fran", "Codex", "Grok"}
    assert (tmp_path / "round1_beth_normalized.json").exists()


def test_manual_workflow_continues_on_one_more_round_then_locks(
    monkeypatch,
    tmp_path: Path,
):
    beth_calls = 0

    def fake_call_oracle(config, user_message):
        nonlocal beth_calls
        if config.name != "Beth":
            return _reviewer_response(config.name)

        beth_calls += 1
        recommendation = "ONE_MORE_ROUND" if beth_calls == 1 else "LOCK"
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
            "recommendation": recommendation,
            "recommendation_reason": recommendation.lower(),
            "revised_draft": f"draft round {beth_calls}",
        }

    monkeypatch.setattr(oracle2, "call_oracle", fake_call_oracle)

    session = oracle2.run_review(
        draft="initial spec",
        max_rounds=4,
        output_dir=tmp_path,
        workflow="manual",
    )

    assert session.converged is True
    assert len(session.rounds) == 2
    assert session.canonical_draft == "draft round 2"

