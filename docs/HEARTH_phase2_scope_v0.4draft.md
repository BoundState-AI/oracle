# HEARTH — §13 PHASE-2 FOUNDER BUILD — LOCKED SCOPE (v0.4 draft)

**Status:** locked for the Phase-2 build session, 2026-06-12. Authored per the
§12 pattern; supersedes §0–11 where they conflict for Phase 2, with every
conflict logged in `BUILD_NOTES.md`. Mode is still **founder field test**
(single self-represented user); the §8/§9 UPL gates carry forward unchanged —
findings-only, no generative legal language, no third-party users.

**Build EXACTLY these four deliverables, in order, each gated on pytest.
Explicitly OUT of scope:** valuation engine (blocked on a specced backtest
harness), MLS/portal adapters (blocked on the §9 #1 operating-model
decision), local-model ClauseAnalyzer (blocked on founder local-model
infra), any new web/UI surface for the new organs (Phase 3), live network
adapters of any kind — ingestion is **bulk-file based** in P2.

### P2-A: Exposure-capture dependency made explicit (closes BUILD_NOTES §7)
- Exposure specs gain `capture_from_rule: <rule_id>`; the loader rejects a
  pack whose exposure spec references a rule absent from the pack.
- When a target price is configured but the depended-on capture did not
  fire, the finding itself carries a visible "exposure not computed" note —
  in the finding text, not just the log.
- ACCEPT: loader rejects dangling `capture_from_rule`; deleting the fee rule
  from a pack copy yields a backstop finding with the visible note; Grey
  Rock golden unchanged for the computed case.

### P2-B: Real signing + governance loop (replaces the stub-only signer)
- Ed25519 per-reviewer signatures (`ED25519:<key_id>:<hex>`) over the same
  canonical rule bytes; committed public-key registry (`keys.json`) resolved
  relative to the pack; `python -m hearth.packs.signing` grows
  `keygen`/`sign`/`resign-stub` modes. STUB1 remains valid **only** for
  provisional rules.
- **Invariant (load-time):** `status: reviewed` requires a verifying
  Ed25519 signature — a stub signature cannot attest human review.
- Governance freshness: per-pack `sources.lock.json` snapshot of monitored
  sources; `hearth pack-status` reports rule statuses, signature schemes,
  and staleness vs `update_sla_days`; `python -m hearth.packs.governance`
  flips rules whose `source` matches a changed monitored source back to
  provisional (auto-invalidation, §2.2).
- New dependency: `cryptography` (Ed25519) — justification line in README.
- ACCEPT: sign/verify round-trip; tampered Ed25519 rule fails closed;
  reviewed+stub pack refuses to load; reviewed+Ed25519 pack loads;
  stale/missing source snapshot surfaces in `hearth pack-status`.

### P2-C: PropertyIdentity + PropertyEvidence ingest (bulk-file, Larimer)
- §4.1 data-rights row is a **declared data structure** required by every
  adapter; adapters refuse to run without one. Two file-based adapters:
  Larimer assessor bulk export and Larimer permits export (synthetic
  fixture schemas, marked SYNTHETIC).
- Identity resolution (§2.3): stable `property_uid` from state|county|parcel;
  normalized addresses; explicit match_confidence; **low confidence blocks
  evidence joins** (no silent merges) unless `manual_override`.
- Filesystem evidence store (no DB in P2): append-only JSONL with full
  provenance (source, retrieved, confidence) so every downstream number can
  cite a row (§6).
- CLI: `hearth ingest <export.csv> --adapter larimer-assessor --store DIR`;
  malformed input fails closed (exit 2).
- ACCEPT: synthetic exports ingest → identities + evidence rows round-trip;
  low-confidence join raises; unknown columns/garbage CSV refuse; CLI exit
  codes proven.

### P2-D: Landmine scan engine (turns P1-C's inert specs into value)
- Evaluator executes the four `data_query` landmine rules against the
  evidence store: numeric/count/rating thresholds → `PropertyAlert`s citing
  the exact evidence rows (§6 evidence-first). Missing evidence for a
  rule's query field → `insufficient_evidence` alert, **never silence**
  (§3.1 minimum-evidence gate, applied to landmines).
- CLI: `hearth scan <property_uid> --pack CO-Larimer --store DIR` →
  banners (legal + provisional) + alert table + §11 audit artifact
  (run_type `scan` — additive extension of §11's enum, logged). Unknown
  property, unusable pack, or low-confidence identity ⇒ refuse, exit 2.
- ACCEPT: golden scan over synthetic properties — mills 52→warn / 63→flag,
  radon zone 1→warn, wildfire high→flag, wells count thresholds, missing
  field→insufficient_evidence; audit artifact emitted and verifiable;
  boundary suite still fully green (no new network surface).

### Constraints carried forward
- Python 3.11+, Pydantic v2, pytest; filesystem stores only; every commit
  cites the section it implements; fail closed everywhere; BuyerPack
  boundary tests must stay green untouched.
- Definition of done: full repo pytest green; `hearth ingest`, `hearth
  scan`, `hearth pack-status` work end-to-end on the synthetic fixtures in
  two commands each from the README; BUILD_NOTES updated (what exists /
  stubbed / deviations / next steps); branch shipped and merged.

*§13 — drafted in-session from BUILD_NOTES §5 recommendations and spec §10
build order. The landmine thresholds have been sitting in the pack as data
since P1-C; P2-D is where they earn their keep.*
