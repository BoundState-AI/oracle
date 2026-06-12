# HEARTH — §14 PHASE-3 FOUNDER BUILD — LOCKED SCOPE (v0.4 draft)

**Status:** locked for the Phase-3 build session, 2026-06-12. Mission, per the
founder: every data stream needed so the buyer cannot be steamrolled by the
seller side — pulled, integrated, and visible. Founder field test mode; §8/§9
UPL gates unchanged.

**Environment reality (recorded):** this build container's egress policy
blocks county/state data domains (uniform 403; package registries and web
search only). Therefore Phase 3 ships the REAL endpoints as an executable
fetch layer (`hearth pull`) that runs on the founder's machine, plus full
integration proven against schema-faithful fixtures, plus every dataset that
IS verifiable from here (EPA radon zone constants) integrated as real data.
Nothing fabricated: anything not verifiable verbatim stays SYNTHETIC-marked.

### P3-A: `hearth pull` — the fetch layer (network-permitted zone)
- Source registry as data: Larimer assessor Public Data Center bulk exports,
  ECMC well surface locations (updated daily), DOLA/LGIS mill certifications,
  FEMA NFHL, CSFS Wildfire Risk atlas — each with real URLs, §4.1 rights row,
  expected formats, and manual-fallback notes for portal-gated exports.
- `hearth pull --source <id> --cache DIR` downloads with provenance (sha256,
  retrieved date, manifest), records the governance source snapshot, and
  FAILS CLOSED on any network/HTTP error with the manual runbook printed.
  `hearth pull --plan` works fully offline.
- Boundary discipline: the fetch module is the FIRST entry on the static-scan
  allowlist (httpx, WHY-commented) with a runtime canary test proving
  BuyerPack material cannot reach the fetch layer. Injectable transport for
  tests — no live network in CI.
- ACCEPT: plan mode lists all sources offline; mocked-transport pull writes
  cache + manifest + governance snapshot; network failure refuses with
  runbook; boundary suite green with the allowlist entry exercised.

### P3-B: Risk-layer data integrated
- **Radon (REAL data now):** EPA Map of Radon Zones — Larimer/Weld/Boulder
  all Zone 1 (verified 2026-06-12, epa.gov Colorado zone document). New
  `hearth radon --store DIR --county Larimer` stamps county-constant
  `epa_radon_zone` evidence rows (tier 0.90) for every stored identity.
- **Wells:** `hearth wells <ecmc_wells.csv> --store DIR` parses the ECMC
  surface-location schema, computes `wells_within_radius` (haversine,
  default 2,000 ft, ECMC Rule 604 framework) + `nearest_well_ft` per
  identity geocode, appends evidence with provenance. Fixture mirrors the
  real ECMC column set, marked SYNTHETIC.
- **Buyer-supplied entries:** `hearth add-evidence <property> --field X
  --value Y` for flood zone / wildfire rating / anything the buyer learns
  first-hand (tier 0.80) until automated feeds land.
- **Flood landmine rule:** CO-LAR-LM-FLOOD-001 (fema_flood_zone: A/AE/AO →
  flag; X-shaded/X500 → warn) joins the pack; pack version bumps to
  2026.06.1; goldens regenerated deliberately; FEMA NFHL + EPA radon map
  join monitored_sources with lock entries.
- DOLA mills adapter NOT built (assessor bulk already carries mill levies;
  DOLA stays a registry endpoint for Phase-4 cross-checks).
- ACCEPT: radon rows land for every identity; wells math proven on known
  coordinates (golden distances); flood rule fires on manual evidence; scan
  of a fully-fed property produces alerts on all five landmine rules;
  fail-closed on malformed wells CSV / unknown county / junk field names.

### P3-C: Scan surface in the web app
- Server: `GET /hearth/properties` (identities in the configured store) and
  `POST /hearth/scan` (uid → alerts + rendered report + audit ref), same
  auth gate and refusal semantics as /hearth/scrub.
- Frontend: a Properties & Landmines section on the /hearth page — list
  ingested properties, scan button, alert cards with status/severity and
  evidence citations, insufficient-evidence rendered honestly.
- ACCEPT: server tests green; `next build` green; banners structural.

### P3-D: Loop, ship, merge
- Adversarial review of the Phase-3 diff; fix + regression-pin findings;
  full suite green; PR to main; merge on green CI (founder pre-authorized).

### Carried exclusions
Valuation engine (blocked on backtest harness spec), MLS adapters (§9 #1),
LLM ClauseAnalyzer (local-model infra), automated FEMA/CSFS per-point GIS
queries (need working egress; endpoint specs recorded for the founder
machine).

*§14 — the fetch layer is the bridge between this sandbox and the county
records; radon is the first real number in the store. The realtor-proofing
stack: scrubbed agreement + mills + radon + wells + flood + wildfire +
permits, every row cited.*
