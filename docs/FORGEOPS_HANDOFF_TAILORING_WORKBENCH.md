# Handoff — ORACLE/RDW → Requirements Tailoring & Gap Analysis Workbench

**To:** the forgeops crew. **From:** Beth (builder, boundstate_oracle).
**Date:** 2026-08-02. **Authority:** Dr. Wilde's workbench decision
(generic Requirements Tailoring & Gap Analysis Workbench; 6030 is the
first validation corpus, not product vocabulary; T0–T6 rebaseline).

This document is the current truth of the ORACLE-side work you are
inheriting concepts, capabilities, and lessons from. Everything below is
committed on branch `build/rdw-mvp-grok` of `boundstate_oracle`, HEAD
`51b8e7f`, suite 668 passed / 4 skipped (672 collected). Six commits,
each independently gated by an adversarial reviewer before merge:
`133ed41 → dded550 → 793f5c8 → 5d8889d → 51b8e7f`.

## 1. What is PROVEN (use it as the existence proof, port the ideas)

**The acceptance result that matters:** a real 115-requirement
engagement (NASA-STD-6030, human-adjudicated with an expert) replays
through the engine via normal gated APIs — facts, elections, evidence
registration, actions, work packages, attestations — and every
engine-DERIVED disposition code and readiness label matches the locked,
human-adjudicated row identity. Row-by-row, not tallies.
(`oracle/disposition/replay.py`; the corpus lives OUTSIDE the repo
behind `RDW_CORPUS_PATH`; a synthetic self-test covers every label
class keylessly in CI.)

The workflow in the decision — source + scope + evidence ↔ helper, one
requirement at a time → human-adjudicated matrix → gaps/actions/exports
— is exactly what this codebase does end-to-end today, specialized to
6030. The workbench generalizes it.

## 2. Record mapping (RDW today → workbench records)

| Workbench record | RDW equivalent | Port notes |
|---|---|---|
| SourceDocumentRevision | pack pinning: content hash + `PackPinError` on drift (`rulepack.py`, `packs.py`) | levy rule: drift = new revision, never silent substitution; sessions pin the hash and refuse mismatches |
| SourceRequirement | `RequirementRecord` (verbatim shall_text, locator, source tag, provenance) | keep verbatim text sacred — a curation defect class we hit was silent dehyphenation corrupting source text |
| ProjectScopeDeclaration | scope declarations (SD-1…) + `Fact` ledger (assumed vs confirmed, owner, supersession) | the assumed/confirmed distinction is load-bearing: assumptions never silently confirm; supersession triggers re-review propagation |
| TailoringScheme | **DELTA** — RDW has enum labels (`ExportLabel`, codes CW/MI/EX/NA) | the decision makes code vocabulary DATA. Do not port the enums; port the *derivation discipline* (§4 below) |
| TailoringAssessment | `UnitAxesState`: applicability, obligated actor, org responsibility, **fulfillment_path** (the contract election) + **execution_state** (the execution fact), approval, rationale/comment, adjudicator, supersession via review states | see §4 — the fulfillment/execution split is the single most important modeling lesson |
| Gap | **DELTA** — RDW derives gaps (readiness view) rather than storing them | the decision's first-class Gap + typed GapWorkItem relation is better; RDW's `ActionRecord`/`WorkPackageRecord` (plan-quality floor: owner + exit criteria) are the closure-action shape |
| EvidenceLink | `EvidenceRef` (typed citation) + `EvidenceStore` registry (dates, expiry, withdrawal, fail-closed parsing) | a CITATION is not EVIDENCE: unregistered/undated citations never qualify (fail closed); registry is last-wins by evidence id — give links unique ids |
| MatrixRevision | export suite with refusal discipline + DRAFT watermark vs release gating on review-accepted rows | exports re-check every gate (defense in depth); external products refuse unaccepted rows unless explicitly watermarked DRAFT |
| AssistantRun | `advisor_outputs` events: model id, PROMPT_VERSION (content hash of prompt text), context hash, output hash (finalize-hash-last), accept/edit/reject via the walk | closest existing implementation of the decision's AssistantRun; §5 below |

## 3. The event-sourcing spine (port as-is in spirit)

Hash-chained append-only event log; reload = replay; `verify()` fails
on any tamper. Atomic multi-event batches (`append_many`, single
temp+rename) so multi-record operations can never persist a prefix.
Replay and live mutation MUST apply state changes in the same order —
we shipped a live-vs-resume divergence and a reviewer caught it;
pin replay==resume equality in tests from day one.

## 4. The hardest-won modeling lessons (do not relearn these)

