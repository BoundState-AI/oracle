#!/usr/bin/env python3
"""
Module: dude.core.triggers
Purpose: Symmetric trigger matching and the single merged adjustment
         (spec v0.2 I7; review A6–A8).

A trigger match never discounts. It WIDENS uncertainty — evidence
requirements go up in both directions — unless the trigger's calibration
tag says the user's record in this domain is historically accurate, in
which case the effect is ATTEND (the signal is worth weight). Each
trigger contributes exactly once, with its calibration folded into that
one contribution, so a single disposition is never counted twice
(review A7). The merge produces ONE ConfidenceAdjustment per run,
itemized and user-visible.

Matching in Phase 1 is deterministic substring matching over cues; any
future semantic matcher is a model inference and must be labeled as such
(review revision 16).

Safety Critical: False
Psychologically Critical: True — this module is where "you're
overreacting" would be built if built wrong.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging

from dude.data.enums import TriggerCalibration
from dude.data.triggers import (
    AdjustmentContribution,
    AdjustmentEffect,
    ConfidenceAdjustment,
    TriggerMatch,
    TriggerPattern,
)

LOGGER = logging.getLogger("dude.core.triggers")

# Foundational UX copy (v0.1 §8, corrected to be symmetric per v0.2 I7).
# Evidence-state language only — validated against the banned-phrase list
# by tests (I2).
WIDEN_NOTE = (
    "This case overlaps known trigger patterns. That does not make your "
    "interpretation false, and it does not make it true. Evidence "
    "requirements are higher in both directions until evidence improves."
)
ATTEND_NOTE = (
    "This case overlaps a pattern where your reads have historically been "
    "accurate. The signal is worth weight; the cause still needs evidence."
)
MIXED_NOTE = (
    "This case overlaps known trigger patterns, including one where your "
    "reads have historically been accurate. Treat the signal as worth "
    "weight, and hold interpretations to higher evidence in both directions."
)


def match(triggers: list[TriggerPattern], case_text: str) -> list[TriggerMatch]:
    """Deterministic cue matching over active triggers."""
    haystack = case_text.lower()
    matches: list[TriggerMatch] = []
    for trigger in triggers:
        if not trigger.active:
            continue
        hits = [cue for cue in trigger.cues if cue.lower() in haystack]
        if hits:
            matches.append(
                TriggerMatch(
                    trigger_id=trigger.id,
                    trigger_name=trigger.name,
                    matched_cues=sorted(hits),
                    calibration=trigger.calibration,
                )
            )
    return matches


def merge(matches: list[TriggerMatch]) -> ConfidenceAdjustment:
    """Fold all matches into ONE itemized adjustment (v0.2 I7).

    Effect rule: historically_accurate -> ATTEND; overfires/neutral ->
    WIDEN. Net: WIDEN if any widen contribution exists (evidence
    requirements up both ways is the conservative direction), with the
    note acknowledging attend-domains when both are present."""
    contributions = [
        AdjustmentContribution(
            channel="trigger",
            source_id=m.trigger_id,
            effect=_effect_for(m.calibration),
            note=f"{m.trigger_name}: matched {', '.join(m.matched_cues)}",
        )
        for m in matches
    ]
    effects = {c.effect for c in contributions}
    if not effects:
        return ConfidenceAdjustment()
    if effects == {AdjustmentEffect.ATTEND}:
        net, note = AdjustmentEffect.ATTEND, ATTEND_NOTE
    elif AdjustmentEffect.ATTEND in effects:
        net, note = AdjustmentEffect.WIDEN, MIXED_NOTE
    else:
        net, note = AdjustmentEffect.WIDEN, WIDEN_NOTE
    return ConfidenceAdjustment(
        net_effect=net, contributions=contributions, user_facing_note=note
    )


def _effect_for(calibration: TriggerCalibration) -> AdjustmentEffect:
    if calibration is TriggerCalibration.HISTORICALLY_ACCURATE:
        return AdjustmentEffect.ATTEND
    return AdjustmentEffect.WIDEN
