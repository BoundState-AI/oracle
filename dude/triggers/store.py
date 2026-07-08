#!/usr/bin/env python3
"""
Module: dude.triggers.store
Purpose: Append-only persistence for the Trigger Calibration Engine
         (trigger spec v1 §1/§10, same discipline as PomStore).

Trigger-engine records live under <root>/trigger_engine/, structurally
separate from case evidence: a case load never sees trigger records, so
assessments are excluded from the evidence fingerprint by construction
(R5) and calibration can never leak into a case stream. Same immutability
rules as the case store: append-only streams, supersede chains, never
overwrite. Revocation (R6d) is a superseding record with revoked=True and
a reason — nothing is ever deleted.

Safety Critical: True — a lost retrieval-audit write must abort the
retrieval (v1 §10: audit every trigger retrieval into a case).
Psychologically Critical: True

Never-suppress-error: all persistence failures raise StoreError with the
original cause; nothing is logged-and-ignored.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import logging
from dataclasses import dataclass, field

from dude.pom.contracts import RetrievalRecord
from dude.store.jsonl import CaseStore, StoreError, _resolve
from dude.triggers.contracts import (
    CalibrationPair,
    CalibrationPrompt,
    CaseTriggerAssessment,
    LegacyTriggerLink,
    PairContrastResult,
    PersonalTriggerProfile,
    TriggerCalibrationResponse,
    TriggerEvidence,
    TriggerFamily,
)

LOGGER = logging.getLogger("dude.triggers.store")

_TRIGGER_STREAMS: dict[type, str] = {
    TriggerFamily: "families",
    PersonalTriggerProfile: "profiles",
    TriggerCalibrationResponse: "calibration",
    TriggerEvidence: "evidence",
    CaseTriggerAssessment: "assessments",
    CalibrationPrompt: "prompts",
    CalibrationPair: "pairs",
    PairContrastResult: "contrasts",
    LegacyTriggerLink: "legacy_links",
    RetrievalRecord: "retrievals",
}


@dataclass
class TriggerBundle:
    """Loaded trigger-engine state, supersede chains resolved (retrievals
    and legacy links are audit logs and are never superseded)."""

    families: list[TriggerFamily] = field(default_factory=list)
    profiles: list[PersonalTriggerProfile] = field(default_factory=list)
    calibration: list[TriggerCalibrationResponse] = field(default_factory=list)
    evidence: list[TriggerEvidence] = field(default_factory=list)
    assessments: list[CaseTriggerAssessment] = field(default_factory=list)
    prompts: list[CalibrationPrompt] = field(default_factory=list)
    pairs: list[CalibrationPair] = field(default_factory=list)
    contrasts: list[PairContrastResult] = field(default_factory=list)
    legacy_links: list[LegacyTriggerLink] = field(default_factory=list)
    retrievals: list[RetrievalRecord] = field(default_factory=list)

    def families_by_slug(self) -> dict[str, TriggerFamily]:
        return {f.slug: f for f in self.families}

    def profiles_for(self, user_id: str) -> list[PersonalTriggerProfile]:
        """User scoping happens BEFORE anything else sees profiles
        (v1 §10: user-scoped before semantic search)."""
        return [p for p in self.profiles if p.user_id == user_id]

    def profile_for_family(
        self, user_id: str, family_slug: str
    ) -> PersonalTriggerProfile | None:
        for profile in self.profiles_for(user_id):
            if profile.family_slug == family_slug:
                return profile
        return None


class TriggerStore:
    """Trigger-engine streams on a CaseStore's root directory."""

    def __init__(self, case_store: CaseStore) -> None:
        self._store = case_store
        self._dir = case_store.root / "trigger_engine"
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError(f"Cannot create trigger-engine dir: {exc}") from exc

    def append(self, record: object) -> None:
        stream = _TRIGGER_STREAMS.get(type(record))
        if stream is None:
            raise StoreError(f"No trigger stream for {type(record).__name__}.")
        self._store._append_line(self._dir / f"{stream}.jsonl", record)  # noqa: SLF001

    def load(self) -> TriggerBundle:
        read = self._store._read  # noqa: SLF001
        return TriggerBundle(
            families=_resolve(read(self._dir / "families.jsonl", TriggerFamily)),
            profiles=_resolve(
                read(self._dir / "profiles.jsonl", PersonalTriggerProfile)
            ),
            calibration=_resolve(
                read(self._dir / "calibration.jsonl", TriggerCalibrationResponse)
            ),
            evidence=_resolve(read(self._dir / "evidence.jsonl", TriggerEvidence)),
            assessments=_resolve(
                read(self._dir / "assessments.jsonl", CaseTriggerAssessment)
            ),
            prompts=read(self._dir / "prompts.jsonl", CalibrationPrompt),
            pairs=read(self._dir / "pairs.jsonl", CalibrationPair),
            contrasts=read(self._dir / "contrasts.jsonl", PairContrastResult),
            legacy_links=read(self._dir / "legacy_links.jsonl", LegacyTriggerLink),
            retrievals=read(self._dir / "retrievals.jsonl", RetrievalRecord),
        )
