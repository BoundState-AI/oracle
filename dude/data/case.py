#!/usr/bin/env python3
"""
Module: dude.data.case
Purpose: Case and analysis-run contracts (spec v0.1 §6/§10, v0.2 §2–4).

Deadlines are first-class (review Case H is mechanized: they enter the
scope fingerprint, so an approaching deadline reopens analysis). The
stored status never contains WAITING_FOR_DATA — that is computed from the
gate (review A15: no dual source of truth).

Safety Critical: False
Psychologically Critical: True — AnalysisRun is the record the user
trusts; a run that misstates its own gate mode re-creates review A12.

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
from dude.data.enums import CaseStatus, ConfidenceBand, GateMode
from dude.data.triggers import ConfidenceAdjustment, TriggerMatch


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Deadline(DudeModel):
    """An irreversible-by-date constraint (review Case H)."""

    id: str = Field(default_factory=_new_id)
    description: str
    due_at: datetime
    resolved: bool = False


class Case(DudeModel):
    """The primary object (v0.1 §6). The system holds no favored model;
    only the user does (v0.2 I10)."""

    id: str = Field(default_factory=_new_id)
    title: str
    summary: str | None = None
    status: CaseStatus = CaseStatus.UNSTRUCTURED
    user_favored_hypothesis_id: str | None = None
    deadlines: list[Deadline] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


class ScopeFingerprint(DudeModel):
    """The analysis-scope fingerprint (v0.2 §4). evidence_hash covers
    user-contributed material only; scope_hash adds the hypothesis set,
    deadlines, and the elapsed-time bucket."""

    evidence_hash: str
    scope_hash: str
    elapsed_bucket: int
    computed_at: datetime = Field(default_factory=_now)


class HypothesisDelta(DudeModel):
    """One hypothesis's band movement between runs (v0.1 §19–20), keyed by
    lineage so regenerated hypotheses still diff (review A21)."""

    lineage_id: str
    title: str
    previous: ConfidenceBand | None = None
    current: ConfidenceBand
    reason: str


class CumulativePattern(DudeModel):
    """Course-of-conduct accrual state for one pattern class (v0.2 I6).
    `cumulative_band` is computed over the whole case, not the last delta,
    so drip evidence can cross bands (review A4)."""

    pattern_class: str
    event_count: int
    first_at: datetime | None = None
    last_at: datetime | None = None
    cumulative_band: ConfidenceBand


class Refusal(DudeModel):
    """A pass that could not run safely. Refusals are findings, not
    silence (v0.2 I12): a run with refusals says so on its face."""

    pass_name: str
    reason: str


class AnalysisRun(DudeModel):
    """One analysis run's durable record (v0.2 §2)."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    mode: GateMode
    fingerprint: ScopeFingerprint
    crisis_active: bool = False
    hypothesis_bands: dict[str, ConfidenceBand] = Field(default_factory=dict)
    deltas: list[HypothesisDelta] = Field(default_factory=list)
    cumulative_patterns: list[CumulativePattern] = Field(default_factory=list)
    trigger_matches: list[TriggerMatch] = Field(default_factory=list)
    adjustment: ConfidenceAdjustment = Field(default_factory=ConfidenceAdjustment)
    refusals: list[Refusal] = Field(default_factory=list)
    user_facing_summary: str = ""
    recorded_at: datetime = Field(default_factory=_now)
