#!/usr/bin/env python3
"""
Module: oracle.disposition.evidence
Purpose: Phase 2 evidence service — controlled artifacts, gates, multi-unit links.

v0 stores metadata + optional local path; content-addressed hash when file present.
Withdrawal/expiration marks linked units for re-review (via graph propagation).

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

LOGGER = logging.getLogger("oracle.disposition.evidence")

Confidentiality = Literal["public", "internal", "controlled", "export_controlled"]


class EvidenceArtifact(BaseModel):
    """Controlled evidence object (RDW §12) — not a bare comment link."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    doc_id: str
    revision: str
    title: str = ""
    scope: str = ""
    issuing_organization: str = ""
    effective_date: Optional[str] = None
    approval_date: Optional[str] = None
    expiration_date: Optional[str] = None
    confidentiality: Confidentiality = "internal"
    source_location: str = ""  # URI or local path descriptor
    content_hash: Optional[str] = None
    unit_ids: tuple[str, ...] = ()
    withdrawn: bool = False
    note: str = ""

    @field_validator("doc_id", "revision", "evidence_id")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("evidence identity fields must be non-blank")
        return str(v).strip()


class EvidenceGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    reasons: tuple[str, ...] = ()


def is_expired(art: EvidenceArtifact, as_of: Optional[str] = None) -> bool:
    if not art.expiration_date:
        return False
    try:
        exp = date.fromisoformat(art.expiration_date[:10])
        ref = date.fromisoformat((as_of or date.today().isoformat())[:10])
        return ref > exp
    except ValueError:
        return False


def evidence_supports_meet(art: EvidenceArtifact, as_of: Optional[str] = None) -> EvidenceGateResult:
    """Mandatory evidence gate for Meet / Meets Intent claims."""
    reasons: list[str] = []
    if art.withdrawn:
        reasons.append("evidence withdrawn")
    if is_expired(art, as_of):
        reasons.append(f"evidence expired on {art.expiration_date}")
    if not art.doc_id or not art.revision:
        reasons.append("missing doc_id or revision")
    if not art.effective_date and not art.approval_date:
        reasons.append("missing effective/approval date")
    return EvidenceGateResult(ok=len(reasons) == 0, reasons=tuple(reasons))


class EvidenceStore:
    """
    File-backed evidence registry under a session/evidence root.

    Layout:
      <root>/registry.jsonl
      <root>/blobs/<content_hash>/...
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry = self.root / "registry.jsonl"
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(exist_ok=True)
        if not self.registry.exists():
            self.registry.touch()

    def _append(self, art: EvidenceArtifact) -> None:
        with self.registry.open("a", encoding="utf-8") as f:
            f.write(art.model_dump_json() + "\n")

    def list_all(self) -> list[EvidenceArtifact]:
        out: list[EvidenceArtifact] = []
        if not self.registry.exists():
            return out
        # Last write wins per evidence_id
        by_id: dict[str, EvidenceArtifact] = {}
        with self.registry.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                art = EvidenceArtifact.model_validate_json(line)
                by_id[art.evidence_id] = art
        return list(by_id.values())

    def get(self, evidence_id: str) -> Optional[EvidenceArtifact]:
        for a in self.list_all():
            if a.evidence_id == evidence_id:
                return a
        return None

    def register(
        self,
        *,
        evidence_id: str,
        doc_id: str,
        revision: str,
        unit_ids: tuple[str, ...] = (),
        title: str = "",
        scope: str = "",
        issuing_organization: str = "",
        effective_date: Optional[str] = None,
        approval_date: Optional[str] = None,
        expiration_date: Optional[str] = None,
        confidentiality: Confidentiality = "internal",
        source_location: str = "",
        local_file: Optional[Path | str] = None,
        note: str = "",
    ) -> EvidenceArtifact:
        content_hash = None
        if local_file:
            p = Path(local_file)
            raw = p.read_bytes()
            content_hash = f"sha256:{hashlib.sha256(raw).hexdigest()}"
            dest = self.blobs / content_hash.replace(":", "_")
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / p.name)
            source_location = source_location or str(dest / p.name)
        art = EvidenceArtifact(
            evidence_id=evidence_id,
            doc_id=doc_id,
            revision=revision,
            title=title,
            scope=scope,
            issuing_organization=issuing_organization,
            effective_date=effective_date,
            approval_date=approval_date,
            expiration_date=expiration_date,
            confidentiality=confidentiality,
            source_location=source_location,
            content_hash=content_hash,
            unit_ids=unit_ids,
            note=note,
        )
        self._append(art)
        LOGGER.info("Registered evidence %s for units %s", evidence_id, unit_ids)
        return art

    def withdraw(self, evidence_id: str) -> EvidenceArtifact:
        prior = self.get(evidence_id)
        if prior is None:
            raise KeyError(evidence_id)
        new = prior.model_copy(update={"withdrawn": True})
        self._append(new)
        return new

    def known_doc_ids(self) -> set[str]:
        return {a.doc_id for a in self.list_all() if not a.withdrawn}

    def for_unit(self, unit_id: str) -> list[EvidenceArtifact]:
        return [a for a in self.list_all() if unit_id in a.unit_ids and not a.withdrawn]

    def unit_has_qualifying_meet_evidence(
        self, unit_id: str, as_of: Optional[str] = None
    ) -> bool:
        for a in self.for_unit(unit_id):
            if evidence_supports_meet(a, as_of).ok:
                return True
        return False

    def expired_or_withdrawn_unit_ids(self, as_of: Optional[str] = None) -> list[str]:
        units: set[str] = set()
        for a in self.list_all():
            if a.withdrawn or is_expired(a, as_of):
                units.update(a.unit_ids)
        return sorted(units)
