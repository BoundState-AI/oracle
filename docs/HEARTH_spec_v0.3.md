





# HEARTH — Buyer-Side Real Estate Intelligence Platform

**Specification v0.3 (Code-ready: ORACLE v0.2 + locked Phase-1 build scope)**

BoundState AI 2026 · Classification: BoundState Proprietary Maintainer: Dr. Joseph Wilde · Drafted with: Beth (Claude Fable 5) Working name: **HEARTH** (alternates deferred). Brand logic: Bouncer gets you past the door, HEARTH gets you the house behind it.

> **Revision note (v0.2):** Round 1 review produced unanimous critical findings on (1) UPL/brokerage exposure of generative output, (2) undefined MLS data rights, and (3) an unenforceable BuyerPack privacy claim, plus high-severity findings on JurisdictionPack scaling, valuation statistics, and property identity. This draft resolves the reviewable engineering defects and reframes compliance posture conservatively. Three items require human/legal authority before lock and are flagged in Section 9.

## 0. Thesis

The residential buyer's structural disadvantage is **unexplained defaults**: pre-filled commission percentages, region-wide agreement scopes, backstop clauses, list prices unanchored to evidence, contract deadlines the buyer doesn't know are negotiable. Every organ of this platform exists to surface a default, cite the evidence against it, and present a buyer-favorable alternative **for the buyer's licensed human to draft and execute**.

Same architecture as Bouncer, rotated 90°:

