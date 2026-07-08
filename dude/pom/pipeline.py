#!/usr/bin/env python3
"""
Module: dude.pom.pipeline
Purpose: POM import pipeline (§15) and policy-filtered retrieval (§11–§12).

Import: immutable ingest -> segmentation -> atomic extraction (behind a
protocol; the Phase-1 stub refuses visibly) -> schema validation ->
persist. Extraction never freestyles a psychological profile: it is a
typed extraction job with provenance, and unconfirmed statuses import
unconfirmed (§13).

Retrieval: candidates -> policy filter -> contamination check -> audit
record -> context. NEVER nearest-vectors-into-prompt (§11): candidates
are only candidates; nothing reaches model context without passing
authorize() and writing a RetrievalRecord.

Safety Critical: True
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import logging
import uuid
from typing import Protocol

from dude.pom.contracts import (
    PROHIBITED_USES,
    AllowedUse,
    EpistemicStatus,
    PomCategory,
    PomItem,
    RetrievalRecord,
    SourceArtifact,
    UNCONFIRMED_ON_IMPORT,
)
from dude.pom.policy import PolicyViolation, authorize
from dude.pom.store import PomStore

LOGGER = logging.getLogger("dude.pom.pipeline")


class ExtractionUnavailable(Exception):
    """No extractor is configured; the ingest persists, extraction refuses."""


class PomExtractor(Protocol):
    """Atomic extraction contract. Live implementations run behind the
    model router and must classify by ACTUAL provenance (§3)."""

    def extract(self, artifact: SourceArtifact) -> list[PomItem]: ...


class StubExtractor:
    """Phase-1 stub: refuses visibly (v0.2 I12). The source is still
    ingested and hashed; extraction runs when a model is configured."""

    def extract(self, artifact: SourceArtifact) -> list[PomItem]:  # noqa: ARG002
        raise ExtractionUnavailable(
            "No extraction model configured; source ingested immutably, "
            "extraction refused (no output fabricated)."
        )


def ingest_source(
    store: PomStore, user_id: str, title: str, content: str
) -> SourceArtifact:
    """Immutable ingest (§1). A re-import of the same title supersedes the
    prior artifact; nothing is ever overwritten."""
    existing = [a for a in store.load().source_artifacts if a.title == title]
    artifact = SourceArtifact(
        user_id=user_id,
        title=title,
        content=content,
        supersedes=existing[-1].id if existing else None,
    )
    store.append(artifact)
    return artifact


def validate_items(items: list[PomItem]) -> list[PomItem]:
    """Schema validation before persist (§13, §15). Provenance-based
    defaults are enforced structurally (contracts) — this re-checks the
    batch-level rules and fails closed on any violation."""
    for item in items:
        if not item.source_excerpt.strip():
            raise ValueError(f"Item {item.id} has no source excerpt (provenance).")
        if item.epistemic_status in UNCONFIRMED_ON_IMPORT and item.user_confirmed:
            raise ValueError(f"Item {item.id}: unconfirmed status marked confirmed.")
    return items


def import_source(
    store: PomStore,
    user_id: str,
    title: str,
    content: str,
    extractor: PomExtractor | None = None,
) -> tuple[SourceArtifact, list[PomItem]]:
    """The §15 import pipeline. Ingest always persists; extraction refuses
    without a configured extractor and never fabricates."""
    artifact = ingest_source(store, user_id, title, content)
    items = validate_items((extractor or StubExtractor()).extract(artifact))
    for item in items:
        store.append(item)
    return artifact, items


def confirm_item(store: PomStore, item: PomItem) -> PomItem:
    """User confirmation = a SUPERSEDING record with a confirmed status
    (§3/§13/§16) — never an in-place flag flip."""
    promoted = item.model_copy(
        update={
            "id": uuid.uuid4().hex,
            "supersedes": item.id,
            "user_confirmed": True,
            "epistemic_status": (
                EpistemicStatus.USER_CONFIRMED_PATTERN
                if item.epistemic_status in UNCONFIRMED_ON_IMPORT
                else item.epistemic_status
            ),
        }
    )
    store.append(promoted)
    return promoted


def retrieve(
    store: PomStore,
    *,
    case_id: str,
    analysis_run_id: str,
    use: AllowedUse | str,
    cues: list[str],
    reason: str,
) -> list[PomItem]:
    """Policy-filtered retrieval with mandatory audit (§11–§12).

    A prohibited or unknown `use` raises for the WHOLE call — there is no
    path where an evidence-class request degrades into a partial result.
    Candidate matching (Phase 1: cue substrings; semantic later) produces
    candidates ONLY; each retrieved item passes authorize() and writes a
    RetrievalRecord before anything is returned."""
    if isinstance(use, str) and use in PROHIBITED_USES:
        raise PolicyViolation(
            f"Use {use!r} is constitutionally prohibited: POM knowledge is "
            "never evidence about the external world (§5/§17)."
        )
    try:
        resolved = AllowedUse(use)
    except ValueError as exc:
        raise PolicyViolation(f"Unknown use {use!r}.") from exc
    bundle = store.load()
    lowered = [c.lower() for c in cues]
    retrieved: list[PomItem] = []
    # Defense against historical import duplicates (the pre-fix boot loop
    # re-imported the dataset per deploy): one retrieval per statement.
    seen_statements: set[str] = set()
    for item in bundle.items:
        norm = " ".join(item.statement.split()).lower()
        if norm in seen_statements:
            continue
        seen_statements.add(norm)
        try:
            authorize(item, resolved)
        except PolicyViolation:
            continue  # this item isn't allowed for this use; others may be
        if (
            item.category is PomCategory.HISTORICAL_CASE_CONTEXT
            and resolved is not AllowedUse.CASE_RETRIEVAL
        ):
            # §6: no historical case may silently corroborate a new case.
            continue
        haystack = f"{item.statement} {item.category.value}".lower()
        if lowered and not any(cue in haystack for cue in lowered):
            continue
        retrieved.append(item)
    for item in retrieved:
        store.append(
            RetrievalRecord(
                case_id=case_id,
                pom_item_id=item.id,
                analysis_run_id=analysis_run_id,
                retrieval_reason=reason,
                allowed_use=AllowedUse(use),
            )
        )
    return retrieved
