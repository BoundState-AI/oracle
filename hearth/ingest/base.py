#!/usr/bin/env python3
"""
Module: hearth.ingest.base
Purpose: Ingest adapter contract — bulk-file sources only in Phase 2
         (spec v0.3 §4, §4.1; §13 P2-C).

An adapter turns one bulk export file into RawPropertyRecords under a
declared DataRightsRow. Two invariants are enforced HERE so no adapter can
forget them:
  1. No rights row, no ingest (§4.1: declaration precedes buildability).
  2. No record may carry an evidence field outside the declared
     allowed_fields — an adapter that drifts past its declaration fails
     the batch, it does not quietly widen it.

Everything fails CLOSED: malformed input raises IngestError; there is no
partial-success return shape.

Safety Critical: False
Financially Critical: True — ingest provenance is what lets every
  downstream number cite a row (§6); never-suppress-error applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from hearth.data.rights import DataRightsRow

LOGGER = logging.getLogger("hearth.ingest.base")


class IngestError(Exception):
    """Source file unusable; caller must fail CLOSED."""


@dataclass(frozen=True)
class RawPropertyRecord:
    """One property's worth of fields from one source file."""

    parcel_id: str
    address_raw: str
    city: str | None = None
    zip_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    # Evidence fields (field name -> value); names must be ⊆ the adapter's
    # declared allowed_fields.
    fields: dict[str, int | float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestBatch:
    """The validated output of one adapter run over one file."""

    source_id: str
    rights: DataRightsRow
    records: list[RawPropertyRecord]
    retrieved: date


@runtime_checkable
class IngestAdapter(Protocol):
    """A bulk-file source adapter (§13 P2-C)."""

    source_id: str
    rights: DataRightsRow

    def parse(self, path: Path) -> IngestBatch:
        """Parse the export file or raise IngestError."""
        ...  # pragma: no cover - protocol definition


def validate_batch(batch: IngestBatch) -> IngestBatch:
    """Enforce the §4.1 declaration over a parsed batch (fail CLOSED)."""
    if not batch.records:
        raise IngestError(f"{batch.source_id}: file yielded zero records")
    allowed = set(batch.rights.allowed_fields)
    for record in batch.records:
        stray = set(record.fields) - allowed
        if stray:
            raise IngestError(
                f"{batch.source_id}: parcel {record.parcel_id} carries fields "
                f"outside the declared data-rights row: {sorted(stray)}"
            )
        if not record.parcel_id.strip():
            raise IngestError(
                f"{batch.source_id}: record with empty parcel id "
                f"(address {record.address_raw!r}) — identity cannot anchor"
            )
    LOGGER.info(
        "validated batch: %s, %d records, rights declared by %s (verified=%s)",
        batch.source_id,
        len(batch.records),
        batch.rights.declared_by,
        batch.rights.verified,
    )
    return batch
