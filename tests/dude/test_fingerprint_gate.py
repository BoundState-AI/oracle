"""Fingerprint and gate invariants (spec v0.2 I3/I4/I5, §3–4;
review A12: the hash must be keyed on user material, must treat new
hypotheses as learning, and must let silence reopen analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dude.core import fingerprint
from dude.data import (
    Case,
    CreatedBy,
    Event,
    GateMode,
    Hypothesis,
    Interpretation,
    SourceType,
)
from dude.data.case import Deadline


def _fp(case: Case, events=(), interpretations=(), hypotheses=(), last_run=None, now=None):
    return fingerprint.scope_fingerprint(
        case=case,
        captures=[],
        artifacts=[],
        events=list(events),
        interpretations=list(interpretations),
        hypotheses=list(hypotheses),
        last_run_at=last_run,
        now=now,
    )


class TestEvidenceHashKeying:
    def test_machine_records_never_change_the_hash(self) -> None:
        """v0.2 I5: re-extraction must not change any fingerprint."""
        case = Case(title="t")
        base = _fp(case)
        machine_event = Event(
            case_id=case.id,
            description="extracted",
            created_by=CreatedBy.MODEL_STUB,
            user_confirmed=False,
        )
        machine_interp = Interpretation(
            case_id=case.id, statement="model inference", created_by=CreatedBy.ENGINE
        )
        after = _fp(case, events=[machine_event], interpretations=[machine_interp])
        assert after.evidence_hash == base.evidence_hash

    def test_user_interpretation_changes_the_hash(self) -> None:
        case = Case(title="t")
        base = _fp(case)
        interp = Interpretation(case_id=case.id, statement="I think X caused Y")
        after = _fp(case, interpretations=[interp])
        assert after.evidence_hash != base.evidence_hash

    def test_silence_checkpoint_is_hashable_evidence(self) -> None:
        """v0.2 I4 / Rule 6: silence is data with data-model backing."""
        case = Case(title="t")
        base = _fp(case)
        checkpoint = Event(
            case_id=case.id,
            description="No reply after 14 days",
            is_silence_checkpoint=True,
            source_type=SourceType.SILENCE_CHECKPOINT,
        )
        after = _fp(case, events=[checkpoint])
        assert after.evidence_hash != base.evidence_hash


class TestGateModes:
    def test_first_run_is_new_evidence(self) -> None:
        case = Case(title="t")
        assert fingerprint.gate(_fp(case), None) is GateMode.NEW_EVIDENCE

    def test_unchanged_scope_is_no_new_data(self) -> None:
        case = Case(title="t")
        assert fingerprint.gate(_fp(case), _fp(case)) is GateMode.NO_NEW_DATA

    def test_new_hypothesis_is_learning_not_rumination(self) -> None:
        """v0.2 I3 / review A12a: hypothesis-set change over unchanged
        evidence gets its own labeled full re-analysis."""
        case = Case(title="t")
        prior = _fp(case)
        hypothesis = Hypothesis(case_id=case.id, title="H_new", description="d")
        current = _fp(case, hypotheses=[hypothesis])
        assert fingerprint.gate(current, prior) is GateMode.NEW_HYPOTHESIS_REANALYSIS

    def test_elapsed_time_reopens_analysis(self) -> None:
        """Continued silence changes the elapsed bucket -> SCOPE_CHANGE."""
        case = Case(title="t")
        run_at = datetime.now(timezone.utc) - timedelta(days=15)
        prior = _fp(case, last_run=None)
        current = _fp(case, last_run=run_at)
        assert current.elapsed_bucket != prior.elapsed_bucket
        assert fingerprint.gate(current, prior) is GateMode.SCOPE_CHANGE

    def test_new_deadline_changes_scope(self) -> None:
        """Case H mechanized: deadlines are fingerprint material."""
        plain = Case(title="t")
        prior = _fp(plain)
        with_deadline = plain.model_copy(
            update={
                "deadlines": [
                    Deadline(
                        description="respond to filing",
                        due_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                    )
                ]
            }
        )
        current = _fp(with_deadline)
        assert fingerprint.gate(current, prior) is not GateMode.NO_NEW_DATA

    def test_evidence_change_wins_over_hypothesis_change(self) -> None:
        case = Case(title="t")
        prior = _fp(case)
        event = Event(case_id=case.id, description="new fact")
        hypothesis = Hypothesis(case_id=case.id, title="H", description="d")
        current = _fp(case, events=[event], hypotheses=[hypothesis])
        assert fingerprint.gate(current, prior) is GateMode.NEW_EVIDENCE