1. **Commitment ≠ execution.** One axis serving both the contract
   answer ("we will comply as written") and the execution state ("not
   started") made the engagement's dominant pattern — committed-but-not-
   met-with-plan — inexpressible. The split (`fulfillment_path` vs
   `execution_state`) fixed it. Your TailoringAssessment already
   separates code from implementation/verification/evidence states —
   keep them independent; derive views, never store two views in one
   field.
2. **Identity-first goldens.** Lock adjudicated ROW identities; compute
   totals for reporting; never enforce totals. We were caught fitting
   row codes to a target tally ("code-fitting") by the domain expert —
   enforcing 85/6/7/17 would have forced two requirements into false
   exception codes. The stale-tally constant was retired.
3. **Gates protect CLAIMS, not commitments, and must be
   label-independent.** Evidence and prerequisite-fact gates originally
   blocked only the "Meet" label; electing an exception-mapped claim
   sailed past. Now: an evidenced/verified execution claim under an
   unresolved prerequisite refuses regardless of which code it maps to;
   a commitment with execution not-started elects and the readiness
   view carries the open dependency.
4. **Provenance flags are derived, never caller-settable.** A
   `split_elected` provenance flag unlocked model allowances; a reviewer
   forged it through the public API in one call. Any "this state was
   explicitly elected" marker must be computed from the shape of the
   write, and rejected as input.
5. **Fail closed everywhere at boundaries.** Unparseable dates =
   invalid evidence; missing registry = citation does not qualify;
   unknown vocabulary = load refusal; half-provided axis pairs = loud
   refusal, never defaulting; identifier scan runs on the FINAL
   normalized cells immediately before write (normalization itself once
   introduced a blocked term after the scan).
6. **Preserve source wording; classification is interpretation.** The
   decision's ruling on shall/should/may matches what we learned: any
   normalized normativity judgment is an attributed interpretation, not
   source data.

## 5. The helper (T2) — what RDW's advisor already proves

The decision's helper contract (structured proposals only; never
silently mutate; accept/edit/reject; full provenance) is implemented
here for Claude and ports directly to `gpt-5.6-terra`:

- **Structured JSON proposals**, schema-validated; anything the
  deterministic gates block is stripped before display; a proposal
  whose shown label diverges from what its fields actually derive is
  refused (we shipped that divergence once — it was a critical).
- **Deterministic fallback** on any parse/validation failure, recorded
  AS a fallback in the run record — never a silent substitution.
- **Provenance:** model id, PROMPT_VERSION = content hash of the
  prompt templates (a stale "v1" tag can never mask an edited prompt),
  context hash of the exact input bundle, output hash computed last,
  accept/edit/reject outcome event-logged.
- **Ordering:** closure/summary drafting runs AFTER the human's
  decisions with the context the interview actually produced (raw
  answers, evidence, actions) — never a stale pre-decision snapshot.
- **Language gates on drafts:** a prohibited-language + claims-vs-facts
  grader refuses drafts asserting compliance the fact ledger doesn't
  support. OPEN RULING to carry over: our word-list refuses descriptive
  uses of "qualified/approved/complete" — refine to claim-PHRASES.
- **LOW-information discipline:** when the unit-relevant inputs are
  unresolved, the helper proposes NOTHING and asks the scope question.
  Relevance comes from an explicit dependency graph, not a global scan.

## 6. Privacy/data boundary (D-3 — matches the decision's rule)

No customer, export-controlled, or operational data in any repo. The
mechanism that works: an operator terms file OUTSIDE the repo; a scrub
tool that maps arbitrary spreadsheet headers, replaces terms, scans
every final cell against identifier patterns, and refuses to write on
any hit (`corpus_scrub.py` — atomic writes, never over its inputs,
terms REQUIRED to write). The engagement corpus lives outside the repo;
tests skip-with-reason without it; CI stays keyless and deterministic
(red always means regression, never vendor outage).

## 7. The review loop that made the quality (process handoff)

Builder never self-gates. Every slice: spec → build → keyless suite →
independent adversarial review with reproducible probes → builder fixes
with pinned regressions → independent re-verdict → operator authorizes
commit. Across six gated commits this caught ~40 real defects including
two criticals and one forged-provenance hole. Reviewer-model note: our
gate reviewer (`gpt-5.6-terra`) once refused a review whose handoff used
attack-flavored vocabulary; neutral QA language plus a sentence naming
privacy-protection code as such fixed it. Write your review handoffs
that way from the start.

## 8. Pointers (all in boundstate_oracle, branch build/rdw-mvp-grok)

- Gate record (every review + fix round): `docs/slices/RDW_REVIEW_BUNDLE_2bc0276.md`
- Specs: `docs/slices/RDW_MODEL_SPLIT_SPEC.md`, `RDW_CORPUS_REPLAY_SPEC.md`,
  `RDW_CORPUS_SCRUB_SLICE.md`; contract: `docs/ORACLE_DISPOSITION_SPEC.md`
  (protected)
- Engine: `oracle/disposition/` — `session.py` (event-sourced state,
  gates), `export_map.py` + `readiness.py` (derived views),
  `decision.py` (deterministic blocks), `advisor.py` (helper),
  `replay.py` (identity golden), `corpus.py`/`corpus_scrub.py`
  (ingest + D-3), `workpackage.py`, `evidence.py`, `eventlog.py`
- Validation corpus: curated 6030 pack (public standard text) in-repo;
  the adjudicated engagement corpus stays outside repos (operator
  holds it; the golden consumes it via `RDW_CORPUS_PATH`)
- ORACLE extraction/review capabilities for T5/T6: `oracle/` top level
  (pack generation from regulatory PDFs, multi-oracle review)

## 9. Open items that transfer with the work

- Fran's sign-off on one row adjudication (AMR-50 contract NA via the
  single-source read-across; reopening trigger recorded in-corpus).
- §13.2 word-list refinement ruling (see §5).
- RDW guide round (115 sections + 16 work-package chapters + DOCX) —
  unstarted; equivalent functionality lands as the workbench's T4
  management-deck/export stage.

*Advisory-only per D-1. This handoff contains no engagement
identifiers; the pilot-context names stay outside every repo.*
