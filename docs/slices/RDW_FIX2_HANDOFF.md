# RDW Fix Round 2 — Grok Handoff

**Base:** `2ab4e81` on `build/rdw-mvp-grok`. **Authority:** Atlas round-2
findings + triage in `docs/slices/RDW_REVIEW_BUNDLE_2bc0276.md` (§ "Atlas
round 2"), under Dr. Wilde's rulings of 2026-07-30: **the assistant is the
core; this is a single-user tool; no multi-user — the six-role review board
is removed by subtraction, multi-user enforcement parks until a later
phase.** Where this handoff is silent, the bundle doc and the prior build
spec govern.

## F1 — Stale accepted rows must not export (A1, Critical)

- §10.2 propagation: when a confirmed fact marks units for re-review, any
  affected unit whose `review_state` is `accepted` transitions to
  `superseded` (recorded as an event; replay-faithful). The prior
  acceptance no longer stands; re-attestation is required.
- `build_matrix_rows` refuses units present in `needs_rereview` (same
  refusal style as blocked labels; error names the units). No flag to
  bypass — the user clears re-review by re-electing/attesting or
  `clear_rereview`, both logged.

## F2 — Evidence must qualify, not merely exist (A2, Critical)

- When an `EvidenceStore` exists at `<session>/evidence`, the Meet gate
  requires `unit_has_qualifying_meet_evidence(unit_id)` **and** at least
  one cited `EvidenceRef` matching a registered artifact on
  `(doc_id, revision)`. Expired/withdrawn/undated artifacts do not qualify
  (the existing `evidence_supports_meet()` — use it, don't reimplement).
- Phantom-ref check compares `(doc_id, revision)` pairs, not doc_id alone.
- `export_all` must never synthesize the known-set from the refs under
  validation. No registry → skip the check and stamp
  "phantom-ref check: skipped (no evidence registry)" into the export Meta
  (CSV comment block, DOCX paragraph, XLSX Meta sheet). No silent skip.
- No registry → election floor stays `bool(evidence_refs)` (v0 posture),
  with a LOGGER warning that refs are unverified.

## F3 — Propagation must be durable without a second event (A3, High)

- Make replay deterministic: `_replay_into` recomputes propagation (graph
  over confirmed facts, same code path as live) on each replayed
  fact-confirmed event, then applies `rereview_cleared` events in order.
  The `propagation_rereview` event becomes audit-only — replay must not
  depend on it. This closes the crash window between the two appends.
- Re-review diffs recomputed at replay from the replayed state.

## F4 — scope_citation must be a real citation (A6, High)

- Strip + reject whitespace-only `scope_citation` at `UnitAxesState`
  validation; the decision engine treats stripped-empty as absent.

## F5 — Comment refusal re-prompts, never aborts (A8, Medium)

- Move the accept/edit comment flow inside the walk's retry handling: a
  §13.2 refusal shows the hits and re-prompts for another edit; the unit
  stays open; the walk continues. While there, narrow the
  `except (SessionError, ValueError, Exception)` tuple — no broad
  `Exception` (repo standard).

## F6 — Review board subtraction (A4 + A7, per ruling)

- Remove `ReviewPackage`/`Assignment` machinery from the product path.
  `review.py` reduces to the role vocabulary + a docstring noting
  multi-user enforcement is parked for a later phase.
- Single API, on the session:
  `attest_unit(unit_id, *, actor_name, role, decision, accepted_with_tbd=False, comment="")`
  - `role`: the six-role `Literal` vocabulary — **recorded, not enforced**
    (single-operator per RDW §5; there is no identity system to enforce
    against).
  - `decision`: `accepted` | `rejected`.
  - Transition legality enforced: `proposed|in_review → accepted|rejected`;
    `rejected → proposed` (re-open); `superseded → proposed`;
    `accepted → superseded` only via F1 propagation. **Never**
    `accepted → proposed` directly.
  - Review-coherence gate: TBD axes require `accepted_with_tbd=True`.
  - Appends a hash-chained event; replay restores **both** `review_state`
    and `accepted_with_tbd` (A7).
- `audit.py` + CLI audit read attestation events from the event log;
  `review_package.json` loading is removed.
- Update phase-3 tests to the new API: keep coherence-gate and
  transition-legality coverage; assignment/spoof tests are deleted with
  the machinery they tested.

## Deferred — do NOT do this round

- A5 (curated packs lose classification gating): waits for the Phase 4
  pack-dependency slice (pack-declared dependency edges per RDW §9.1
  Logic group).
- The assistant slice (explain / suggest-closure / learn): next build
  after this round, spec to follow from Beth. Do not start it here.

## Done when

- Every Atlas round-2 probe (bundle doc § "Atlas round 2") fails closed:
  stale accepted Meet refuses export; expired/revision-mismatched evidence
  refuses Meet; crash between fact append and propagation cannot lose
  re-review across resume; whitespace scope_citation refused; edited
  prohibited comment re-prompts without aborting; `attest_unit` refuses
  illegal transitions and TBD-accepts without election; replay round-trips
  `review_state` + `accepted_with_tbd`.
- Disposition + full suites green. Golden unaffected or updated
  deliberately.

## Never touch

As prior rounds: protected files per `.oracle_protected`, everything
outside `oracle/disposition/` + `tests/disposition/` + minimal
`oracle/cli.py` wiring. Leave `docs/slices/RDW_REVIEW_BUNDLE_2bc0276.md`
and the handoff docs alone — Beth maintains the gate record.

*Advisory-only per D-1.*
