#!/usr/bin/env python3
"""
Module: hearth.data.buyer_pack
Purpose: BuyerPack — the canonical household, structured (spec v0.3 §2.1).

BuyerPack is local-first and NEVER crosses the trust boundary in plaintext
(§1.1). No BuyerPack field may be placed into an outbound network call, a
server log, a non-E2EE store, or a third-party model prompt — that is a
build-failing violation enforced by the boundary tests (§6, §12 P1-D).
This module defines the shape only; it performs no I/O.

Safety Critical: False
Financially Critical: False (contract definition; consumers carry the risk)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

from datetime import date
from typing import Literal

from pydantic import Field

from hearth.data.base import HearthModel


class BuyerPackIdentity(HearthModel):
    """Who this pack canonically describes (§2.1 identity block)."""

    household: str
    pack_version: str
    created: date


class Financing(HearthModel):
    """Financing posture (§2.1 hard_constraints.financing)."""

    type: Literal["conventional", "cash", "hybrid"]
    preapproval_usd: int = Field(ge=0)
    down_pct: float = Field(ge=0.0, le=1.0)
    rate_lock_expiry: date | None = None


class Geography(HearthModel):
    """Geographic envelope (§2.1 hard_constraints.geography)."""

    anchor: str
    max_commute_min: int = Field(ge=0)
    counties: list[str]


class HardConstraints(HearthModel):
    """Constraints that disqualify, never trade off (§2.1)."""

    budget_ceiling_usd: int = Field(gt=0)
    financing: Financing
    geography: Geography
    deal_breakers: list[str]


class SoftPreference(HearthModel):
    """Weighted preference consumed by the FitScorer (§2.1, §3.5)."""

    feature: str
    # bool before int: pydantic smart-union keeps `true` a bool and 600 an
    # int, so round-trips stay lossless for both target shapes in §2.1.
    target: bool | int | float | str
    weight: float = Field(ge=0.0, le=1.0)


class Timeline(HearthModel):
    """Occupancy pressure, quantified (§2.1 timeline)."""

    need_occupancy_by: date
    flexibility_days: int = Field(ge=0)
    temp_housing_runway_days: int = Field(ge=0)


class Posture(HearthModel):
    """Negotiation posture (§2.1). disclosure_policy is enforced by the
    leak check (§6), not merely suggested."""

    contingency_tolerance: Literal["standard", "tight", "waive_with_evidence"]
    max_appraisal_gap_usd: int = Field(ge=0)
    disclosure_policy: Literal["reveal_nothing"]


class BuyerPack(HearthModel):
    """The canonical household (§2.1). Local-first; E2EE sync only."""

    identity: BuyerPackIdentity
    hard_constraints: HardConstraints
    soft_preferences: list[SoftPreference]
    timeline: Timeline
    posture: Posture
