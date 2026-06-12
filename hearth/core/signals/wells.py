#!/usr/bin/env python3
"""
Module: hearth.core.signals.wells
Purpose: ECMC well-proximity evidence — wells_within_radius / nearest_well_ft
         per stored identity (spec v0.3 §4; §14 P3-B).

Consumes the ECMC well surface-location export (statewide, updated daily;
SHP converted to CSV) and computes, for every identity with a real
geocode, how many non-plugged wells sit within the configured radius
(default 2,000 ft — the ECMC Rule 604 location-standard framework) plus
the distance to the nearest one. Great-circle distance via haversine; at
parcel scale the spherical-earth error is < 0.5%, far inside the data's
own positional noise.

Fail CLOSED: malformed CSV, missing columns, unparseable coordinates, or
an identity set with no usable geocodes all raise — a wrong well count is
exactly the landmine this exists to defuse.

Safety Critical: False
Financially Critical: True

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
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hearth.data import PropertyEvidence
from hearth.data.rights import DataRightsRow
from hearth.db.evidence_store import EvidenceStore

LOGGER = logging.getLogger("hearth.core.signals.wells")

DEFAULT_RADIUS_FT = 2000  # ECMC Rule 604 location-standard framework
EARTH_RADIUS_FT = 20_902_231.0  # mean Earth radius in feet

# ECMC facility-status codes counted as proximity-relevant. PA (plugged &
# abandoned) is excluded; AB (abandoned, plugging status unverified) is
# deliberately INCLUDED — unverified plugging is the §2.2 rule's concern.
COUNTED_STATUSES = frozenset({"AC", "PR", "SI", "TA", "DG", "WO", "AB", "DM"})

REQUIRED_COLUMNS = ("api", "well_name", "latitude", "longitude", "facil_stat", "county")

RIGHTS = DataRightsRow(
    source="ECMC well surface locations download (ecmc.colorado.gov, updated daily)",
    access="public bulk download, file supplied by the operator (SHP->CSV)",
    allowed_fields=["wells_within_radius", "nearest_well_ft"],
    storage_ttl_days=None,
    derived_use="well-proximity landmine evaluation (ECMC Rule 604 framework)",
    display_limits="public-record data; cite ECMC + retrieval date",
    auth_obligations="none identified for public download",
    audit_obligations="retain source file hash with ingest provenance (§11)",
    fallback="degrade to buyer-supplied well observations",
    confidence_tier=0.90,
    declared_by="Dr. Joseph Wilde (founder declaration)",
    declared_on=date(2026, 6, 12),
    verified=False,
)


class WellsError(Exception):
    """Wells file or geometry unusable; caller must fail CLOSED."""


@dataclass(frozen=True)
class WellRecord:
    api: str
    well_name: str
    lat: float
    lon: float
    status: str
    county: str


def parse_wells_csv(path: Path) -> list[WellRecord]:
    """Parse the ECMC-schema wells CSV; WellsError on any defect."""
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = [h.lower() for h in (reader.fieldnames or [])]
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                raise WellsError(f"{path.name} is missing required columns: {missing}")
            rows = [{k.lower(): v for k, v in row.items()} for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise WellsError(f"cannot read {path.name}: {exc}") from exc
    if not rows:
        raise WellsError(f"{path.name} contains zero wells")
    records: list[WellRecord] = []
    seen_apis: set[str] = set()
    for line, row in enumerate(rows, start=2):
        try:
            record = WellRecord(
                api=row["api"].strip(),
                well_name=row["well_name"].strip(),
                lat=float(row["latitude"]),
                lon=float(row["longitude"]),
                status=row["facil_stat"].strip().upper(),
                county=row["county"].strip(),
            )
        except (KeyError, ValueError) as exc:
            raise WellsError(f"{path.name} line {line} is malformed ({exc})") from exc
        if not (-90.0 <= record.lat <= 90.0 and -180.0 <= record.lon <= 180.0):
            # Out-of-range coordinates also catch lat/lon swaps (a swapped
            # Colorado well lands near latitude -105): refuse, never guess.
            raise WellsError(
                f"{path.name} line {line}: coordinates out of range "
                f"({record.lat}, {record.lon})"
            )
        if record.lat == 0.0 and record.lon == 0.0:
            # ECMC uses 0,0 for un-surveyed permits: skip, loudly.
            LOGGER.warning("skipping un-surveyed well %s (0,0 coordinates)", record.api)
            continue
        if record.api in seen_apis:
            # Real exports contain duplicate API rows; counting one well
            # twice would double the landmine signal.
            LOGGER.warning("skipping duplicate well row for API %s", record.api)
            continue
        seen_apis.add(record.api)
        records.append(record)
    if not records:
        raise WellsError(f"{path.name} yielded zero usable wells")
    return records


def haversine_ft(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in feet."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_FT * math.asin(math.sqrt(a))


def compute_well_proximity(
    store: EvidenceStore,
    wells: list[WellRecord],
    *,
    radius_ft: int = DEFAULT_RADIUS_FT,
    retrieved: date | None = None,
) -> int:
    """Append wells_within_radius + nearest_well_ft evidence per identity.
    Returns the number of identities annotated."""
    if radius_ft <= 0:
        raise WellsError(f"radius_ft must be positive, got {radius_ft}")
    counted = [w for w in wells if w.status in COUNTED_STATUSES]
    annotated = 0
    for identity in store.identities():
        lat, lon = identity.geocode.lat, identity.geocode.lon
        if lat == 0.0 and lon == 0.0:
            LOGGER.warning(
                "identity %s has no geocode — skipping well proximity "
                "(record it via the assessor ingest first)",
                identity.property_uid,
            )
            continue
        distances = [haversine_ft(lat, lon, w.lat, w.lon) for w in counted]
        within = sum(1 for d in distances if d <= radius_ft)
        nearest = min(distances) if distances else None
        when = retrieved or date.today()
        store.add_evidence(
            PropertyEvidence(
                property_uid=identity.property_uid,
                field="wells_within_radius",
                value=within,
                source=RIGHTS.source,
                retrieved=when,
                confidence=RIGHTS.confidence_tier,
            )
        )
        if nearest is not None:
            store.add_evidence(
                PropertyEvidence(
                    property_uid=identity.property_uid,
                    field="nearest_well_ft",
                    value=int(round(nearest)),
                    source=RIGHTS.source,
                    retrieved=when,
                    confidence=RIGHTS.confidence_tier,
                )
            )
        annotated += 1
    if annotated == 0:
        raise WellsError(
            "no identity carried a usable geocode — nothing was annotated "
            "(ingest assessor data first; failing closed instead of silently "
            "writing nothing)"
        )
    return annotated
