#!/usr/bin/env python3
"""
Module: dude.data.triggers
Purpose: Trigger-layer contracts (spec v0.1 §8–9, rebuilt per v0.2 I7).

The v0.1 trigger layer was a one-way confidence discount; the ORACLE review
(A6–A8) showed that to be statistically unlicensed and structurally
gaslighting. v0.2 replaces it: a trigger match WIDENS uncertainty in both
directions, calibration tags can shift that (a historically-accurate
trigger is a reason to ATTEND, not discount), and all channels merge into
one net, itemized, user-visible adjustment.

Safety Critical: False
Psychologically Critical: True — this layer is where "you're overreacting"
would be built if built wrong.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import Field, model_validator

from dude.data.base import DudeModel
from dude.data.enums import TriggerCalibration, TriggerConfidence


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TriggerPattern(DudeModel):
    """A user-known trigger class (v0.1 §9, minus clinician_supplied —
    removed for Phase 1 per v0.2 §6).

    Inferred triggers can never silently become active: activation of an
    inferred trigger requires explicit user confirmation (v0.1 §9,
    enforced here rather than suggested)."""

    id: str = Field(default_factory=_new_id)
    name: str
    description: str | None = None
    cues: list[str] = Field(default_factory=list)
    typical_interpretations: list[str] = Field(default_factory=list)
    severity: int = Field(ge=1, le=5, default=3)
    confidence: TriggerConfidence = TriggerConfidence.USER_STATED
    calibration: TriggerCalibration = TriggerCalibration.NEUTRAL
    user_confirmed: bool = False
    active: bool = False
    recorded_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _inferred_requires_confirmation(self) -> "TriggerPattern":
        if (
            self.active
            and self.confidence is TriggerConfidence.INFERRED
            and not self.user_confirmed
        ):
            raise ValueError(
                "An inferred trigger cannot be active without explicit user "
                "confirmation (spec v0.1 §9 / v0.2 I7)."
            )
        return self


class TriggerMatch(DudeModel):
    """One trigger's overlap with a case, with the cues that matched."""

    trigger_id: str
    trigger_name: str
    matched_cues: list[str] = Field(default_factory=list)
    calibration: TriggerCalibration = TriggerCalibration.NEUTRAL


class AdjustmentEffect(str, Enum):
    """Net effect vocabulary. There is no 'discount' — that word and that
    mechanism were removed by the review (A6). WIDEN raises evidence
    requirements in BOTH directions; ATTEND marks a historically accurate
    signal domain as worth weight."""

    NONE = "none"
    WIDEN = "widen"
    ATTEND = "attend"


class AdjustmentContribution(DudeModel):
    """One itemized channel contribution (trigger / memory / calibration).
    Channels are merged into a single net adjustment (v0.2 I7) so a single
    disposition is never counted twice (review A7)."""

    channel: str
    source_id: str
    effect: AdjustmentEffect
    note: str


class ConfidenceAdjustment(DudeModel):
    """THE single net adjustment attached to an analysis run. One per run,
    itemized, user-visible; the merge rule lives in dude.core.triggers."""

    net_effect: AdjustmentEffect = AdjustmentEffect.NONE
    contributions: list[AdjustmentContribution] = Field(default_factory=list)
    user_facing_note: str = ""
