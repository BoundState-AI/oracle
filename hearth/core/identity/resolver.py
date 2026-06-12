#!/usr/bin/env python3
"""
Module: hearth.core.identity.resolver
Purpose: PropertyIdentity resolution (spec v0.3 §2.3; §13 P2-C).

APN is one identifier, not canonical truth. The resolver derives a stable
internal property_uid from (state, county, parcel), normalizes addresses
so sources can corroborate each other, and assigns an EXPLICIT
match_confidence. Confidence rules are deterministic and documented here —
no fuzzy scoring without a paper trail:

  0.97  parcel corroborated by the authoritative parcel source (assessor)
  0.92  parcel from a single non-authoritative source
  0.85  sources share the parcel but disagree on the normalized address
        (split/merge or situs error — resolve before trusting joins)

Low confidence BLOCKS evidence joins downstream (hearth.db.evidence_store)
until resolved or manually overridden — no silent merges.

Safety Critical: False
Financially Critical: True — a wrong identity join prices the wrong house.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import hashlib
import logging
import re

from hearth.data import Geocode, PropertyIdentity
from hearth.ingest.base import IngestBatch, RawPropertyRecord

LOGGER = logging.getLogger("hearth.core.identity.resolver")

CONFIDENCE_AUTHORITATIVE = 0.97
CONFIDENCE_SINGLE_SOURCE = 0.92
CONFIDENCE_ADDRESS_CONFLICT = 0.85

# Sources whose parcel assignments are authoritative for identity.
AUTHORITATIVE_PARCEL_SOURCES = frozenset({"larimer-assessor"})

_ABBREVIATIONS = {
    "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR",
    "LANE": "LN", "COURT": "CT", "CIRCLE": "CIR", "BOULEVARD": "BLVD",
    "PLACE": "PL", "HIGHWAY": "HWY", "PARKWAY": "PKWY", "TRAIL": "TRL",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
}


def normalize_address(raw: str) -> str:
    """Canonical situs form: uppercase, punctuation-free, USPS-style suffixes."""
    cleaned = re.sub(r"[^\w\s]", " ", raw.upper())
    tokens = [(
        _ABBREVIATIONS.get(token, token)) for token in cleaned.split()]
    return " ".join(tokens)


def property_uid(state: str, county: str, parcel: str) -> str:
    """Stable internal UID; parcel formatting noise must not fork identities."""
    parcel_key = re.sub(r"[\s\-]", "", parcel.upper())
    digest = hashlib.sha256(
        f"{state.upper()}|{county.upper()}|{parcel_key}".encode("utf-8")
    ).hexdigest()
    return f"hearth:prop:{digest[:12]}"


def resolve_batches(
    batches: list[IngestBatch], state: str = "CO", county: str = "Larimer"
) -> list[PropertyIdentity]:
    """Resolve all records across batches into PropertyIdentity instances."""
    by_uid: dict[str, list[tuple[str, RawPropertyRecord]]] = {}
    for batch in batches:
        for record in batch.records:
            uid = property_uid(state, county, record.parcel_id)
            by_uid.setdefault(uid, []).append((batch.source_id, record))

    identities = [
        _resolve_one(uid, sourced_records)
        for uid, sourced_records in sorted(by_uid.items())
    ]
    LOGGER.info("resolved %d identities from %d batches", len(identities), len(batches))
    return identities


def _resolve_one(
    uid: str, sourced_records: list[tuple[str, RawPropertyRecord]]
) -> PropertyIdentity:
    addresses = {
        normalize_address(record.address_raw) for _, record in sourced_records
    }
    sources = {source for source, _ in sourced_records}

    if len(addresses) > 1:
        # Same parcel, different situs across sources: §2.3 says surface it,
        # never merge silently — confidence drops below the join threshold.
        confidence = CONFIDENCE_ADDRESS_CONFLICT
        LOGGER.warning(
            "identity %s: address conflict across sources %s: %s",
            uid, sorted(sources), sorted(addresses),
        )
    elif sources & AUTHORITATIVE_PARCEL_SOURCES:
        confidence = CONFIDENCE_AUTHORITATIVE
    else:
        confidence = CONFIDENCE_SINGLE_SOURCE

    primary = _primary_record(sourced_records)
    geocode = Geocode(
        lat=primary.lat if primary.lat is not None else 0.0,
        lon=primary.lon if primary.lon is not None else 0.0,
    )
    return PropertyIdentity(
        property_uid=uid,
        parcels=sorted({record.parcel_id for _, record in sourced_records}),
        address_normalized=sorted(addresses)[0],
        unit=None,
        geocode=geocode,
        listing_ids=[],
        parcel_history=[],
        match_confidence=confidence,
        manual_override=False,
    )


def _primary_record(
    sourced_records: list[tuple[str, RawPropertyRecord]]
) -> RawPropertyRecord:
    """Prefer the authoritative source's record (it carries the geocode)."""
    for source, record in sourced_records:
        if source in AUTHORITATIVE_PARCEL_SOURCES:
            return record
    return sourced_records[0][1]