| **Bouncer** | **HEARTH** |
| --- | --- |
| CV rule pack (canonical "me") | BuyerPack (canonical household) |
| ATS posting scanner | Listing/records ingestion pipeline |
| Tailoring engine → finished deck | Offer optimizer → **scenario analysis brief** |
| — | JurisdictionPack (the local's rules, serialized) |
| — | DocScrubber (the Kelly module) |

Integrity rules inherit from MIRA: evidence-first, no hardcoded triggers, every recommendation cites sources with calibrated uncertainty. A valuation without citations is a vibe; HEARTH does not ship vibes.

## 1. Architecture & Deployment Model

hearth/
├── api/            # FastAPI endpoints (single-tenant)
├── core/
│   ├── valuation/      # Comp engine, calibrated prediction intervals
│   ├── signals/        # Seller-motivation analysis
│   ├── scrubber/       # Document parsing & default detection (local inference)
│   ├── optimizer/      # Offer scenario construction
│   ├── fit/            # BuyerPack ↔ property scoring
│   └── identity/       # PropertyIdentity resolution (Section 2.3)
├── data/           # Pydantic models (Section 2)
├── db/             # PostgreSQL + FAISS (comp embedding search)
├── packs/
│   ├── buyer/          # BuyerPack instances (local-first, E2EE sync only)
│   └── jurisdiction/   # JurisdictionPack micro-rule library (versioned, signed)
├── ingest/         # Source adapters (Section 4)
├── audit/          # Per-run reproducibility artifacts (Section 11)
├── skills/         # Knowledge base
└── utils/

### 1.1 Deployment & Trust Boundary (resolves R1 privacy contradiction)

HEARTH ships as a **local-first, single-tenant application**. The trust boundary is explicit:

**BuyerPack never crosses the trust boundary in plaintext.** It is stored locally (or as an end-to-end-encrypted blob the server cannot decrypt — see 2.1) and is processed only by **local models**. No BuyerPack field is sent to any third-party inference API, analytics, telemetry, or backup that the operator cannot read-exclude.

**Market data (county, MLS, portal, risk layers) may cross the boundary** to a single-tenant instance under the data-rights matrix (Section 4.1).

**Exfiltration is defined testably:** any code path that places a BuyerPack field into an outbound network call, a server log, a non-E2EE store, or a third-party model prompt is a build-failing violation. CI includes boundary tests (Section 6, Section 11).

Standard BoundState headers on all modules. Safety Critical: False throughout; new header field Financially Critical: True for valuation, scrubber, optimizer, identity. Financially-critical modules follow the never-suppress-error pattern: a scrub that fails OPEN (silently passes a document) is the cardinal failure mode.

## 2. Data Models

### 2.1 BuyerPack

Canonical household, structured. Local-first; if synced across a household's trusted devices, only as an **end-to-end-encrypted blob (zero-knowledge to the server)**. This enables couples/multi-device/advisor collaboration without breaking the privacy guarantee.

{
  "identity": {"household": str, "pack_version": str, "created": date},
  "hard_constraints": {
    "budget_ceiling_usd": int,
    "financing": {"type": "conventional|cash|hybrid",
                   "preapproval_usd": int, "down_pct": float,
                   "rate_lock_expiry": date | None},
    "geography": {"anchor": "Ursa Major, Berthoud CO",
                   "max_commute_min": int,
                   "counties": ["Larimer", "Weld", "Boulder"]},
    "deal_breakers": [str]
  },
  "soft_preferences": [
    {"feature": "shop_space_sqft", "target": 600, "weight": 0.25},
    {"feature": "single_story",    "target": true, "weight": 0.10}
  ],
  "timeline": {"need_occupancy_by": date, "flexibility_days": int,
                "temp_housing_runway_days": int},
  "posture": {"contingency_tolerance": "standard|tight|waive_with_evidence",
               "max_appraisal_gap_usd": int,
               "disclosure_policy": "reveal_nothing"}
}

### 2.2 JurisdictionPack (micro-rule model + governance)

Replaces the monolithic per-county document. A pack is a set of **versioned, individually-signed micro-rules**, each with provenance and an effective-date window. Experts act as **reviewers**, not authors: rules are bootstrapped from source legal texts/brokerage manuals and require human licensee/attorney validation per rule.

{
  "jurisdiction": {"state": "CO", "county": "Larimer", "version": "2026.06"},
  "governance": {
    "owner": str,                         # named accountable maintainer
    "monitored_sources": [str],           # statute/form feeds watched for change
    "update_sla_days": int,
    "status": "provisional|reviewed|deprecated"
  },
  "rules": [
    {"rule_id": str,
     "category": "contract_deadline|landmine|commission_norm|form",
     "effective_from": date, "effective_to": date | None,
     "source": str,                       # statute / form citation
     "authority_review": {"reviewer": str, "license": str, "date": date},
     "signature": str,                     # cryptographic signature
     "payload": {...}}
  ]
}

**Auto-invalidation:** when a monitored standard form or statute changes, dependent rules flip to provisional and any output relying on them is flagged stale until re-reviewed.

**Mid-transaction change:** if a rule's effective_to lapses during an active engagement, the run is flagged and the user is told the basis changed.

Packs/rules without licensee/attorney review ship marked provisional and cannot be the sole basis of a flag/refuse finding shown to a user.

### 2.3 PropertyIdentity & PropertyEvidence (resolves APN fragility)

APN is **one identifier, not canonical truth.** A PropertyIdentity resolves listings/parcels/units with explicit match confidence.

# PropertyIdentity
{
  "property_uid": str,                     # internal canonical UID
  "parcels": [str],                        # one or more APNs
  "address_normalized": str,
  "unit": str | None,
  "geocode": {"lat": float, "lon": float},
  "listing_ids": [str],
  "parcel_history": [str],                 # split/merge lineage
  "match_confidence": float,
  "manual_override": bool
}

# PropertyEvidence Row
{
  "property_uid": str,                     # FK to PropertyIdentity
  "field": str,
  "value": Union[float, str],
  "source": str,
  "retrieved": date,
  "confidence": float
}

Low match_confidence blocks comp/permit/landmine joins until resolved or overridden — no silent merges.

### 2.4 SellerSignals

*(unchanged from v0.1; keyed on `property*uid`.)_

{
  "property_uid": str,
  "dom": int, "price_cuts": [{"date": date, "from": int, "to": int}],
  "acquisition": {"price": int, "date": date, "implied_equity_pct": float},
  "tells": [{"signal": "estate_sale|relocation|vacant|listed_below_assessment|expired_relist",
              "evidence": str, "confidence": float}],
  "motivation_score": float,
  "leverage_notes": str
}

### 2.5 ScrubFinding (the Kelly module output — human-gated)

{
  "document": str, "clause_ref": str,
  "category": "fee|scope|backstop|default_trap|deadline|waiver",
  "severity": "info|warn|flag|refuse",
  "found": str,                                  # verbatim clause
  "default_analysis": str,                       # what the blank could have said
  "exposure_usd": int | None,
  "suggested_template": str | None,              # reviewed CO template language ONLY
  "requires_human_review": true,                 # always true for template output
  "jurisdiction_basis": str                      # cite into JurisdictionPack rule_id
}

suggested_template is drawn only from licensee/attorney-reviewed template libraries, is framed as "language commonly used / questions to ask your licensee or attorney," and **must be marked `requires_human_review`**. The system never represents it as final, buyer-specific legal advice. Pending the Section 9 counsel opinion, deployments may run the scrubber in **findings-only mode** (no suggested_template).

Reference test case: the 2026-06-11 Grey Rock BDB24-6-24 must produce, minimum: fee/warn, scope/flag, backstop/flag (exposure*usd computed), `default*trap/flag`. **This document is the unit test.**

### 2.6 OfferScenarioAnalysis (was OfferPackage — reframed to reduce UPL/brokerage exposure)

{
  "property_uid": str,
  "price": {"estimate": int, "pi_low": int, "pi_high": int,   # prediction interval
             "coverage": float, "vs_list": int,
             "evidence_rows": [PropertyEvidence]},
  "scenarios": [                                  # modeled options, not instructions
    {"label": str, "earnest_pct": float, "deadlines": {...},
     "contingencies": {...}, "appraisal_gap_usd": int,
     "modeled_outcome": str, "tradeoffs": str, "rationale": str}
  ],
  "concessions_math": str,
  "human_handoff": {"licensee_tasks": [...], "attorney_tasks": [...]},
  "requires_human_review": true
}

The platform **models** the outcomes of different term structures; the buyer's licensed human performs the acts of drafting and submitting an offer. No direct-send or negotiation capability exists in the product.

## 3. Core Engines

### 3.1 Valuation Engine (statistically corrected)

Comp selection: FAISS similarity over structured embedding — **closed sales only** as anchors; actives as market-direction signal only.

Output: point estimate plus an **empirically calibrated prediction interval** for a specific property, **not** mean ± 1.645·σ/√n. Intervals are derived from backtested holdout error by submarket and property type, and **published coverage** (e.g., target 90% empirical coverage) is reported.

**Minimum-evidence gates:** below a minimum comp count / above an error threshold, the engine returns an explicit insufficient_evidence no-estimate state rather than a narrow range.

Hedonic adjustments carry their derivation and their uncertainty contribution inline. No black-box AVM mimicry. *"Zestimate disagrees" is not an error state; false precision is.*

### 3.2 Seller Signal Engine

Public + licensed listing data only (Sections 4, 8). DOM percentile vs. micro-market, cut cadence, acquisition basis from transfer records, vacancy proxies, relist detection. Motivation-score weights are a published profile (Section 5), not a hidden model.

### 3.3 DocScrubber (local inference when BuyerPack-adjacent)

Parse → clause segmentation → deterministic template diff against JurisdictionPack rules (high precision on known forms) → LLM clause analysis for novel documents, each finding citing the motivating rule_id. **Any analysis stage that can see BuyerPack or buyer-identifying context runs on local models.** **Fails CLOSED:** unparseable document → refuse finding, never silence.

### 3.4 Offer Optimizer

Inputs: BuyerPack posture + Valuation + SellerSignals + JurisdictionPack rules. Output: OfferScenarioAnalysis (2.6) — modeled term-surface options with tradeoffs, not prescriptive instructions or submission-ready legal documents. Enforces disclosure_policy: reveal_nothing: generated text never leaks budget ceiling, timeline pressure, or attachment, and passes the leak check (Section 6) before display.

### 3.5 FitScorer

BuyerPack soft preferences × property evidence → explainable 0–1 score in MIRA scoring-profile format. Local inference. Replaces "I have a feeling about this one" with arithmetic the household can argue about over dinner.

## 4. Ingestion (MVP sources, Larimer/Weld/Boulder)

| **Source** | **Data** | **Access** | **Confidence tier** |
| --- | --- | --- | --- |
| County assessor (3 counties) | Parcels, levies, transfers, sold prices | Public APIs/bulk | 0.95 |
| County permits | Permit history | Public portals | 0.90 |
| IRES MLS | Listings, DOM, cuts, solds | Licensed feed — see 4.1 & Sec. 9 #1 | 0.85 |
| Buyer-supplied docs/PDFs | Listing sheets, contracts | User-provided | 0.80 |
| COGCC, FEMA, CO FireRisk | Wells, flood, wildfire layers | Public | 0.90 |
| Metro district transparency portal | Mill levies, debt | Public | 0.95 |

**Portal scraping is removed as a production dependency** (non-durable, ToS risk). It may be used only for manual one-off research, never as an automated pipeline.

### 4.1 Data-Rights Matrix (required before treating a source as buildable)

Each source must declare, before adapter build: allowed fields; storage/caching TTL and retention limits; derived-use permissions; display limits; end-user authentication obligations; audit/reporting obligations; and fallback behavior when the source is unavailable or revoked. MLS data is governed additionally by RESO/IDX/VOW constraints and the chosen operating model (Section 9 #1). The valuation/seller engines must degrade gracefully (to buyer-supplied-doc mode) when MLS data is absent.

Identity resolution per Section 2.3; property_uid is canonical, APN is an attribute.

## 5. Scoring Profiles (published weights, rationale mandatory)

BUYER_LEVERAGE_PROFILE = {
    "seller_motivation":   0.35,
    "valuation_gap":       0.30,
    "market_micro_trend":  0.20,
    "competition_proxy":   0.15
}

Rationale block required per profile. Profiles are versioned and user-visible — no hidden weights, ever.

## 6. Integrity Rules (Fran's rules, ported & hardened)

**Evidence-first:** every number cites a row; every row cites a source; calibrated uncertainty always shown.

**No hardcoded triggers:** derive from comps, never "if Zestimate > list then good deal."

**No advice past the data:** thin comps → insufficient_evidence, never improvise.

**Scrubber fails closed.**

**BuyerPack never exfiltrates** — defined testably (Section 1.1). CI boundary tests prove no BuyerPack field reaches an outbound call, server log, non-E2EE store, or third-party model. Not to analytics, not to "improve the model," not anywhere.

**Disclosure discipline is enforced, not suggested** — generated external text passes a leak check against the pack before display.

**Human-review gating:** any template language or submission-ready term content is marked requires_human_review and is never presented as final buyer-specific legal advice.

## 7. Unbundled Human Layer

Platform does cognition; licensed humans perform statutorily-gated acts:

**Door access / contract signature:** flat-fee or hourly CO licensee, engaged per-property via the JurisdictionPack touring-agreement template.

**Closing paper:** real estate attorney, fixed fee.

Target intermediary cost on a $700k purchase: **≤ $5k** vs $21k status quo.

**Supply risk (R1, Gemini):** a liquid market of licensees willing to perform on-demand, unbundled, low-margin gated acts does not currently exist. This is a last-mile dependency, not a given. Candidate resolution — building or affiliating a flat-fee brokerage employing salaried/contract agents (a tech-enabled-service rather than pure-SaaS model) — is a **product-direction decision flagged in Section 9 #5**.

## 8. Legal Guardrails (hard requirements, not vibes)

HEARTH is **not a brokerage** and performs no act defined as brokerage under C.R.S. 12-10-201 — no negotiating *on behalf of*, no offering to perform for compensation. It is an analytics and document-intelligence tool used by a principal on their own behalf.

**Disclaimers are not controls.** Hard workflow controls accompany them: approved template/form boundaries; mandatory licensed-human review for any clause language or submission-ready offer content; no direct-send or negotiation actions in the product; product copy framed as options/questions where counsel requires.

Output banners ("not legal advice / not a licensed brokerage") on valuation, scrub, and scenario outputs — **in addition to**, not instead of, the controls above.

JurisdictionPack rules without licensee/attorney review ship provisional and cannot solely drive user-shown flag/refuse.

Data acquisition respects each source's rights matrix; MLS data only via the licensed operating model chosen in Section 9 #1.

**Blocking gate:** no generative legal-language path (suggested_template, scenario term recommendations) ships to any non-founder user until the Section 9 #3 Colorado counsel opinion is obtained. Founder field test runs in findings-only / self-represented mode.

## 9. ORACLE Review — Open Questions (require human/legal authority)

**MLS operating model.** Define now: who holds the MLS license, who authenticates end users, what may be stored/displayed/derived, retention limits, audit duties, and feed-revocation fallback. RESO/IDX/VOW constraints in scope. Sequence: buyer-supplied-doc MVP → sponsoring-broker feed.

**JurisdictionPack as product vs internal.** Decides governance investment. Default: micro-rule library with signed expert review; licensing to flat-fee brokerages is an option.

**UPL/brokerage counsel opinion (blocking).** Obtain a written Colorado opinion on whether gated, human-reviewed template language and scenario analysis sold for compensation stays outside brokerage/UPL. Until then, ship findings-only / analysis-only.

**Photo-derived condition features.** MVP: permit-history proxy only; CV pipeline phase 2.

**Unbundled human-layer supply.** Build/affiliate a flat-fee brokerage (tech-enabled service) vs rely on an open market that does not yet exist. Business-direction decision.

**Name.** HEARTH / DRAWBRIDGE / LEDGER / other.

## 10. Claude Code Handoff Notes

Build order (each stage independently useful):

**DocScrubber CLI (findings-only)** — packs/jurisdiction/CO-Larimer micro-rule skeleton + BDB24-6-24 template diff. Unit test: Grey Rock (2.5).

**PropertyIdentity + PropertyEvidence ingest** — assessor + permit adapters for Larimer; property_uid-keyed store with match-confidence joins.

**Valuation engine** — comp FAISS + calibrated prediction intervals; backtest harness; buyer-supplied-comp fallback.

**SellerSignals** — transfer-record basis + DOM/cut analysis.

**FitScorer + BuyerPack schema** — local-only instance zero.

**Offer scenario analyzer** — last; needs 1–5 live; ships gated.

Stack: FastAPI (single-tenant), Pydantic v2, Postgres+FAISS, local models for any BuyerPack-adjacent inference, pytest with the Grey Rock doc as fixture #1 and BuyerPack boundary tests as fixture #2. Headers per boundstate-architecture with Financially Critical field added.

## 11. Audit & Reproducibility (new)

Every financially-critical run (scrub, valuation, scenario) emits an immutable audit artifact:

source snapshot IDs (which data rows/versions fed the run)

JurisdictionPack version + contributing rule_ids

scoring-profile version

code + model + prompt hash

rendered output

Define diff and rollback procedures before production use: any later pack/source/model/prompt change that would alter a prior result must be reproducible and explainable. This supports debugging, dispute handling, and regulator/partner review.

*v0.2 — revised after Round 1 ORACLE review. The unit test for this platform still walked up to its author at an airport gate and asked for his signature.*


---

## 12. PHASE-1 FOUNDER BUILD — LOCKED SCOPE (v0.3 addition, authoritative for this build session)

**Mode: founder field test.** Single user (Joe), self-represented principal. UPL blocking gate (Sec. 8/9) is satisfied for this mode: findings-only scrubber, no suggested_template generation, no compensation, no third-party users. Nothing in this phase ships beyond the founder.

**Build EXACTLY these four deliverables. Nothing else. No valuation engine, no MLS adapters, no optimizer, no UI beyond CLI.**

### P1-A: Repo skeleton + models
- `hearth/` per Section 1 tree; Pydantic v2 models for BuyerPack, JurisdictionPack (micro-rule schema 2.2), PropertyIdentity, PropertyEvidence, ScrubFinding, AuditArtifact.
- BoundState headers on every module incl. `Financially Critical` field.
- ACCEPT: `pytest` green on model round-trip (JSON → model → JSON, lossless).

### P1-B: DocScrubber CLI — findings-only
- `hearth scrub <file.pdf|.docx|.txt> --pack CO-Larimer` → table of ScrubFinding + JSON output + AuditArtifact (Sec. 11 fields; prompt/model hash may be stubbed constants in P1).
- Pipeline: text extraction → clause segmentation → deterministic rule match against pack micro-rules → findings. LLM stage: STUB behind interface (`ClauseAnalyzer` protocol), not implemented in P1 — deterministic only.
- FAILS CLOSED: extraction or parse failure → single `refuse` finding, exit code 2, never empty-success.
- ACCEPT: Grey Rock BDB24-6-24 fixture produces ≥ these findings: fee/warn (3% pre-filled, fee-negotiable rule), scope/flag (region-wide), backstop/flag with exposure_usd = 3% × $700,000 = $21,000 at configured target price, default_trap/flag (fee survives buyer default). Golden-file test.

### P1-C: CO-Larimer pack skeleton (provisional)
- ≥ 12 micro-rules, all `status: provisional`, real source citations, signature field present (stub signer OK):
  - 4 rules covering the BDB24-6-24 findings above (buyer-broker fee negotiability, scope breadth, buyer backstop, default-survival)
  - CREC CBS contract deadline table: inspection objection, inspection resolution, appraisal deadline, loan availability (4 rules, payload = lever + risk-if-waived text)
  - Landmines: metro-district mill thresholds (warn 45 / flag 60), radon norm, wildfire-insurance check, oil/gas setback radius query spec (4 rules; detection specs as data, adapters NOT built in P1)
- ACCEPT: pack validates against 2.2 schema; provisional rules render with provisional banner in CLI output.

### P1-D: Boundary-test scaffold
- CI test asserting no BuyerPack field appears in any outbound-call construction, log write, or non-local store. P1 implementation: static scan of network/log call sites + runtime fixture with canary values in a BuyerPack, asserting canaries never reach a mocked network layer or log capture.
- ACCEPT: canary test red when a deliberate leak is introduced in a test branch, green on main.

### Constraints
- Stack: Python 3.12, FastAPI present but only health endpoint in P1, Pydantic v2, pytest, no DB required in P1 (filesystem stores fine); no new heavyweight deps without a one-line justification in README.
- Grey Rock document = `tests/fixtures/BDB24-6-24_greyrock_2026-06-11.*` = fixture #1. Boundary canary = fixture #2.
- Every commit message cites the spec section it implements.
- If any instruction here conflicts with Sections 0–11, THIS SECTION WINS for Phase 1, and the conflict gets logged in `BUILD_NOTES.md` for v0.4.

*v0.3 — Beth, 2026-06-11, The Hotel, Loveland/Berthoud corridor. ORACLE found the cracks; this section pours the first concrete. Build order is the beer order: P1-A pilsner, P1-B the heavy pour, P1-C session ale, P1-D the nightcap that keeps everyone honest.*
