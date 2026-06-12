#!/usr/bin/env python3
"""
Module: hearth.ingest.co_radon
Purpose: EPA radon-zone evidence — REAL county-constant data (spec v0.3 §4;
         §14 P3-B).

The EPA Map of Radon Zones assigns each county a zone (1 = highest indoor
radon potential, >4.0 pCi/L predicted average). Larimer, Weld, and Boulder
counties are all Zone 1 — verified 2026-06-12 against the EPA Colorado
zone document (epa.gov /sites/default/files/2014-08/documents/colorado.pdf).
Zone designations are county constants, so this is the one risk layer that
integrates as real data without a bulk download.

`hearth radon --store DIR --county Larimer` stamps every stored identity
with an epa_radon_zone evidence row. Unknown counties fail closed — no
guessing zones.

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

import logging
from datetime import date

from hearth.data import PropertyEvidence
from hearth.data.rights import DataRightsRow
from hearth.db.evidence_store import EvidenceStore

LOGGER = logging.getLogger("hearth.ingest.co_radon")

# EPA Map of Radon Zones, Colorado (verified 2026-06-12). Zone 1 = highest
# potential. Extend ONLY with values read from the EPA document itself.
EPA_RADON_ZONES: dict[str, int] = {
    "larimer": 1,
    "weld": 1,
    "boulder": 1,
}

RIGHTS = DataRightsRow(
    source="EPA Map of Radon Zones, Colorado (epa.gov, verified 2026-06-12)",
    access="public federal document; county-constant designation",
    allowed_fields=["epa_radon_zone"],
    storage_ttl_days=None,
    derived_use="radon landmine evaluation; inspection-norm guidance",
    display_limits="public data; cite EPA zone map",
    auth_obligations="none",
    audit_obligations="retain verification date with provenance (§11)",
    fallback="buyer-supplied radon test results",
    confidence_tier=0.90,
    declared_by="Dr. Joseph Wilde (founder declaration)",
    declared_on=date(2026, 6, 12),
    verified=False,
)


class RadonError(Exception):
    """County unknown to the verified zone table; fail CLOSED."""


def stamp_radon_zone(
    store: EvidenceStore, county: str, *, retrieved: date | None = None
) -> int:
    """Append epa_radon_zone evidence for every stored identity."""
    zone = EPA_RADON_ZONES.get(county.strip().lower())
    if zone is None:
        raise RadonError(
            f"county {county!r} is not in the verified EPA zone table "
            f"({sorted(EPA_RADON_ZONES)}) — refusing to guess"
        )
    stamped = 0
    when = retrieved or date.today()
    for identity in store.identities():
        existing = store.evidence_for(
            identity.property_uid, "epa_radon_zone", allow_low_confidence=True
        )
        # WHY allow_low_confidence: dedup READ of a county constant is not a
        # cross-source identity join; the §2.3 guard protects joins, and a
        # zone stamp is identical for every parcel in the county.
        if any(row.source == RIGHTS.source for row in existing):
            continue
        store.add_evidence(
            PropertyEvidence(
                property_uid=identity.property_uid,
                field="epa_radon_zone",
                value=zone,
                source=RIGHTS.source,
                retrieved=when,
                confidence=RIGHTS.confidence_tier,
            )
        )
        stamped += 1
    LOGGER.info("stamped epa_radon_zone=%d for %d identities (%s)", zone, stamped, county)
    return stamped
