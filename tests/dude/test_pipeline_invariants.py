"""Pipeline control-flow invariants (spec v0.2 §2, I1/I2/I12).

The load-bearing tests: the safety floor runs BEFORE the no-new-data
gate, a failed safety persist aborts the run, crisis output is never
gated, stub passes refuse visibly, and every user-facing summary passes
the banned-phrase floor.
"""

from __future__ import annotations

import pytest

import time

from dude.core.loop import validate_copy
from dude.data import Case, CaseStatus, GateMode, Hypothesis, Interpretation
from dude.pipeline.engine import analyze, capture
from dude.pipeline.passes import STUB_REASON, PassOutput, PassSet
from dude.store.jsonl import CaseStore, StoreError

CRISIS_TEXT = "He said he's going to kill me if I leave."
BENIGN_TEXT = "Jerry replied and suggested open source."


class TestSafetyBeforeGate:
    def test_safety_scan_persists_even_when_gate_blocks(self, store, case) -> None:
        """v0.2 I1: analyze twice with no changes — the second run serves
        the prior analysis, but the safety scan still ran and persisted."""
        capture(store, case.id, CRISIS_TEXT)
        analyze(store, case.id)
        events_after_first = len(store.load_case(case.id).safety_events)
        result = analyze(store, case.id)  # no changes -> gate blocks
        assert result.served_prior
        events_after_second = len(store.load_case(case.id).safety_events)
        assert events_after_second == events_after_first + 1

    def test_crisis_output_is_never_gated(self, store, case) -> None:
        capture(store, case.id, CRISIS_TEXT)
        analyze(store, case.id)
        result = analyze(store, case.id)  # NO_NEW_DATA path
        assert result.served_prior
        assert result.safety.crisis
        assert result.safety.resources

    def test_failed_safety_persist_aborts_capture(self, store, case) -> None:
        """v0.2 I1: the SafetyEvent write happens first and its failure
        aborts the run. The stream file is replaced by a directory so the
        append fails naturally — no monkeypatching."""
        case_dir = store.root / "cases" / case.id
        (case_dir / "safety_events.jsonl").mkdir()
        with pytest.raises(StoreError):
            capture(store, case.id, CRISIS_TEXT)
        # Ordering proof: the capture itself must NOT have been persisted.
        assert not (case_dir / "captures.jsonl").exists()


class TestGateBehavior:
    def test_first_analysis_runs_full(self, store, case) -> None:
        capture(store, case.id, BENIGN_TEXT)
        result = analyze(store, case.id)
        assert not result.served_prior
        assert result.run.mode is GateMode.NEW_EVIDENCE

    def test_no_new_data_serves_prior(self, store, case) -> None:
        capture(store, case.id, BENIGN_TEXT)
        first = analyze(store, case.id)
        second = analyze(store, case.id)
        assert second.served_prior
        assert second.run.id == first.run.id

    def test_new_user_interpretation_reopens_analysis(self, store, case) -> None:
        capture(store, case.id, BENIGN_TEXT)
        analyze(store, case.id)
        store.append(Interpretation(case_id=case.id, statement="I think X did Y"))
        result = analyze(store, case.id)
        assert not result.served_prior

    def test_new_hypothesis_is_labeled_learning(self, store, case) -> None:
        """v0.2 I3: hypothesis-only change -> NEW_HYPOTHESIS_REANALYSIS."""
        capture(store, case.id, BENIGN_TEXT)
        analyze(store, case.id)
        store.append(
            Hypothesis(case_id=case.id, title="new theory", description="d")
        )
        result = analyze(store, case.id)
        assert not result.served_prior
        assert result.run.mode is GateMode.NEW_HYPOTHESIS_REANALYSIS
        assert "learning" in result.run.user_facing_summary


class TestHonestStubsAndCopy:
    def test_stub_passes_refuse_visibly(self, store, case) -> None:
        """v0.2 I12: a run's record says which passes did not run."""
        capture(store, case.id, BENIGN_TEXT)
        result = analyze(store, case.id)
        stubbed = {r.pass_name for r in result.run.refusals}
        assert {"separator", "unknowns", "hypotheses", "adversary"} <= stubbed
        assert all(r.reason == STUB_REASON for r in result.run.refusals)
        assert "did not run" in result.run.user_facing_summary

    def test_summary_passes_banned_phrase_floor(self, store, case) -> None:
        capture(store, case.id, CRISIS_TEXT)
        result = analyze(store, case.id)
        validate_copy(result.run.user_facing_summary)  # must not raise

    def test_crisis_summary_contains_resources(self, store, case) -> None:
        capture(store, case.id, CRISIS_TEXT)
        result = analyze(store, case.id)
        assert result.run.crisis_active
        assert "988" in result.run.user_facing_summary

    def test_analysis_activates_case_status(self, store, case) -> None:
        capture(store, case.id, BENIGN_TEXT)
        analyze(store, case.id)
        assert store.load_case(case.id).case.status is CaseStatus.ACTIVE


class SlowExplodingHypotheses:
    """A concurrent-batch pass that stalls, then dies mid-run — the run
    must absorb it as a visible refusal, never crash or lose the sibling
    passes' output."""

    pass_name = "hypotheses"

    def run(self, bundle) -> PassOutput:  # noqa: ARG002
        time.sleep(0.2)  # outlive the fast sibling stubs before failing
        raise RuntimeError("provider meltdown")


class TestConcurrentPassFailure:
    def test_failing_concurrent_pass_becomes_its_refusal(self, store, case) -> None:
        """Fail closed under concurrency: an exception inside one builder
        pass surfaces as that pass's refusal alongside the others' — the
        analysis run still persists."""
        capture(store, case.id, BENIGN_TEXT)
        result = analyze(
            store, case.id, passes=PassSet(hypotheses=SlowExplodingHypotheses())
        )
        assert not result.served_prior
        by_pass = {r.pass_name: r.reason for r in result.run.refusals}
        assert "provider meltdown" in by_pass["hypotheses"]
        # The sibling stubs still reported their own refusals, and the
        # run itself persisted despite the mid-batch exception.
        assert {"separator", "unknowns", "adversary"} <= set(by_pass)
        assert store.load_case(case.id).analysis_runs[-1].id == result.run.id


class TestStoreDiscipline:
    def test_records_are_append_only_and_supersede(self, store, case) -> None:
        """v0.2 I11: corrections supersede; nothing is overwritten."""
        original = Hypothesis(case_id=case.id, title="v1", description="d")
        store.append(original)
        revised = original.model_copy(
            update={"id": "rev1", "title": "v2", "supersedes": original.id}
        )
        store.append(revised)
        loaded = store.load_case(case.id).hypotheses
        assert [h.title for h in loaded] == ["v2"]
        assert loaded[0].lineage_id == original.lineage_id

    def test_orphan_records_are_rejected(self, store) -> None:
        with pytest.raises(StoreError, match="does not exist"):
            store.append(
                Interpretation(case_id="no_such_case", statement="orphan")
            )

    def test_contracts_reject_unknown_keys(self) -> None:
        with pytest.raises(Exception):
            Case.model_validate({"title": "t", "surprise_field": 1})

    def test_contract_round_trip_is_lossless(self, store, case) -> None:
        loaded = store.load_case(case.id).case
        assert loaded.to_json_dict() == case.to_json_dict()
