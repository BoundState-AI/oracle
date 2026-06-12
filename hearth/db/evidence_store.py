#!/usr/bin/env python3
"""
Module: hearth.db.evidence_store
Purpose: Filesystem PropertyIdentity + PropertyEvidence store (spec v0.3
         §2.3, §6; §13 P2-C — no DB in Phase 2).

Two JSONL files per store: identities.jsonl (upsert-by-uid) and
evidence.jsonl (append-only, full provenance: source, retrieved,
confidence) so every downstream number can cite a row (§6).

THE join guard lives here: evidence reads for an identity whose
match_confidence is below JOIN_CONFIDENCE_THRESHOLD raise
LowConfidenceJoinError unless the identity carries manual_override — no
silent merges (§2.3). A corrupt store line is an error, never a skipped
record.

Safety Critical: False
Financially Critical: True — a silent bad join prices the wrong house;
  never-suppress-error applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
from pathlib import Path

from pydantic import ValidationError

from hearth.data import PropertyEvidence, PropertyIdentity

LOGGER = logging.getLogger("hearth.db.evidence_store")

# §2.3: below this, comp/permit/landmine joins are blocked until the
# identity is resolved or manually overridden.
JOIN_CONFIDENCE_THRESHOLD = 0.90

IDENTITIES_FILE = "identities.jsonl"
EVIDENCE_FILE = "evidence.jsonl"


class EvidenceStoreError(Exception):
    """Store unusable or query invalid; caller must fail CLOSED."""


class LowConfidenceJoinError(EvidenceStoreError):
    """Identity confidence too low to trust evidence joins (§2.3)."""


class EvidenceStore:
    """Append-only evidence + upserted identities on the local filesystem."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EvidenceStoreError(f"cannot create store at {root}: {exc}") from exc

    # -- identities ---------------------------------------------------------

    def upsert_identity(self, identity: PropertyIdentity) -> None:
        identities = {i.property_uid: i for i in self.identities()}
        identities[identity.property_uid] = identity
        path = self.root / IDENTITIES_FILE
        try:
            with path.open("w", encoding="utf-8") as handle:
                for record in sorted(identities.values(), key=lambda i: i.property_uid):
                    handle.write(record.model_dump_json() + "\n")
        except OSError as exc:
            raise EvidenceStoreError(f"cannot write {path}: {exc}") from exc

    def identities(self) -> list[PropertyIdentity]:
        return self._read_jsonl(self.root / IDENTITIES_FILE, PropertyIdentity)

    def get_identity(self, property_uid: str) -> PropertyIdentity | None:
        for identity in self.identities():
            if identity.property_uid == property_uid:
                return identity
        return None

    # -- evidence -----------------------------------------------------------

    def add_evidence(self, row: PropertyEvidence) -> None:
        path = self.root / EVIDENCE_FILE
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(row.model_dump_json() + "\n")
        except OSError as exc:
            raise EvidenceStoreError(f"cannot append to {path}: {exc}") from exc

    def evidence_for(
        self,
        property_uid: str,
        field: str | None = None,
        *,
        allow_low_confidence: bool = False,
    ) -> list[PropertyEvidence]:
        """Evidence rows for one property, join-guarded (§2.3)."""
        identity = self.get_identity(property_uid)
        if identity is None:
            raise EvidenceStoreError(f"unknown property_uid {property_uid!r}")
        if (
            identity.match_confidence < JOIN_CONFIDENCE_THRESHOLD
            and not identity.manual_override
            and not allow_low_confidence
        ):
            raise LowConfidenceJoinError(
                f"identity {property_uid} has match_confidence "
                f"{identity.match_confidence:.2f} < {JOIN_CONFIDENCE_THRESHOLD} — "
                "resolve the identity or set manual_override before joining "
                "evidence (§2.3: no silent merges)"
            )
        rows = [
            row
            for row in self._read_jsonl(self.root / EVIDENCE_FILE, PropertyEvidence)
            if row.property_uid == property_uid
        ]
        if field is not None:
            rows = [row for row in rows if row.field == field]
        return rows

    # -- shared -------------------------------------------------------------

    def _read_jsonl(self, path: Path, model_cls):
        if not path.is_file():
            return []
        results = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise EvidenceStoreError(f"cannot read {path}: {exc}") from exc
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                results.append(model_cls.model_validate_json(line))
            except ValidationError as exc:
                # A corrupt row is a store-integrity event, not a skippable
                # record: silently dropping it could hide a landmine.
                raise EvidenceStoreError(
                    f"{path}:{number} is corrupt ({model_cls.__name__}): {exc}"
                ) from exc
        return results
