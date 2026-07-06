#!/usr/bin/env python3
"""
Module: dude.data.hypotheses
Purpose: Hypothesis contracts (spec v0.1 Stage 6, §25; v0.2 I3/I9/I10).

Hypotheses carry a `lineage_id` distinct from `id`: regenerated or revised
hypotheses keep their lineage, which is what makes cross-run deltas
("previous: plausible → current: weakened") possible (review A21) and what
the scope fingerprint hashes (v0.2 §4).

Adversary output attaches as annotations — it never silently rewrites a
hypothesis (v0.2 I10). The system holds no favored model; only the user
does (Case.user_favored_hypothesis_id).

Safety Critical: False
Psychologically Critical: True — the harm_class field drives the
asymmetric-stakes override (I9); mislabeling it re-creates review A3.

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

from pydantic import Field

from dude.data.base import DudeModel
from dude.data.enums import ConfidenceBand, CreatedBy, HarmClass, HypothesisArchetype


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AdversaryAnnotation(DudeModel):
    """One adversarial attack attached to a hypothesis. Disagreements are
    surfaced, never merged (v0.2 I10)."""

    id: str = Field(default_factory=_new_id)
    attack: str
    unsupported_links: list[str] = Field(default_factory=list)
    created_by: CreatedBy = CreatedBy.MODEL_STUB
    recorded_at: datetime = Field(default_factory=_now)


class Hypothesis(DudeModel):
    """One competing causal explanation.

    `falsifiers` ("what evidence would change this") is mandatory content,
    not decoration — it is the exit criterion for WAITING_FOR_DATA
    (v0.1 §25; review strong points). `not_credible_here` lets an archetype
    slot report honestly instead of manufacturing false balance
    (review A11 / revision 14): a slot that cannot be credibly filled says
    so, and that itself is reportable evidence."""

    id: str = Field(default_factory=_new_id)
    lineage_id: str = Field(default_factory=_new_id)
    case_id: str
    title: str
    description: str
    archetype: HypothesisArchetype = HypothesisArchetype.OTHER
    harm_class: HarmClass = HarmClass.NONE
    band: ConfidenceBand = ConfidenceBand.UNRESOLVED
    falsifiers: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    annotations: list[AdversaryAnnotation] = Field(default_factory=list)
    not_credible_here: bool = False
    created_by: CreatedBy = CreatedBy.USER
    recorded_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None

    def is_live(self) -> bool:
        """Live = not contradicted and not an honestly-empty archetype slot.

        WHY: liveness drives the safety-dominant override (v0.2 I9) — a
        contradicted catastrophic hypothesis must stop forcing the override,
        and a placeholder slot must never trigger it."""
        return self.band is not ConfidenceBand.CONTRADICTED and not self.not_credible_here
