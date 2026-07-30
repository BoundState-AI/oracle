# RDW Assistant Slice — Build Spec (Tailor shell over the RDW engine)

**Build:** manual Grok build, Beth + Atlas review at the gate (same loop as
the MVP and fix rounds).
**Authority:** RDW_SPEC v0.2 (§10 decision/language split, §11 interview,
§13 comments, §14.1 workspace), ORACLE_DISPOSITION_SPEC v0.5.0 (D-1
advisory posture, D-7/BSMS grounded retrieval, §8 proposal bands, P-2 data
governance), Fran's tailor-helper review of 2026-07-30 (recorded in
`RDW_REVIEW_BUNDLE_2bc0276.md`), and Dr. Wilde's rulings of 2026-07-30:
**the assistant is the core; single-user tool; no multi-user.**
**Base:** `build/rdw-mvp-grok` at `6ddf073` (fix round 2 committed; all
gates enforced; suites green 537/4).
**Product sentence (the spec in one line):** reads the requirements one at
a time, tells you what each is asking, works with you to see where you
land, offers suggestions on how to close Not-Mets, and learns.

## Stage 0 — Pack re-curation (PREREQUISITE, human-in-the-loop)

The builtin 6030 pack is corrupted (77/115 shall_texts end in a dangling
`[`; AMR-2 truncated — bundle doc, pack-integrity finding). The authoritative
source PDF (NASA-STD-6030, Approved 2021-04-21, Baseline, 190 pp, public
release) has been provided by the operator.

1. **Source pinned (2026-07-30):**
   `docs/2021-04-21_nasa-std-6030-approveddocx.pdf` (3,317,520 bytes),
   `source_hash` =
   `sha256:5246d3b992ac0cc7a7deadb4c3c10284444add7d7e055968ae011d671d5a96cd`.
   Verified: pypdf extracts the text layer cleanly (190 pages); all 115
   `[AMR-n]` markers present, none missing; AMR-2 extracts complete.
   Caution: `[AMR-n]` markers appear BOTH in the body (§4–8) and in the
   Appendix A compliance matrix — extract shall texts + rationale from the
   main body only, then use Appendix A as the completeness cross-check.
2. Re-extract all 115 AMR verbatim shall texts + section + page + rationale
   (the italic `[Rationale: ...]` blocks) + guidance notes into a draft pack
   via the existing `DraftPackWorkspace` (import → review → promote —
   FR-003). **Verbatim means verbatim**: no paraphrase, no truncation;
   spot-check every text against the PDF page cited.
3. Operator (Dr. Wilde) reviews the draft; on `mark_reviewed` +
   `promote_to`, the curated pack lands at
   `oracle/disposition/data/nasa_std_6030_curated.json` with `source_hash`
   and per-requirement `source_coordinates` (page).
4. `load_rdw_default_packs` prefers the curated pack over the builtin when
   present (builtin stays untouched and protected; it remains the fallback).
5. Rationale/guidance text rides along as `rationale` / `notes` fields —
   the advisor grounds its explanations in these, not in model memory.

## Stage A — Deterministic record deltas (Fran's gaps; no LLM)

1. **Raw answer retention:** every interview answer is stored verbatim on
   the event log (`answer_recorded`: unit_id, question_key, raw text,
   actor, ts) before any mapping to axes. Replay-faithful.
2. **ActionRecord** replaces the bare `open_actions` strings: id (e.g.
   `GOV-01`), title, owner, deliverable, exit_criteria, priority,
   due_or_trigger, work_package, affected_unit_ids. Frozen model,
   event-logged, supersession by successor records. Existing string
   actions migrate as minimal records.
