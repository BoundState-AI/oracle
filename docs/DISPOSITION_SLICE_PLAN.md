# Disposition v1 — Slice Build Plan

**Status:** Draft for review — run one single-round ORACLE pass on THIS plan
(sequencing/coupling lens) before slice 1 starts. Do not re-run the full
convergence loop on the spec; its delta since the run is the decision record.
**Spec:** `docs/ORACLE_DISPOSITION_SPEC.md` v0.5.0 (build contract, protected)
**Method:** one slice = one `oracle_build.py` run (BUILD → CHECK → REVIEW →
GATE), committed on APPROVED, next slice builds on the committed state. Every
slice diff stays well under the 200K gate cap. Coverage floor 80 throughout.
**Author:** Dr. Joseph Wilde / Claude (Beth), 2026-07-28

## Sequencing logic

Deterministic spine first, judgment layers last: the assisted matrix must be
fully useful with **zero** LLM proposals (a human can enter every code by
hand and still get provenance, gates, and exports). LLM proposal quality then
becomes an additive layer whose failure modes are bounded by gates that
already exist — and the §16 kill-criteria are measured against working
machinery, not promises.

## The slices

### S1 — Data model + release state machine *(the spine)*
Unit schema (§7, Pydantic `extra="forbid"`), workflow_state machine (§7.1),
acceptance records, composition vectors + §1.1 roll-up badge derivation,
§2.3 sub-reason vocabulary as a closed enum, levy manifest model. Pure
models + pure functions, no I/O. Includes the fixture harness: case-count and
spec_rules-pointer drift assertions (§15/§16) go live here.
- **Done when:** every §7 field typed and validated; illegal state
  transitions raise; the §1.1 truth-table test passes for every child-code
  combination; machine code paths can set only `proposed`.
- **Stop if:** any need arises to edit the spec or fixture (protected — a
  conflict means the plan, not the contract, is wrong).

### S2 — Extraction & unit boundaries (§7.3)
Extend `shall_extractor` to emit disposition units: hierarchical IDs
(AMR-51 → AMR-51(e)), `applicability_clause` extraction, documented
ID-stability rule, boundary-confirmation workflow (`oracle disposition
confirm-units`), golden parse fixtures for 6030 + 6033 generated from the
existing builtin-pack sources.
- **Done when:** 6030/6033 re-extract to stable unit sets across two
  extractor invocations; golden parses committed; disposition of an
  unconfirmed unit raises.
- **Never touch:** existing pack outputs consumed by the review engine.

### S3 — Intake: scope + capability model (§3)
Intake schema with typed scope declarations, capability model with
`basis_evidence`, evidenced-impossibility rule failing closed, NA scope
citations plumbed. Fixture case 18 (genuine NA) representable; cases 4/5
groundwork (decided in S6).
- **Done when:** a `physical_impossibility` without evidence routes to human
  adjudication, never NA; intake refuses to start disposition when absent.

### S4 — Authority classification + report (§4)
Token scan → per-unit `authority_classification`, ambiguity fails closed to
`pending_review`, per-standard coverage across the levied set, authority
report rendering **before** the matrix. Start the annotated corpus (6030's
18 named-authority AMRs + 6033's parallel chain) for recall measurement.
- **Done when:** recall = 100% on the annotated corpus (kill-criterion
  measured here, D-2); fixture cases 1, 16, 26 assert; report ordering
  enforced.

### S5 — Matrix + §9 gates/flags + scope-change reopening
Matrix assembly from S1–S4; all 15 §9.1 blocking gates and 8 §9.2 flags as
deterministic checks with recorded human elections; gate report (§12 #5);
§3.2 reopening (scope-declaration change downgrades citing units to OPEN).
The v1-vacuous items (cycle-free-propagation gate, reserved sub-reasons)
implemented as trivially-passing with explicit v1.1 markers.
- **Done when:** every gate and flag has a test reproducing its
  observed-failure column; fixture consistency cases (2, 6, 7, 11) assert.

### S6 — Deterministic proposal layer + assisted evidence linking
NA-vs-zero-limit logic over the capability model (cases 4, 5 vs 18), paired
scope questions asked once (case 19 asserts OPEN — `must_not_propose` goes
live), §8 banding with LOW → OPEN-as-question, BSMS linker in assisted mode:
bundle retrieval (roles per §14.1) over packs + supplier documents,
explainable match basis, derived `link_confidence`, grader pass, threshold →
`evidence_absent`.
- **Done when:** linker precision@1 ≥ 0.95 / false-link ≤ 5% on the held-out
  set (kill-criteria measured, D-2); all `na_vs_zero_limit` cases green.

### S7 — LLM proposal layer + calibration eval
Remap proposer (§5, per-unit granularity — case 3), intent statements,
voluntary-expansion detection feeding §9.2 (cases 6, 9, 10), definitional
exclusion arguments (case 25), narrative checks (cases 12–15). Probabilistic
eval harness per §16 (held-out, versioned, distribution-reported), separate
from the deterministic CHECK.
- **Done when:** zero false-CW on process-sensitive classes of the golden
  package; ≥ 60% proposability floor measured (D-2 build-commitment
  decision point: below floor → v1 ships assisted-only and this slice's
  proposals stay dark).

### S8 — Outputs + CLI closure
Countersign export (state-preserving, re-import gated), exception detail,
narrative computed from the matrix (case 22), referenced-artifact gating
(case 23), advisory labeling on every artifact (D-1), `oracle disposition`
CLI verb finalized, docs.
- **Done when:** full §12 output contract emits in order on the reference
  corpus; a package with any OPEN/unelected unit refuses release-marking.

## Fixture activation map

| Slice | Cases that become executable assertions |
|---|---|
| S1 | truth-table, count/pointer drift |
| S2 | 3 (unit granularity groundwork), 24 (citation-vs-corpus) |
| S3 | 18 |
| S4 | 1, 16, 26 |
| S5 | 2, 6, 7, 11, 17* , 21* (*consistency aspects only; propagation itself is v1.1) |
| S6 | 4, 5, 19, 20 |
| S7 | 3, 8–10, 12–15, 25 |
| S8 | 22, 23 |

All 26 cases active by S8; `expert_corrected`/`expert_discovered` regressions
merge-block from the slice that activates them.

## Kill-criteria measurement milestones (D-2)

- After S4: authority recall (must be 100% to proceed past S4).
- After S6: linker precision / false-link.
- After S7: false-CW on process-sensitive classes; proposability floor —
  **the build-commitment decision point**: below floor, S7's proposals ship
  dark and v1 is assisted-only, per §16.

## Standing constraints (every slice)

- `--coverage-floor 80`; full suite green; protected paths untouched (spec,
  run records, fixture — enforced by CHECK, not trust).
- No slice edits the spec. A spec defect found mid-build is a finding routed
  back through review, not a quiet patch.
- Commit on APPROVED only; one slice per branch; PIPELINE_REPORT.md retained
  per slice in `oracle_builds/`.

## Two coherence notes from slicing (for the plan review to weigh)

1. §9.1's cycle-free-propagation gate and the two reserved sub-reasons are
   vacuous until v1.1 — implemented as explicit trivial-passes in S5 so the
   gate table stays complete without pretending machinery exists.
2. Case 17 and 21 are only partially assertable in v1 (their consistency
   surface, not propagation); the fixture activation map marks this so
   "26/26 active" is never misread as "propagation tested."
