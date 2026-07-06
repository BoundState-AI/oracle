#!/usr/bin/env python3
"""
Module: dude.pom.store
Purpose: Append-only POM persistence on the CaseStore root (§1, §6).

POM records live under <root>/pom/, structurally separate from case
evidence (§6) — a case load never sees POM records and vice versa.
Same immutability rules as the case store: append-only streams,
supersede chains, never overwrite.

Safety Critical: True — a lost retrieval-audit write must abort the
retrieval (§12).
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

from dataclasses import dataclass, field

from dude.pom.contracts import (
    GroundingCoordinate,
    PomItem,
    RetrievalRecord,
    SourceArtifact,
    WorkingModel,
)
from dude.store.jsonl import CaseStore, StoreError, _resolve

_POM_STREAMS: dict[type, str] = {
    SourceArtifact: "source_artifacts",
    PomItem: "items",
    WorkingModel: "working_models",
    GroundingCoordinate: "grounding",
    RetrievalRecord: "retrievals",
}


@dataclass
class PomBundle:
    """Loaded POM state, supersede chains resolved (retrievals are an
    audit log and are never superseded)."""

    source_artifacts: list[SourceArtifact] = field(default_factory=list)
    items: list[PomItem] = field(default_factory=list)
    working_models: list[WorkingModel] = field(default_factory=list)
    grounding: list[GroundingCoordinate] = field(default_factory=list)
    retrievals: list[RetrievalRecord] = field(default_factory=list)


class PomStore:
    """POM streams on a CaseStore's root directory."""

    def __init__(self, case_store: CaseStore) -> None:
        self._store = case_store
        self._dir = case_store.root / "pom"
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError(f"Cannot create POM dir: {exc}") from exc

    def append(self, record: object) -> None:
        stream = _POM_STREAMS.get(type(record))
        if stream is None:
            raise StoreError(f"No POM stream for {type(record).__name__}.")
        self._store._append_line(self._dir / f"{stream}.jsonl", record)  # noqa: SLF001

    def load(self) -> PomBundle:
        read = self._store._read  # noqa: SLF001
        return PomBundle(
            source_artifacts=_resolve(
                read(self._dir / "source_artifacts.jsonl", SourceArtifact)
            ),
            items=_resolve(read(self._dir / "items.jsonl", PomItem)),
            working_models=_resolve(
                read(self._dir / "working_models.jsonl", WorkingModel)
            ),
            grounding=_resolve(
                read(self._dir / "grounding.jsonl", GroundingCoordinate)
            ),
            retrievals=read(self._dir / "retrievals.jsonl", RetrievalRecord),
        )
