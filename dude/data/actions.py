#!/usr/bin/env python3
"""
Module: dude.data.actions
Purpose: Action contracts (spec v0.1 §13–15, rebuilt per v0.2 I8/I9).

Removed relative to v0.1 §15, by review finding:
  - EmotionalImpulsePenalty / impulseContamination (A10) — the user's
    emotional state is never a scoring input.
  - HypothesisWeight (A9) — no hidden priors; scoring is prior-free.
  - The reversibility double-count (A3) — one reversibility field.
Added:
  - per-hypothesis information gain (probing is not free in adversarial
    worlds), `safety_seeking` (exempt from irreversibility penalties under
    the I9 override), and `unsafe_under` (hypothesis IDs under which the
    action is unacceptable — the input to safety-dominant filtering).

Safety Critical: False
Psychologically Critical: True — this schema is where inaction bias
(review A3) would re-enter if fields regress.

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


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ActionOption(DudeModel):
    """A candidate move. Generators must always include a no-action option
    and an information-seeking option (v0.1 §36); the high-risk option is
    suppressed while a crisis flag is active (v0.2 §5)."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    title: str
    description: str
    safety_seeking: bool = False
    is_no_action: bool = False
    is_information_seeking: bool = False
    recorded_at: datetime = Field(default_factory=_now)


class ActionEvaluation(DudeModel):
    """Prior-free evaluation of one action across live hypotheses.

    `utilities` and `information_gain` are keyed by hypothesis id — there
    is deliberately no aggregate utility field, because any aggregate
    would need the hypothesis prior v0.2 I8 forbids. Aggregation happens
    only in dude.core.actions via dominance / minimax-regret, and the
    criterion used is reported on the result."""

    action_id: str
    utilities: dict[str, float] = Field(default_factory=dict)
    information_gain: dict[str, float] = Field(default_factory=dict)
    unsafe_under: list[str] = Field(default_factory=list)
    reversibility: float = Field(ge=0.0, le=1.0, default=0.5)
    option_preservation: float = Field(ge=0.0, le=1.0, default=0.5)
    financial_cost: float = Field(ge=0.0, le=1.0, default=0.0)
    social_cost: float = Field(ge=0.0, le=1.0, default=0.0)
    legal_risk: float = Field(ge=0.0, le=1.0, default=0.0)
    professional_risk: float = Field(ge=0.0, le=1.0, default=0.0)
    physical_risk: float = Field(ge=0.0, le=1.0, default=0.0)
    emotional_cost: float = Field(ge=0.0, le=1.0, default=0.0)
    time_cost: float = Field(ge=0.0, le=1.0, default=0.0)
    notes: list[str] = Field(default_factory=list)


class ActionRecommendation(DudeModel):
    """The engine's ranked output. `criterion` names the decision rule that
    produced the ranking (\"dominance+minimax_regret\" or
    \"safety_dominant\") so authority is never overstated (review A9:
    determinism of arithmetic confers nothing on invented operands — the
    criterion and its inputs are both visible)."""

    case_id: str
    criterion: str
    safety_dominant_applied: bool = False
    ranked_action_ids: list[str] = Field(default_factory=list)
    excluded_action_ids: dict[str, str] = Field(default_factory=dict)
    works_under: dict[str, list[str]] = Field(default_factory=dict)
    fails_under: dict[str, list[str]] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_now)
