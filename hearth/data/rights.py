#!/usr/bin/env python3
"""
Module: hearth.data.rights
Purpose: Data-rights matrix row (spec v0.3 §4.1) — required before any
         source is treated as buildable.

Every ingest adapter must declare, as data: allowed fields, storage/TTL
and retention limits, derived-use permissions, display limits, end-user
authentication obligations, audit obligations, and fallback behavior when
the source is unavailable or revoked. Adapters without a declared row do
not run; adapters may not emit fields outside their declaration (enforced
in hearth.ingest.base).

`verified: false` means founder-declared pending human/legal verification —
the declaration exists so the obligation is visible, not to claim it has
been discharged.

Safety Critical: False
Financially Critical: False (contract definition; enforcement lives in
  hearth.ingest.base)

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


class DataRightsRow(HearthModel):
    """One source's declared rights posture (§4.1)."""

    source: str = Field(min_length=1)
    access: str = Field(min_length=1)
    allowed_fields: list[str] = Field(min_length=1)
    storage_ttl_days: int | None = None  # None = no retention limit identified
    derived_use: str = Field(min_length=1)
    display_limits: str = Field(min_length=1)
    auth_obligations: str = Field(min_length=1)
    audit_obligations: str = Field(min_length=1)
    fallback: str = Field(min_length=1)
    confidence_tier: float = Field(ge=0.0, le=1.0)  # §4 source table
    declared_by: str = Field(min_length=1)
    declared_on: date
    verified: bool = False
