#!/usr/bin/env python3
"""
Module: hearth.ingest.larimer_assessor
Purpose: Larimer County assessor bulk-export adapter (spec v0.3 §4;
         §13 P2-C). File-based: the operator downloads the county's bulk
         export and feeds the file — no live network in Phase 2.

Expected CSV columns (assessor bulk-export shape, SYNTHETIC fixtures mirror
it): account_id, parcel_number, situs_address, situs_city, situs_zip,
latitude, longitude, total_mill_levy, metro_district_mill_levy,
tax_district, last_sale_price, last_sale_date.

Missing columns, unparseable numbers, or an empty file raise IngestError —
a malformed export must never shrink to "fewer properties".

Safety Critical: False
Financially Critical: True — assessor rows anchor identity and tax-burden
  landmines; never-suppress-error applies.

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
from datetime import date
from pathlib import Path

from hearth.data.rights import DataRightsRow
from hearth.ingest.base import IngestBatch, IngestError, RawPropertyRecord, validate_batch

LOGGER = logging.getLogger("hearth.ingest.larimer_assessor")

SOURCE_ID = "larimer-assessor"

REQUIRED_COLUMNS = (
    "account_id",
    "parcel_number",
    "situs_address",
    "situs_city",
    "situs_zip",
    "latitude",
    "longitude",
    "total_mill_levy",
    "metro_district_mill_levy",
    "tax_district",
    "last_sale_price",
    "last_sale_date",
)

# §4.1: declared BEFORE the adapter is buildable; verified=False until the
# founder/legal confirms the posture against the county's actual terms.
RIGHTS = DataRightsRow(
    source="Larimer County Assessor bulk export (larimer.gov/assessor)",
    access="public bulk export, file supplied by the operator (no live API in P2)",
    allowed_fields=[
        "total_mill_levy",
        "metro_district_mill_levy",
        "tax_district",
        "last_sale_price",
        "last_sale_date",
    ],
    storage_ttl_days=None,
    derived_use="tax-burden analysis, comparable anchoring, landmine thresholds",
    display_limits="public-record data; cite assessor + retrieval date on display",
    auth_obligations="none identified for public bulk export",
    audit_obligations="retain source file hash with ingest provenance (§11)",
    fallback="degrade to buyer-supplied documents (§4.1)",
    confidence_tier=0.95,  # §4 source table: county assessor
    declared_by="Dr. Joseph Wilde (founder declaration)",
    declared_on=date(2026, 6, 12),
    verified=False,
)


class LarimerAssessorAdapter:
    """Parses the assessor bulk CSV into property records."""

    source_id = SOURCE_ID
    rights = RIGHTS

    def parse(self, path: Path) -> IngestBatch:
        rows = _read_csv(path)
        records = [
            _record_from_row(row, line)
            for line, row in enumerate(rows, start=2)  # 1-based + header line
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


def _record_from_row(row: dict[str, str], line: int) -> RawPropertyRecord:
    try:
        return RawPropertyRecord(
            parcel_id=row["parcel_number"].strip(),
            address_raw=row["situs_address"].strip(),
            city=row["situs_city"].strip() or None,
            zip_code=row["situs_zip"].strip() or None,
            lat=float(row["latitude"]),
            lon=float(row["longitude"]),
            fields={
                "total_mill_levy": float(row["total_mill_levy"]),
                "metro_district_mill_levy": float(row["metro_district_mill_levy"]),
                "tax_district": row["tax_district"].strip(),
                "last_sale_price": int(row["last_sale_price"]),
                "last_sale_date": row["last_sale_date"].strip(),
            },
        )
    except (KeyError, ValueError) as exc:
        raise IngestError(
            f"{SOURCE_ID}: line {line} is malformed ({exc}) — refusing the file"
        ) from exc
