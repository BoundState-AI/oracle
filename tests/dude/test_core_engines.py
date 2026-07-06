"""State machine, conduct accrual, trigger symmetry, and loop-copy
invariants (spec v0.2 I2/I6/I7; review A4/A6/A7/A8/A15)."""

from __future__ import annotations

import pytest

from dude.core import conduct, loop
from dude.core import triggers as trigger_engine
from dude.core.state import CaseEvent, InvalidTransition, transition, waiting_for_data
from dude.data import (
    ConfidenceBand,
    CreatedBy,
    Event,
    GateMode,
    TriggerCalibration,
    TriggerPattern,
)
from dude.data.enums import CaseStatus
from dude.data.triggers import AdjustmentEffect


class TestStateMachine:
    def test_analysis_activates_case(self) -> None:
        assert (
            transition(CaseStatus.UNSTRUCTURED, CaseEvent.ANALYSIS_PERSISTED)
            is CaseStatus.ACTIVE
        )

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(InvalidTransition):
            transition(CaseStatus.ARCHIVED, CaseEvent.DECISION_RECORDED)

    def test_reopen_is_an_edge_not_a_state(self) -> None:
        assert transition(CaseStatus.RESOLVED, CaseEvent.REOPENED) is CaseStatus.ACTIVE

    def test_waiting_for_data_is_computed_only(self) -> None:
        """Review A15: WAITING_FOR_DATA must not exist as a stored status."""
        assert not hasattr(CaseStatus, "WAITING_FOR_DATA")
        assert waiting_for_data(GateMode.NO_NEW_DATA)
        assert not waiting_for_data(GateMode.NEW_EVIDENCE)


def _incident(case_id: str, n: int) -> Event:
    return Event(
        case_id=case_id,
        description=f"showed up uninvited #{n}",
        pattern_class="unwanted_contact",
        created_by=CreatedBy.USER,
    )


class TestConductAccrual:
    def test_drip_evidence_crosses_bands(self) -> None:
        """Review A4: each incident individually explainable, jointly
        damning — the cumulative band must escalate with count."""
        events_2 = [_incident("c", i) for i in range(2)]
        events_5 = [_incident("c", i) for i in range(5)]
        band_2 = conduct.accrue(events_2)[0].cumulative_band
        band_5 = conduct.accrue(events_5)[0].cumulative_band
        assert band_2 is ConfidenceBand.WEAKLY_SUPPORTED
        assert band_5 is ConfidenceBand.SUPPORTED

    def test_unconfirmed_machine_events_do_not_accrue(self) -> None:
        machine = Event(
            case_id="c",
            description="extracted incident",
            pattern_class="unwanted_contact",
            created_by=CreatedBy.MODEL_STUB,
            user_confirmed=False,
        )
        assert conduct.accrue([machine]) == []

    def test_events_without_pattern_class_do_not_accrue(self) -> None:
        plain = Event(case_id="c", description="a normal thing happened")
        assert conduct.accrue([plain]) == []


def _trigger(name: str, calibration: TriggerCalibration) -> TriggerPattern:
    return TriggerPattern(
        name=name,
        cues=["institutional silence"],
        calibration=calibration,
        confidence="user_stated",
        user_confirmed=True,
        active=True,
    )


class TestTriggerSymmetry:
    CASE_TEXT = "Weeks of institutional silence after the email."

    def test_match_widens_not_discounts(self) -> None:
        """Review A6: no discount channel exists; the effect vocabulary
        has no such member and neutral triggers widen."""
        assert not hasattr(AdjustmentEffect, "DISCOUNT")
        matches = trigger_engine.match(
            [_trigger("t", TriggerCalibration.NEUTRAL)], self.CASE_TEXT
        )
        adjustment = trigger_engine.merge(matches)
        assert adjustment.net_effect is AdjustmentEffect.WIDEN
        assert "both directions" in adjustment.user_facing_note

    def test_historically_accurate_attends(self) -> None:
        """v0.2 I7: calibration can raise, not only lower."""
        matches = trigger_engine.match(
            [_trigger("t", TriggerCalibration.HISTORICALLY_ACCURATE)], self.CASE_TEXT
        )
        adjustment = trigger_engine.merge(matches)
        assert adjustment.net_effect is AdjustmentEffect.ATTEND

    def test_one_contribution_per_trigger(self) -> None:
        """Review A7: a single disposition is never counted twice."""
        matches = trigger_engine.match(
            [
                _trigger("a", TriggerCalibration.NEUTRAL),
                _trigger("b", TriggerCalibration.HISTORICALLY_ACCURATE),
            ],
            self.CASE_TEXT,
        )
        adjustment = trigger_engine.merge(matches)
        assert len(adjustment.contributions) == 2
        assert len({c.source_id for c in adjustment.contributions}) == 2

    def test_inferred_trigger_cannot_activate_unconfirmed(self) -> None:
        with pytest.raises(ValueError):
            TriggerPattern(
                name="inferred",
                cues=["silence"],
                confidence="inferred",
                user_confirmed=False,
                active=True,
            )

    def test_adjustment_copy_passes_banned_phrase_floor(self) -> None:
        for note in (
            trigger_engine.WIDEN_NOTE,
            trigger_engine.ATTEND_NOTE,
            trigger_engine.MIXED_NOTE,
        ):
            loop.validate_copy(note)


class TestLoopCopy:
    def test_motive_attribution_is_banned(self) -> None:
        """v0.2 I2 / review A8: the v0.1 line can never ship."""
        with pytest.raises(loop.BannedCopyError):
            loop.validate_copy("You are recomputing because uncertainty hurts.")

    def test_pathologizing_copy_is_banned(self) -> None:
        with pytest.raises(loop.BannedCopyError):
            loop.validate_copy("Honestly you're just triggered right now.")

    def test_mode_messages_describe_evidence_state(self) -> None:
        for mode in GateMode:
            loop.validate_copy(loop.mode_message(mode))

    def test_loop_concern_is_a_question_not_a_verdict(self) -> None:
        text = loop.loop_question("Tawyna talked to Herald")
        assert "?" in text
        assert "initiator" in text or "direction" in text
