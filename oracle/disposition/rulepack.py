#!/usr/bin/env python3
"""
Module: oracle.disposition.rulepack
Purpose: Load builtin NASA-STD-6030 pack into requirement records (RDW §9.1).

Actor/trigger fields are machine-extracted CANDIDATES — never silent facts.
Pack content hash pins the levy (refuses silent repin without --repin).

Safety Critical: advisory-only per spec D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

LOGGER = logging.getLogger("oracle.disposition.rulepack")

BUILTIN_NASA_6030 = (
    Path(__file__).resolve().parents[1] / "builtin_packs" / "nasa_std_6030_rulepack.json"
)


class CandidateField(BaseModel):
    """Machine-extracted candidate — interview must confirm before it is a fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    machine_extracted: bool = True
    confirmed: bool = False


class RequirementLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    standard: str
    revision: str
    section: str
    page: Optional[int] = None


class RequirementRecord(BaseModel):
    """RDW §9.1 requirement record (disposition-facing, not pack mutation)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    rule_pack_id: str
    pack_content_hash: str
    shall_text: str
    locator: RequirementLocator
    actor_candidate: Optional[CandidateField] = None
    trigger_candidates: tuple[CandidateField, ...] = ()
    keywords: tuple[str, ...] = ()
    authority_dependent: bool = False
    source_tag: Optional[str] = None
    # Stage 0: curated pack rationale / guidance for advisor grounding
    rationale: str = ""
    notes: str = ""
    source_hash: Optional[str] = None  # PDF source pin when curated


class DependencyEdge(BaseModel):
    """Human-authored dependency seed (not auto-extracted)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prerequisite_id: str
    dependent_id: str
    kind: str  # classification | plan | control
    note: str = ""


# Human-authored dependency seeds (extendable; not full auto-extraction)
DEPENDENCY_SEEDS: tuple[DependencyEdge, ...] = (
    # Classification (AMR-5/6/8/10/11/12) gates class-conditional requirements
    DependencyEdge(
        prerequisite_id="AMR-5",
        dependent_id="AMR-17",
        kind="classification",
        note="Primary class gates quantitative NDE",
    ),
    DependencyEdge(
        prerequisite_id="AMR-6",
        dependent_id="AMR-17",
        kind="classification",
        note="Secondary class / fracture inputs",
    ),
    DependencyEdge(
        prerequisite_id="AMR-8",
        dependent_id="AMR-17",
        kind="classification",
        note="Classification package completeness",
    ),
    DependencyEdge(
        prerequisite_id="AMR-10",
        dependent_id="AMR-18",
        kind="classification",
        note="Class-conditional special NDE",
    ),
    DependencyEdge(
        prerequisite_id="AMR-11",
        dependent_id="AMR-18",
        kind="classification",
        note="Class-conditional special NDE",
    ),
    DependencyEdge(
        prerequisite_id="AMR-12",
        dependent_id="AMR-18",
        kind="classification",
        note="Class-conditional special NDE",
    ),
    # AMCP (AMR-2) gates references to it
    DependencyEdge(
        prerequisite_id="AMR-2",
        dependent_id="AMR-3",
        kind="plan",
        note="AMCP presence gates AMCP-referenced rows",
    ),
    # EFCP (AMR-14 → 6033)
    DependencyEdge(
        prerequisite_id="AMR-14",
        dependent_id="EFCR-1",
        kind="control",
        note="EFCP / 6033 matrix gates EFCR chain",
    ),
)


class PackPinError(ValueError):
    """Pack content hash does not match the session pin (needs --repin)."""


def content_hash_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def content_hash_path(path: Path | str) -> str:
    p = Path(path)
    return content_hash_bytes(p.read_bytes())


def _normalize_req_id(raw: str) -> str:
    """Normalize pack ids like 'amr-1' → 'AMR-1'."""
    s = (raw or "").strip()
    if not s:
        return s
    # AMR 1 / amr-1 / AMR-1
    s = s.replace(" ", "-")
    parts = s.split("-", 1)
    if len(parts) == 2:
        return f"{parts[0].upper()}-{parts[1]}"
    return s.upper()


