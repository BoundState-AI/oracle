#!/usr/bin/env python3
"""
Module: dude.data.safety
Purpose: Safety contracts (spec v0.2 §5, I1).

SafetyEvent is the durable record of a safety-floor hit; it is persisted
BEFORE any other pipeline step executes, and a store failure while
persisting it aborts the run with a refusal. SafetyScanResult is the
floor's full output including the crisis resources to surface.

Safety Critical: True — a lost or suppressed safety event is the cardinal
failure mode of this system.
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import uuid
from datetime import datetime, timezone

from pydantic import Field

from dude.data.base import DudeModel
from dude.data.enums import CHRONIC_SAFETY_CATEGORIES, SafetyCategory


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CrisisResource(DudeModel):
    """One resource line surfaced verbatim in crisis output."""

    name: str
    contact: str
    note: str = ""


class SafetyFlag(DudeModel):
    """One category hit with the excerpt that matched. The excerpt is kept
    so the flag is auditable — a safety decision with no visible basis is
    unreviewable."""

    category: SafetyCategory
    matched_excerpt: str
    pattern_name: str

    def is_chronic(self) -> bool:
        return self.category in CHRONIC_SAFETY_CATEGORIES


class SafetyScanResult(DudeModel):
    """Full output of one safety-floor scan (v0.2 §5).

    `crisis` means acute categories fired: hold/wait recommendations and
    the high-risk action option are suppressed downstream, and `resources`
    must be surfaced verbatim. Chronic flags additionally feed conduct
    accrual. A scan result is NEVER gated by the no-new-data gate."""

    flags: list[SafetyFlag] = Field(default_factory=list)
    crisis: bool = False
    resources: list[CrisisResource] = Field(default_factory=list)
    user_facing_message: str = ""

    def chronic_flags(self) -> list[SafetyFlag]:
        return [f for f in self.flags if f.is_chronic()]


class SafetyEvent(DudeModel):
    """Durable record of a safety-floor hit (writes to the store's
    safety_events stream; consumed by the pipeline and the CLI status
    surface — review A2: the table exists AND something writes and reads
    it)."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    capture_id: str | None = None
    flags: list[SafetyFlag]
    crisis: bool
    recorded_at: datetime = Field(default_factory=_now)
