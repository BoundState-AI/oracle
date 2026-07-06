#!/usr/bin/env python3
"""
Module: dude.store.jsonl
Purpose: Append-only JSONL case store (spec v0.2 I11, §6).

Records are immutable: files are opened append-only and never rewritten.
A correction is a new record whose `supersedes` field points at the old
one; loading resolves chains by dropping superseded records. A
user-confirmed record can never be overwritten by machine output because
nothing here overwrites anything.

This is the Phase-1 single-tenant implementation of the store interface;
a Postgres adapter must add nothing this interface doesn't already
require. Layout:

    <root>/triggers.jsonl            — user trigger profile
    <root>/cases/<case_id>/<stream>.jsonl

Safety Critical: True — a failed safety_events append must abort the
caller's run (never-suppress-error: failures raise StoreError with the
original cause; nothing is logged-and-ignored).
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from dude.data import (
    AnalysisRun,
    Artifact,
    Capture,
    Case,
    DudeModel,
    Event,
    Hypothesis,
    Interpretation,
    Observation,
    Outcome,
    SafetyEvent,
    TriggerPattern,
    Unknown,
)
from dude.data.actions import ActionEvaluation, ActionOption

LOGGER = logging.getLogger("dude.store.jsonl")

M = TypeVar("M", bound=DudeModel)

# Stream name per record type. One stream per type keeps loads simple and
# makes the append-only property auditable with `wc -l`.
_STREAMS: dict[type, str] = {
    Case: "case",
    Capture: "captures",
    Artifact: "artifacts",
    Event: "events",
    Observation: "observations",
    Interpretation: "interpretations",
    Unknown: "unknowns",
    Hypothesis: "hypotheses",
    ActionOption: "action_options",
    ActionEvaluation: "action_evaluations",
    Outcome: "outcomes",
    SafetyEvent: "safety_events",
    AnalysisRun: "analysis_runs",
}


class StoreError(Exception):
    """Any persistence failure. Callers treat this as a refusal."""


@dataclass
class CaseBundle:
    """Everything loaded for one case, supersede chains resolved."""

    case: Case
    captures: list[Capture] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    interpretations: list[Interpretation] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    action_options: list[ActionOption] = field(default_factory=list)
    action_evaluations: list[ActionEvaluation] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    safety_events: list[SafetyEvent] = field(default_factory=list)
    analysis_runs: list[AnalysisRun] = field(default_factory=list)

    def all_text(self) -> str:
        """Concatenated user-facing material for trigger matching and the
        analysis-time safety scan."""
        parts = [c.text for c in self.captures]
        parts.extend(e.description for e in self.events)
        parts.extend(i.statement for i in self.interpretations)
        return "\n".join(parts)


class CaseStore:
    """Append-only store rooted at a directory ($DUDE_HOME or ~/.dude)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.environ.get("DUDE_HOME", Path.home() / ".dude"))
        try:
            (self.root / "cases").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError(f"Cannot create store root {self.root}: {exc}") from exc

    # -- writes ------------------------------------------------------------

    def create_case(self, case: Case) -> None:
        case_dir = self._case_dir(case.id)
        if case_dir.exists():
            raise StoreError(f"Case {case.id} already exists.")
        try:
            case_dir.mkdir(parents=True)
        except OSError as exc:
            raise StoreError(f"Cannot create case dir: {exc}") from exc
        self.append(case)

    def append(self, record: DudeModel) -> None:
        """Append one record to its stream. Raises StoreError on any
        failure — a lost write must abort the caller, never pass silently."""
        stream = _STREAMS.get(type(record))
        if stream is None:
            raise StoreError(f"No stream for record type {type(record).__name__}.")
        case_id = getattr(record, "case_id", None) or getattr(record, "id", None)
        if isinstance(record, Case):
            path = self._case_dir(record.id) / "case.jsonl"
        else:
            if case_id is None or not self._case_dir(str(case_id)).exists():
                raise StoreError(
                    f"Cannot append {type(record).__name__}: case {case_id!r} "
                    "does not exist (no orphan records)."
                )
            path = self._case_dir(str(case_id)) / f"{stream}.jsonl"
        self._append_line(path, record)

    def append_trigger(self, trigger: TriggerPattern) -> None:
        self._append_line(self.root / "triggers.jsonl", trigger)

    # -- reads -------------------------------------------------------------

    def load_case(self, case_id: str) -> CaseBundle:
        case_dir = self._case_dir(case_id)
        if not case_dir.exists():
            raise StoreError(f"Case {case_id} does not exist.")
        cases = self._read(case_dir / "case.jsonl", Case)
        if not cases:
            raise StoreError(f"Case {case_id} has no case record.")
        return CaseBundle(
            case=cases[-1],  # latest case record wins (title/status edits append)
            captures=self._read(case_dir / "captures.jsonl", Capture),
            artifacts=self._read(case_dir / "artifacts.jsonl", Artifact),
            events=_resolve(self._read(case_dir / "events.jsonl", Event)),
            observations=_resolve(
                self._read(case_dir / "observations.jsonl", Observation)
            ),
            interpretations=_resolve(
                self._read(case_dir / "interpretations.jsonl", Interpretation)
            ),
            unknowns=self._read(case_dir / "unknowns.jsonl", Unknown),
            hypotheses=_resolve(self._read(case_dir / "hypotheses.jsonl", Hypothesis)),
            action_options=self._read(case_dir / "action_options.jsonl", ActionOption),
            action_evaluations=self._read(
                case_dir / "action_evaluations.jsonl", ActionEvaluation
            ),
            outcomes=self._read(case_dir / "outcomes.jsonl", Outcome),
            safety_events=self._read(case_dir / "safety_events.jsonl", SafetyEvent),
            analysis_runs=self._read(case_dir / "analysis_runs.jsonl", AnalysisRun),
        )

    def list_case_ids(self) -> list[str]:
        return sorted(p.name for p in (self.root / "cases").iterdir() if p.is_dir())

    def load_triggers(self) -> list[TriggerPattern]:
        return self._read(self.root / "triggers.jsonl", TriggerPattern)

    # -- internals ----------------------------------------------------------

    def _case_dir(self, case_id: str) -> Path:
        return self.root / "cases" / case_id

    def _append_line(self, path: Path, record: DudeModel) -> None:
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
        except OSError as exc:
            LOGGER.error("Append to %s failed: %s", path, exc)
            raise StoreError(f"Append to {path.name} failed: {exc}") from exc

    def _read(self, path: Path, model: type[M]) -> list[M]:
        if not path.exists():
            return []
        records: list[M] = []
        line_no = 0
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, 1):
                    if line.strip():
                        records.append(model.model_validate(json.loads(line)))
        except (OSError, ValueError) as exc:
            # Never-suppress: a corrupt store is a refusal, not a partial load.
            raise StoreError(f"Reading {path} failed at line {line_no}: {exc}") from exc
        return records


def _resolve(records: list[M]) -> list[M]:
    """Drop superseded records (v0.2 I11): the latest link of each chain
    survives; order of surviving records is preserved."""
    superseded = {
        getattr(r, "supersedes") for r in records if getattr(r, "supersedes", None)
    }
    return [r for r in records if getattr(r, "id") not in superseded]
