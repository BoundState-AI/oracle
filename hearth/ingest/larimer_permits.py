#!/usr/bin/env python3
"""
Module: hearth.ingest.larimer_permits
Purpose: Larimer County permit-history bulk-export adapter (spec v0.3 §4;
         §13 P2-C). File-based, like the assessor adapter.

Expected CSV columns: permit_number, parcel_number, address, issued_date,
permit_type, valuation, status. Permits aggregate per parcel into evidence
fields (permit_count_total, last_permit_date, permit_types) — permit
history is the §9 #4 MVP proxy for property condition.

Safety Critical: False
Financially Critical: True — permit history is the condition proxy;
  never-suppress-error applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import csv
import logging
from collections import defaultdict
from datetime import date
from pathlib import Path

from hearth.data.rights import DataRightsRow
from hearth.ingest.base import IngestBatch, IngestError, RawPropertyRecord, validate_batch

LOGGER = logging.getLogger("hearth.ingest.larimer_permits")

SOURCE_ID = "larimer-permits"

REQUIRED_COLUMNS = (
    "permit_number",
    "parcel_number",
    "address",
    "issued_date",
    "permit_type",
    "valuation",
    "status",
)

RIGHTS = DataRightsRow(
    source="Larimer County building permit portal bulk export (larimer.gov)",
    access="public portal export, file supplied by the operator (no live API in P2)",
    allowed_fields=["permit_count_total", "last_permit_date", "permit_types"],
    storage_ttl_days=None,
    derived_use="property-condition proxy (spec §9 #4 MVP posture)",
    display_limits="public-record data; cite county portal + retrieval date",
    auth_obligations="none identified for public export",
    audit_obligations="retain source file hash with ingest provenance (§11)",
    fallback="degrade to buyer-supplied documents (§4.1)",
    confidence_tier=0.90,  # §4 source table: county permits
    declared_by="Dr. Joseph Wilde (founder declaration)",
    declared_on=date(2026, 6, 12),
    verified=False,
)


class LarimerPermitsAdapter:
    """Aggregates the permits CSV into per-parcel evidence records."""

    source_id = SOURCE_ID
    rights = RIGHTS

    def parse(self, path: Path) -> IngestBatch:
        rows = _read_csv(path)
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        addresses: dict[str, str] = {}
        for line, row in enumerate(rows, start=2):
            parcel = row.get("parcel_number", "").strip()
            if not parcel:
                raise IngestError(
                    f"{SOURCE_ID}: line {line} has no parcel_number — refusing the file"
                )
            _validate_row(row, line)
            grouped[parcel].append(row)
            addresses.setdefault(parcel, row["address"].strip())

        records = [
            _aggregate(parcel, permits, addresses[parcel])
            for parcel, permits in sorted(grouped.items())
        ]
        return validate_batch(
            IngestBatch(
                source_id=self.source_id,
                rights=self.rights,
                records=records,
                retrieved=date.today(),
            )
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                raise IngestError(
                    f"{SOURCE_ID}: {path.name} is missing required columns: {missing}"
                )
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise IngestError(f"{SOURCE_ID}: cannot read {path.name}: {exc}") from exc


def _validate_row(row: dict[str, str], line: int) -> None:
    try:
        date.fromisoformat(row["issued_date"].strip())
        float(row["valuation"])
    except (KeyError, ValueError) as exc:
        raise IngestError(
            f"{SOURCE_ID}: line {line} is malformed ({exc}) — refusing the file"
        ) from exc


def _aggregate(
    parcel: str, permits: list[dict[str, str]], address: str
) -> RawPropertyRecord:
    issued = sorted(row["issued_date"].strip() for row in permits)
    types = sorted({row["permit_type"].strip() for row in permits})
    return RawPropertyRecord(
        parcel_id=parcel,
        address_raw=address,
        fields={
            "permit_count_total": len(permits),
            "last_permit_date": issued[-1],
            "permit_types": ", ".join(types),
        },
    )
