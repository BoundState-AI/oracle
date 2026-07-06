#!/usr/bin/env python3
"""
Module: dude.data.evidence
Purpose: Evidence-side contracts — captures, artifacts, events,
         observations, interpretations, unknowns (spec v0.1 §7 stages 1–5,
         v0.2 I4/I5/I11).

The observed / inferred / unknown separation is the product. Observations
carry mandatory provenance ("no orphan facts"); interpretations are stored
separately and never promoted silently. Records are immutable in the store:
a correction is a new record whose `supersedes` points at the old one.

Safety Critical: False
Psychologically Critical: True — a mislabeled record (inference stored as
observation) is the exact failure the product exists to prevent.

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

from pydantic import Field, model_validator

from dude.data.base import DudeModel
from dude.data.enums import (
    CreatedBy,
    OutcomeProvenance,
    SourceType,
    UnknownImportance,
)


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Provenance(DudeModel):
    """Where a claim came from (v0.1 §31). Every observation carries at
    least one; the store rejects observations without any."""

    source_type: SourceType
    source_id: str
    excerpt: str | None = None
    timestamp: datetime | None = None


class Capture(DudeModel):
    """One raw user input (v0.1 Stage 1). The capture ID is minted here,
    once, and is fingerprint material (v0.2 §4)."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    text: str
    source_type: SourceType = SourceType.USER_STATEMENT
    recorded_at: datetime = Field(default_factory=_now)


class Artifact(DudeModel):
    """An attached file/document. `content_sha256` is fingerprint material;
    re-processing an artifact never changes it (v0.2 I5)."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    filename: str
    content_sha256: str
    source_type: SourceType = SourceType.DOCUMENT
    recorded_at: datetime = Field(default_factory=_now)


class Event(DudeModel):
    """A discrete happening (v0.1 Stage 2). IDs are minted at creation and
    never re-minted by re-extraction. `pattern_class` feeds course-of-conduct
    accrual (v0.2 I6); `is_silence_checkpoint` makes Rule 6 hashable (I4).

    Only user-confirmed events enter the evidence fingerprint, so
    engine-extracted events must be confirmed by the user to count."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    description: str
    occurred_at: datetime | None = None
    recorded_at: datetime = Field(default_factory=_now)
    source_type: SourceType = SourceType.USER_STATEMENT
    source_capture_id: str | None = None
    source_artifact_id: str | None = None
    created_by: CreatedBy = CreatedBy.USER
    user_confirmed: bool = False
    pattern_class: str | None = None
    is_silence_checkpoint: bool = False
    supersedes: str | None = None

    @model_validator(mode="after")
    def _user_records_are_confirmed(self) -> "Event":
        # WHY: a user-authored event IS user confirmation; requiring a second
        # click would train users to ignore the confirmation concept.
        if self.created_by is CreatedBy.USER:
            object.__setattr__(self, "user_confirmed", True)
        return self


class Observation(DudeModel):
    """A claim directly supported by input (v0.1 Stage 3). Mandatory
    provenance — no orphan facts."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    statement: str
    provenance: list[Provenance] = Field(min_length=1)
    source_event_ids: list[str] = Field(default_factory=list)
    created_by: CreatedBy = CreatedBy.USER
    user_confirmed: bool = False
    recorded_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None


class Interpretation(DudeModel):
    """A claim NOT directly supported by input (v0.1 Stage 4) — stored
    separately from observations, visibly and structurally. User-authored
    interpretations are fingerprint material (v0.2 §4); engine-extracted
    ones are not (I5)."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    statement: str
    version: int = 1
    created_by: CreatedBy = CreatedBy.USER
    recorded_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None


class Unknown(DudeModel):
    """Explicitly missing information (v0.1 Stage 5)."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    statement: str
    importance: UnknownImportance = UnknownImportance.MEDIUM
    resolved_by_event_id: str | None = None
    recorded_at: datetime = Field(default_factory=_now)


class Outcome(DudeModel):
    """What actually happened (v0.1 §61). Outcome labels get the same
    observed/inferred discipline as everything else (review A14):
    calibration may only generalize from VERIFIED outcomes, and the
    provenance band is mandatory."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    statement: str
    provenance_band: OutcomeProvenance
    related_hypothesis_id: str | None = None
    recorded_at: datetime = Field(default_factory=_now)