def _authority_dependent(req: dict[str, Any]) -> bool:
    text = (req.get("shall_text") or "") + " " + (req.get("source_tag") or "")
    markers = (
        "Technical Authority",
        "tailoring",
        "CEO",
        "delegated",
        "concurrence",
    )
    return any(m.lower() in text.lower() for m in markers)


def load_requirement_records(
    pack_path: Path | str | None = None,
    *,
    expected_hash: Optional[str] = None,
    repin: bool = False,
) -> tuple[list[RequirementRecord], str]:
    """
    Load the builtin (or given) pack into requirement records.

    Returns (records, content_hash). If expected_hash is set and differs,
    raises PackPinError unless repin=True.
    """
    path = Path(pack_path) if pack_path else BUILTIN_NASA_6030
    raw = path.read_bytes()
    digest = content_hash_bytes(raw)
    if expected_hash is not None and expected_hash != digest and not repin:
        raise PackPinError(
            f"Pack content hash mismatch: session pin={expected_hash} "
            f"file={digest}. Pass repin=True / --repin to re-pin."
        )

    data = json.loads(raw.decode("utf-8"))
    pack_id = str(data.get("rule_pack_id") or data.get("standard_id") or path.stem)
    standard = str(data.get("standard_id") or "NASA-STD-6030")
    revision = str(data.get("version") or data.get("revision") or "Baseline")
    reqs = data.get("requirements") or []

    records: list[RequirementRecord] = []
    for req in reqs:
        rid = _normalize_req_id(str(req.get("id") or req.get("source_tag") or ""))
        if not rid:
            continue
        shall = (req.get("shall_text") or "").strip()
        if not shall:
            continue
        section = str(req.get("section") or "unknown")
        page = req.get("page")
        page_i = int(page) if page is not None and str(page).isdigit() else None

        actor_raw = req.get("subject") or req.get("actor")
        actor_cand = (
            CandidateField(value=str(actor_raw), machine_extracted=True, confirmed=False)
            if actor_raw
            else None
        )
        triggers: list[CandidateField] = []
        applies = req.get("applies_to") or req.get("triggers") or []
        if isinstance(applies, str):
            applies = [applies]
        for t in applies:
            triggers.append(
                CandidateField(value=str(t), machine_extracted=True, confirmed=False)
            )
        kws = req.get("keywords") or []
        if isinstance(kws, str):
            kws = [kws]

        rationale = str(
            req.get("rationale") or req.get("justification") or ""
        ).strip()
        notes = str(req.get("notes") or req.get("context") or "").strip()
        # Prefer explicit page; also accept source_coordinates.page
        if page_i is None:
            sc = req.get("source_coordinates") or {}
            if isinstance(sc, dict) and sc.get("page") is not None:
                try:
                    page_i = int(sc["page"])
                except (TypeError, ValueError):
                    page_i = None

        records.append(
            RequirementRecord(
                requirement_id=rid,
                rule_pack_id=pack_id,
                pack_content_hash=digest,
                shall_text=shall,
                locator=RequirementLocator(
                    standard=standard,
                    revision=revision,
                    section=section,
                    page=page_i,
                ),
                actor_candidate=actor_cand,
                trigger_candidates=tuple(triggers),
                keywords=tuple(str(k) for k in kws),
                authority_dependent=_authority_dependent(req),
                source_tag=req.get("source_tag"),
                rationale=rationale,
                notes=notes,
                source_hash=data.get("source_hash"),
            )
        )

    LOGGER.info(
        "Loaded %d requirement records from %s (hash=%s)",
        len(records),
        path,
        digest,
    )
    return records, digest


def dependency_seeds_for(requirement_id: str) -> list[DependencyEdge]:
    """Return seeds where this requirement is the dependent."""
    rid = _normalize_req_id(requirement_id)
    return [e for e in DEPENDENCY_SEEDS if _normalize_req_id(e.dependent_id) == rid]


def prerequisites_of(requirement_id: str) -> list[str]:
    return [e.prerequisite_id for e in dependency_seeds_for(requirement_id)]
