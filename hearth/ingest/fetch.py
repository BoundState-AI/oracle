#!/usr/bin/env python3
"""
Module: hearth.ingest.fetch
Purpose: `hearth pull` — the network-permitted fetch layer (spec v0.3 §4,
         §4.1; §14 P3-A).

THE ONLY MODULE UNDER hearth/ ALLOWED TO SPEAK TO A NETWORK. It downloads
public bulk exports (assessor, ECMC wells, ...) into a local cache with full
provenance (sha256, retrieved date, manifest) and records the governance
source snapshot. It never sees BuyerPack material — enforced by the P1-D
boundary suite (this module is the first, WHY-commented entry on the
static-scan allowlist, and the runtime canary covers it).

Real endpoints are data in SOURCES below, researched and recorded
2026-06-12. Some county portals gate bulk exports behind interactive
pages; those sources carry manual_steps and `hearth pull` prints them as a
runbook instead of pretending. Every failure is a FetchError — a partial
or mangled download never enters the cache.

Safety Critical: False
Financially Critical: True — provenance of pulled data anchors every
  downstream number; never-suppress-error applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("hearth.ingest.fetch")

USER_AGENT = "hearth-founder-field-test/0.1 (single-tenant; contact: maintainer)"
TIMEOUT_SECONDS = 120.0
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024  # bulk county exports are large


class FetchError(Exception):
    """Download unusable or impossible; caller must fail CLOSED."""


@dataclass(frozen=True)
class FetchSource:
    """One pullable public source (registry entry, §4.1-adjacent)."""

    source_id: str
    description: str
    urls: tuple[str, ...]  # direct-download candidates, tried in order
    file_format: str
    adapter_hint: str  # which hearth command consumes the result
    monitored_source: str | None  # governance.monitored_sources entry to snapshot
    manual_steps: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


# Researched 2026-06-12 (web search; container egress to these domains is
# policy-blocked, so URLs are recorded for execution on the operator's
# machine — `hearth pull --plan` shows this registry).
SOURCES: dict[str, FetchSource] = {
    source.source_id: source
    for source in (
        FetchSource(
            source_id="larimer-assessor",
            description="Larimer County Assessor bulk property data (accounts, sales, values)",
            urls=(),  # portal-gated: the Public Data Center is interactive
            file_format="CSV/SHP export",
            adapter_hint="hearth ingest <file> --adapter larimer-assessor --store DIR",
            monitored_source=None,
            manual_steps=(
                "Open https://www.larimer.gov/assessor/publicdata (Public Data Center)",
                "Export the accounts+sales+values tables (CSV where offered)",
                "Save into the cache dir, then run the adapter_hint command",
            ),
            notes="Bulk data free and public, 24/7, per county announcement 2024-11-15.",
        ),
        FetchSource(
            source_id="ecmc-wells",
            description="ECMC (formerly COGCC) well surface locations, statewide, updated daily",
            urls=(
                "https://ecmc.colorado.gov/data-maps-reports/downloadable-data-documents",
            ),
            file_format="SHP/CSV (well surface locations; ~98k wells statewide)",
            adapter_hint="hearth wells <wells.csv> --store DIR",
            monitored_source="ECMC (formerly COGCC) rules and well database (ecmc.state.co.us)",
            manual_steps=(
                "If the direct page download fails, fetch the WELLS download "
                "linked from the Downloadable Data & Documents page",
                "Convert SHP to CSV if needed (ogr2ogr -f CSV wells.csv WELLS.shp)",
            ),
        ),
        FetchSource(
            source_id="larimer-permits",
            description="Larimer County building permit history export",
            urls=(),
            file_format="CSV export",
            adapter_hint="hearth ingest <file> --adapter larimer-permits --store DIR",
            monitored_source=None,
            manual_steps=(
                "Export permit history from the county permit portal "
                "(larimer.gov building department public records)",
            ),
        ),
        FetchSource(
            source_id="dola-mills",
            description="DOLA/LGIS mill levy certifications (metro-district cross-check)",
            urls=("https://dlg.colorado.gov/special-districts-brief-review-for-residents",),
            file_format="portal/spreadsheet",
            adapter_hint="cross-check only in P3 (assessor bulk already carries mill levies)",
            monitored_source="DOLA special district transparency portal (dola.colorado.gov)",
            manual_steps=(
                "Use DOLA's Local Government Information System for the "
                "district's service plan, debt, and certified levies",
            ),
        ),
        FetchSource(
            source_id="fema-nfhl",
            description="FEMA National Flood Hazard Layer (flood zone per parcel)",
            urls=("https://hazards.fema.gov/femaportal/NFHL/searchResult",),
            file_format="GDB/SHP county panels; per-point queries need GIS",
            adapter_hint="hearth add-evidence <property> --field fema_flood_zone --value <zone>",
            monitored_source="FEMA National Flood Hazard Layer (hazards.fema.gov)",
            manual_steps=(
                "Look up the address at https://msc.fema.gov/portal/search",
                "Record the flood zone with hearth add-evidence",
            ),
            notes="Automated per-point NFHL queries are Phase-4 (need GIS egress).",
        ),
        FetchSource(
            source_id="csfs-wildfire",
            description="Colorado State Forest Service Wildfire Risk Assessment rating",
            urls=("https://www.coloradoforestatlas.org",),
            file_format="interactive atlas; per-parcel rating",
            adapter_hint=(
                "hearth add-evidence <property> --field csfs_wildfire_risk_rating "
                "--value <low|moderate|high|very_high>"
            ),
            monitored_source=(
                "Colorado State Forest Service Wildfire Risk Assessment (coloradoforestatlas.org)"
            ),
            manual_steps=(
                "Look up the parcel on the Colorado Forest Atlas WRA viewer",
                "Record the rating with hearth add-evidence",
            ),
        ),
    )
}


@dataclass(frozen=True)
class FetchResult:
    source_id: str
    path: Path
    sha256: str
    bytes_written: int
    retrieved: date


def plan_lines() -> list[str]:
    """Offline pull plan: every source, how to get it, what consumes it."""
    lines = []
    for source in SOURCES.values():
        lines.append(f"[{source.source_id}] {source.description}")
        lines.append(f"    format : {source.file_format}")
        for url in source.urls:
            lines.append(f"    url    : {url}")
        for step in source.manual_steps:
            lines.append(f"    manual : {step}")
        lines.append(f"    then   : {source.adapter_hint}")
        if source.notes:
            lines.append(f"    note   : {source.notes}")
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def fetch_source(
    source_id: str,
    cache_dir: Path,
    *,
    transport=None,  # injectable for tests (httpx.MockTransport); None = real
) -> FetchResult:
    """Download one source's first working URL into the cache, with
    provenance. FetchError on every failure mode (fail CLOSED)."""
    source = SOURCES.get(source_id)
    if source is None:
        raise FetchError(
            f"unknown pull source {source_id!r}; available: {sorted(SOURCES)}"
        )
    if not source.urls:
        raise FetchError(
            f"source {source_id!r} is portal-gated (no direct URL). Manual steps:\n  - "
            + "\n  - ".join(source.manual_steps)
        )
    import httpx  # the ONE permitted network import under hearth/ (see header)

    errors: list[str] = []
    for url in source.urls:
        try:
            with httpx.Client(
                timeout=TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
                transport=transport,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.content
            if not payload:
                raise FetchError(f"{url} returned an empty body")
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise FetchError(f"{url} exceeds the {MAX_DOWNLOAD_BYTES:,}-byte cap")
            return _write_cache(source, url, payload, cache_dir)
        except FetchError as exc:
            errors.append(str(exc))
        except httpx.HTTPError as exc:
            errors.append(f"{url}: {exc}")
    raise FetchError(
        f"all URLs failed for {source_id!r}: {errors}. Manual fallback:\n  - "
        + "\n  - ".join(source.manual_steps or ("none recorded",))
    )


def _write_cache(
    source: FetchSource, url: str, payload: bytes, cache_dir: Path
) -> FetchResult:
    digest = hashlib.sha256(payload).hexdigest()
    target_dir = cache_dir / source.source_id
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = url.rstrip("/").rsplit("/", 1)[-1] or "download"
        target = target_dir / filename
        target.write_bytes(payload)
        manifest = {
            "source_id": source.source_id,
            "url": url,
            "sha256": digest,
            "bytes": len(payload),
            "retrieved": datetime.now(timezone.utc).isoformat(),
        }
        (target_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise FetchError(f"cannot write cache for {source.source_id}: {exc}") from exc
    LOGGER.info("pulled %s: %d bytes, sha256 %s", source.source_id, len(payload), digest)
    return FetchResult(
        source_id=source.source_id,
        path=target,
        sha256=digest,
        bytes_written=len(payload),
        retrieved=date.today(),
    )
