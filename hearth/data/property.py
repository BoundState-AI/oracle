#!/usr/bin/env python3
"""
Module: hearth.data.property
Purpose: PropertyIdentity + PropertyEvidence (spec v0.3 §2.3).

APN is one identifier, not canonical truth: a PropertyIdentity resolves
listings/parcels/units to an internal property_uid with explicit match
confidence. Low match_confidence blocks comp/permit/landmine joins until
resolved or overridden — no silent merges. Every evidence row cites its
source and retrieval date so every downstream number can cite a row (§6).

Safety Critical: False
Financially Critical: False (contract definition; the identity RESOLVER —
  a Phase-2 organ — is the financially-critical decider)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

from datetime import date

from pydantic import Field

from hearth.data.base import HearthModel


class Geocode(HearthModel):
    """WGS84 point for the resolved property (§2.3)."""

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class PropertyIdentity(HearthModel):
    """Canonical resolution of listings/parcels/units (§2.3)."""

    property_uid: str = Field(min_length=1)
    parcels: list[str]
    address_normalized: str
    unit: str | None = None
    geocode: Geocode
    listing_ids: list[str]
    parcel_history: list[str]
    match_confidence: float = Field(ge=0.0, le=1.0)
    manual_override: bool = False


class PropertyEvidence(HearthModel):
    """One sourced fact about one property (§2.3)."""

    property_uid: str = Field(min_length=1)
    field: str = Field(min_length=1)
    # int joins float|str from §2.3 so JSON integers (sqft, mills, USD)
    # round-trip losslessly instead of being coerced to floats.
    value: int | float | str
    source: str = Field(min_length=1)
    retrieved: date
    confidence: float = Field(ge=0.0, le=1.0)
