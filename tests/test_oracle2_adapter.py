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


def test_converged_session_with_corrupt_normalized_file_raises(tmp_path):
    """AUDIT F1 extension: existence is not enough — the file must parse.

    A truncated round file in a converged session previously passed the
    existence guard and silently reported a clean review.
    """
    _write_summary(tmp_path, total_rounds=1, converged=True)
    _write(tmp_path, "final_draft.md", "# Draft\n")
    (tmp_path / "round1_sonnet_normalized.json").write_text(
        '{"normalized_issues": [{"issue_id": "R1-IS', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="out of sync"):
        build_review_result(tmp_path)


def test_converged_session_with_renamed_key_raises(tmp_path):
    """A future oracle2 renaming 'normalized_issues' must fail loudly."""
    _write_summary(tmp_path, total_rounds=1, converged=True)
    _write(tmp_path, "final_draft.md", "# Draft\n")
    _write(tmp_path, "round1_sonnet_normalized.json", {"issues_v2": []})

    with pytest.raises(ValueError, match="out of sync"):
        build_review_result(tmp_path)


def test_converged_session_with_zero_issues_is_legitimate(tmp_path):
    """An empty normalized_issues list with the key present is a real,
    clean result — not an out-of-sync signature."""
    _write_summary(tmp_path, total_rounds=1, converged=True)
    _write(tmp_path, "final_draft.md", "# Draft\n")
    _write(tmp_path, "round1_sonnet_normalized.json", {"normalized_issues": []})
    _write(tmp_path, "round1_revised_draft.md", "# Draft\n")

    result = build_review_result(tmp_path)
    assert result.converged is True
    assert result.metrics.total_issues_raised == 0


def test_duplicate_count_read_from_dropped_findings(tmp_path):
    _write_summary(tmp_path, total_rounds=1, converged=True)
    _write(tmp_path, "final_draft.md", "# Draft\n")
    _write(tmp_path, "round1_sonnet_normalized.json", {
        "normalized_issues": [{
            "issue_id": "R1-ISSUE-001",
            "title": "Thing",
            "severity": "high",
            "core_problem": "p",
            "recommended_fix": "f",
        }],
        "dropped_findings": [
            {"reason": "duplicate", "title": "dupe 1"},
            {"reason": "duplicate", "title": "dupe 2"},
            {"reason": "unsupported", "title": "weak"},
        ],
    })

    result = build_review_result(tmp_path)
    assert result.metrics.duplicate_count == 2


def test_rounds_to_stability_zero_when_never_unstable(tmp_path):
    """A review with no accepted critical/high issue is stable from the
    start — it must not report the maximum (len(rounds)) as before."""
    _write_summary(tmp_path, total_rounds=1, converged=True)
    _write(tmp_path, "final_draft.md", "# Draft\n")
    _write(tmp_path, "round1_sonnet_normalized.json", {
        "normalized_issues": [{
            "issue_id": "R1-ISSUE-001",
            "title": "Minor nit",
            "severity": "medium",
            "core_problem": "p",
            "recommended_fix": "f",
        }],
    })
    _write(tmp_path, "round1_beth_decisions.json", {
        "revision_decisions": [{
            "issue_id": "R1-ISSUE-001",
            "decision": "accepted_defect",
            "reason": "fair",
        }],
    })

    result = build_review_result(tmp_path)
    assert result.metrics.rounds_to_stability == 0


def test_citation_regex_rejects_bracketed_prose():
    from oracle.oracle2_adapter import extract_pack_citations

    evidence = (
        "[Note: this contradicts §4] and [WARNING: unverified] but also "
        "[far-pack:far-15-001] is real."
    )
    citations = extract_pack_citations(evidence)

    assert len(citations) == 1
    assert citations[0].pack_id == "far-pack"
    assert citations[0].rule_id == "far-15-001"


def test_citation_context_fills_section_and_authority_and_fuzzy_matches():
    from oracle.oracle2_adapter import extract_pack_citations

    context = (
        "## Authority 1: FAR (pack_id: far-pack)\n"
        "[far-pack:far-15-001] §15.304 [SHALL]: The CO shall evaluate.\n"
        "[far-pack:far-19-001] §19.202 [SHALL]: The CO shall document.\n"
    )
    evidence = (
        "The draft violates [far-pack:far-15-001]; separately, "
        "section 19.202 is not addressed."
    )
    citations = extract_pack_citations(evidence, context)

    by_rule = {c.rule_id: c for c in citations}
    assert by_rule["far-15-001"].section == "15.304"
    assert by_rule["far-15-001"].authority_label == "Authority 1"
    # Fuzzy pass: the bare "section 19.202" reference resolved unambiguously
    assert "far-19-001" in by_rule


def test_citation_context_rejects_pack_ids_absent_from_context():
    from oracle.oracle2_adapter import extract_pack_citations

    context = (
        "## Authority 1: FAR (pack_id: far-pack)\n"
        "[far-pack:far-15-001] §15.304 [SHALL]: The CO shall evaluate.\n"
    )
    # [12:30] is timestamp-shaped noise, not a pack in this session
    citations = extract_pack_citations("At [12:30] we saw [far-pack:far-15-001].", context)

    assert [c.rule_id for c in citations] == ["far-15-001"]


def test_citation_tolerates_space_after_colon():
    from oracle.oracle2_adapter import extract_pack_citations

    citations = extract_pack_citations("required by [mil-std: R-001] here")
    assert [(c.pack_id, c.rule_id) for c in citations] == [("mil-std", "R-001")]