3. **Readiness derived view** (second §7.1-style mapping — a view, never
   SoR): Met / Not Met with Plan / TBD Verify / External Action /
   Not Yet Due / Technical N/A, derived from axes + linked ActionRecords +
   the `not_yet_due` marker:
   - Met = meets_as_written + qualifying evidence
   - Not Met with Plan = not_met (or partial) + at least one open
     ActionRecord with owner + exit_criteria
   - External Action = org_responsibility external + open action
   - TBD Verify = any TBD axis with reason
   - Technical N/A = applicability no + scope_citation
   - Not Yet Due = `not_yet_due` marker set with justification (e.g.
     "levied prior to flight-hardware production; program not at that
     phase") — new optional field, event-logged, justification required.
   Exhaustive truth-table test, same discipline as §7.1.
4. **EX closure gates:** Exception label additionally requires
   exception_basis + (closure_path action OR permanent_relief_basis) —
   enforced at election like the other C1 gates.

## Stage B — Advisor service (the LLM layer, P-2 governed)

1. `AdvisorService` interface with two implementations:
   - `DeterministicAdvisor` — template-based, used by ALL tests (keyless
     determinism contract holds; red still means regression).
   - `LiveAdvisor` — Anthropic via existing model plumbing
     (`ORACLE_BETH_MODEL`-style env override, e.g. `RDW_ADVISOR_MODEL`).
2. Three capabilities, all grounded ONLY in supplied context (curated pack
   text + rationale + definitions + fact ledger), BSMS-style per D-7 —
   include the evidence bundle in the prompt, never rely on model memory:
   - **explain(unit)** — plain-language "what is this AMR asking", rendered
     beneath the verbatim text and labeled *interpretation* (§11).
   - **propose(unit, facts)** — axis proposal with ProposalBand + §8 basis;
     LOW band → proposes NOTHING (unit stays OPEN with reason, rendered as
     a question). Never bypasses `evaluate_unit`; a blocked label is never
     proposed.
   - **suggest_closure(unit, facts)** — draft ActionRecord(s) + evidence
     requests for Not-Met/Exception/TBD rows, bounded by the fact ledger
     (§13: never exceeds evidence; states unresolved dependencies).
3. Every advisor output is an event: model id, prompt version hash, input
   context hash, output, band. Outputs are `proposed` — nothing the advisor
   says changes an axis, comment, or action without operator attestation.
4. §13.2 prohibited-language check + a grader pass (second deterministic
   check: claims-vs-facts spot check) on every draft before display.
5. P-2: the pack text is public-release NASA material — clear for model
   calls. Project facts are the operator's own engagement data — live use
   is his call at runtime (`--advisor` opt-in flag); tests use the
   deterministic advisor and the scrubbed Appendix-B seed only.

## Stage C — Shell (harvest the Tailor interaction design)

Read-only harvest from `feat/tailor-helper` (`TailorTab.tsx`, advisor loop
UX). The disposition engine is the only backend; nothing from
`oracle/tailor/` backend code is ported.

1. CLI-first: `oracle disposition walk --advisor` gains the §14.1 panes in
   terminal form — verbatim text + locator FIRST, explanation beneath
   (labeled), why-can't-this-be-Meet, live axes + both derived labels
   (contract + readiness), proposed comment, one question at a time.
2. Advisor proposals render with band + basis; accept = attestation
   (existing `attest_unit` / election machinery), edit = re-checked, skip =
   TBD with reason. Known facts are never re-asked.
3. Stretch (only if Stages 0-B land clean): FastAPI endpoints over the
   session API mirroring the harvested TailorTab flow, for the existing
   `frontend/`. Do not block the slice on this.

## Stage D — Learn (cross-project context library)

1. `oracle disposition library export <session> <out.json>`: confirmed
   facts, paired answers, attested dispositions + rationales, action
   patterns — keyed by requirement id + fact key, with provenance
   (session id, date). No customer identifiers: refuse export if any
   fact statement matches the engagement-identifier blocklist supplied by
   the operator (D-3 posture).
2. `library import` into a new session pre-seeds facts **as assumptions**
   (`assumed=True`, owner = operator, source = library provenance) — the
   assumption discipline stands: nothing imported is confirmed until the
   operator confirms it in the new engagement. Paired-answer keys pre-fill
   the same way.
3. That is v1 "learns": the second engagement starts warm, honestly.

## Stage E — Dual exports (two products, one record)

1. **External:** Appendix-A-format compliance matrix (Section /
   Description / Requirement / Applicable / Comments — the format the
   standard itself ships in Appendix A) + existing supplier matrix, both
   from the contract-label view. D-1 banner, computed counts, refusals as
   built.
2. **Internal:** gap-closure / readiness roadmap grouped by work_package:
   every non-Met row with its ActionRecords (owner, deliverable, exit
   criteria, due/trigger), readiness counts, action ids linking back to
   every affected AMR.
3. Both stamped with session id, pack source_hash, spec versions, advisor
   model/prompt versions used (if any).

## Tests (keyless, deterministic)

- Stage 0: curated-pack integrity — zero dangling `[`, AMR-2 complete,
  115 ids, per-record page present, hash pin.
- Stage A: readiness truth table exhaustive; ActionRecord round-trip +
  replay; EX closure gate; raw-answer retention on replay.
- Stage B: DeterministicAdvisor — LOW band proposes nothing
  (`must_not_propose` class); blocked labels never proposed; §13.2 +
  grader refusals; advisor events carry model/prompt/context hashes.
- Stage C: scripted walk with advisor — explain shown labeled, proposal
  attested, edited proposal re-checked, skip → TBD.
- Stage D: export/import round-trip; imported facts are assumptions;
  blocklist refusal.
- Stage E: Appendix-A + roadmap goldens for the scripted session; counts
  computed at render.
- **115-row golden replay (Fran's acceptance test): BLOCKED pending
  scrubbed engagement records from the operator.** Reconciliation targets
  when it lands: readiness 2 Met / 39 Not Met with Plan / 34 TBD /
  18 program actions / 21 Technical N/A / 1 Not Yet Due; contract
  85 CW / 6 MI / 7 EX / 17 NA. Wire the harness now against the 3-AMR
  golden; leave the loader ready for the full corpus.

## Standards

As all prior slices: BoundState headers (advisory-only per D-1), `LOGGER`,
type hints, `extra="forbid"` (advisor I/O models included), <50-line
functions, no prints in library code (CLI presentation excepted), tests
keyless-deterministic, golden fixtures regenerated only deliberately.

## Never touch

`docs/ORACLE_DISPOSITION_SPEC.md`, `docs/RDW_SPEC.md`, errata + fixture
migration docs, `docs/oracle_runs/*`, `tests/disposition/fixtures/*`,
`oracle/builtin_packs/*` (the corrupt pack is superseded by the curated
one, never edited), every `oracle/` module outside `oracle/disposition/`,
`oracle/tailor/*` on its branch (read-only harvest), `pipeline/*`,
`.github/*`, and the gate-record docs in `docs/slices/` (Beth maintains).

## Stop if

- Verbatim extraction from the PDF is ambiguous for any AMR (report the
  list; the operator adjudicates against the paper copy).
- Any capability requires the advisor to override or precede a
  deterministic gate.
- The readiness truth table cannot close without a new axis (RFC, stop).
- A test requires a live API key.

## Done when

- Stage tests green; full suite green; diff coverage ≥ 80%.
- The operator can: open a session on the curated pack, walk AMR-1 with
  `--advisor` (explanation shown, proposal banded, attestation recorded),
  get closure suggestions on AMR-14 as structured actions, export both
  products, export the library, and start a second session pre-seeded with
  assumptions from it — all without an API key except the live-advisor
  moments he opts into.