def test_citation_space_tolerance_still_rejects_prose():
    from oracle.oracle2_adapter import extract_pack_citations

    # Prose after an aside colon has no digit in the "rule id" position
    citations = extract_pack_citations("[Note: this] and [WARNING: unverified]")
    assert citations == []


def test_citation_credibility_keeps_section_less_packs():
    """A pack rendered without § rule lines (Tier-1 FAR, section-less
    generic) is still credible via its Authority header — explicit
    citations to it must survive in multi-pack reviews."""
    from oracle.oracle2_adapter import extract_pack_citations

    context = (
        "## Authority 1: FAR (pack_id: far-pack)\n"
        "[far-pack:far-15-001] §15.304 [SHALL]: The CO shall evaluate.\n"
        "## Authority 2: MIL (pack_id: mil-pack)\n"
        "[mil-pack:R-001] [SHALL]: No section on this rule line.\n"
    )
    citations = extract_pack_citations(
        "violates [mil-pack:R-001] and [far-pack:far-15-001]", context
    )
    ids = {(c.pack_id, c.rule_id) for c in citations}
    assert ("mil-pack", "R-001") in ids
    assert ("far-pack", "far-15-001") in ids


# ---------------------------------------------------------------------------
# ReviewResult persistence contract test (Section 7.3 + 7.4)
# Verifies that run_review produces the review_result.json artifact.
# ---------------------------------------------------------------------------

def _write_minimal_converged_session(session_dir: Path) -> None:
    """Write the minimal files a converged manual-workflow session needs
    for the adapter preflight + reconstruction to succeed.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps({"session_id": "persist-test", "total_rounds": 1, "converged": True}),
        encoding="utf-8",
    )
    (session_dir / "final_draft.md").write_text("# Final\n", encoding="utf-8")
    (session_dir / "round1_beth_normalized.json").write_text(
        json.dumps({
            "normalized_issues": [{
                "issue_id": "R1-ISSUE-001",
                "title": "Test finding",
                "severity": "high",
                "core_problem": "Problem statement",
                "recommended_fix": "Fix statement",
                "best_evidence": "Evidence text referencing [test-pack:RULE-0001]",
            }]
        }),
        encoding="utf-8",
    )
    (session_dir / "round1_beth_decisions.json").write_text(
        json.dumps({"revision_decisions": [{
            "issue_id": "R1-ISSUE-001",
            "decision": "accepted_defect",
            "reason": "Because.",
        }]}),
        encoding="utf-8",
    )


def test_run_review_persists_review_result_json(tmp_path, monkeypatch):
    """run_review must write review_result.json using the adapter contract.

    This makes the ReviewResult schema (Section 7.3) a first-class,
    machine-readable deliverable alongside findings_report.md.
    """
    from pathlib import Path as _Path

    from oracle import cli as oracle_cli

    session_dir = tmp_path / "oracle_reviews" / "persist-test"
    _write_minimal_converged_session(session_dir)

    # Create a tiny stub module that run_review will import via importlib.
    class _StubSession:
        def __init__(self, sid: str, outdir: _Path):
            self.session_id = sid
            self.document_path = "doc.md"
            self.rounds = []
            self.converged = True
            self.convergence_reason = ""
            self.consensus_type = "full_agreement"

    def _fake_run_review(**kwargs):
        # Ensure the output dir the caller asked for contains the files
        # the adapter will read. The caller already set output_dir.
        out = _Path(kwargs["output_dir"])
        if not (out / "session_summary.json").exists():
            _write_minimal_converged_session(out)
        return _StubSession(kwargs.get("document_path", "x"), out)

    # Patch inside run_review's importlib step.
    import importlib as _importlib
    import sys as _sys
    real_import = _importlib.import_module

    def _fake_import(name: str):
        if name == "oracle.oracle2":
            mod = type(_sys)("_oracle2_stub")
            mod.run_review = _fake_run_review
            mod.ORACLE_ROSTER = {}
            # Also provide compute_metrics used by cmd_review path
            mod.compute_metrics = lambda s: {
                "accepted_critical_count": 0,
                "accepted_high_count": 1,
                "total_accepted_defects": 1,
                "total_rejected_claims": 0,
                "total_preference_only": 0,
                "duplicate_rate": None,
                "rounds_to_stability": 0,
                "converged": True,
            }
            return mod
        return real_import(name)

    monkeypatch.setattr(_importlib, "import_module", _fake_import)

    # Exercise the public run_review entry point with no packs (simplest).
    # It will write compliance_context (None case) + snapshot + call the
    # persistence block that invokes build_review_result.
    # Use a file under tmp_path (never the repo root) so a retry path cannot
    # overwrite tracked files like README.md.
    doc_path = tmp_path / "test_doc_for_persist.md"
    doc_path.write_text("Test document for review persistence adapter contract.", encoding="utf-8")
    session = oracle_cli.run_review(
        document_path=doc_path,
        pack_names=[],
        pack_dir=tmp_path / "packs",
        output_dir=session_dir,
        max_rounds=1,
    )

    result_path = session_dir / "review_result.json"
    assert result_path.exists(), "review_result.json must be written by run_review"

    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["session_id"] == "persist-test"
    assert data["converged"] is True
    assert "metrics" in data
    assert data["metrics"]["total_issues_accepted"] >= 0
    # The adapter must have reconstructed at least the round we wrote
    assert len(data.get("rounds", [])) >= 1
