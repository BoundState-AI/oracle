# Slice S1R — Axis-Model Refactor (DRAFT — gated)

> **NOT A BUILD INPUT YET.** Activation requires ERRATA_RFC_001 boxes 2–3:
> the targeted ORACLE pass and the engine-spec v0.6.0 stamp. Box 1 (domain
> approval) is checked. Until then the binding contract is
> `docs/ORACLE_DISPOSITION_SPEC.md` v0.5.0 and this file is a draft.

**Build input for (when activated):** `py pipeline/oracle_build.py docs/slices/S1R_SPEC.md --repo . --fix-rounds 2 --coverage-floor 80 --check-cmd "py -m pytest tests -q" --ben-model <pinned>`
**Parent:** `docs/ERRATA_RFC_001_AXIS_MODEL.md` (migration rules §4),
`docs/RDW_SPEC.md` §7/§7.1/§10.3, `docs/FIXTURE_AXIS_MIGRATION.md`
(approved rows only).
**Base:** slice S1 as committed on `build/disposition-s1` (7120d44 +
follow-ups) — this slice refactors it, it does not restart it.

## Goal

Re-base `oracle/disposition/` from the single-code system of record to the
RDW six-axis model, preserving every S1 gate and invariant. The five codes
become a computed export view (RDW §7.1) with its own truth-table test.

## Deliverables

1. **`models.py` v2** — `DispositionUnit` carries the six axes
   (applicability, obligated_actor, organization_responsibility,
   implementation_state, approval_state, review via workflow_state).
   The v0.5 `code` field becomes a computed, read-only property
   implementing the §7.1 mapping incl. `Open/Not Met`. All S1 hardening
   survives verbatim: frozen models, no `model_copy` bypass of governed
   fields, evidenced physical-impossibility, acceptance gates, roll-up
   non-dispositional rule.
2. **TBD-reason vocabulary** — extend the closed sub-reason enum per RDW §7
   (`customer_input_missing` alias, `classification_unresolved` new); every
   TBD on any axis carries exactly one reason.
3. **Axis-coherence gates** (RDW §10.3) — the six enumerated gates as pure
   validators + a §7.1 **export truth table test** asserting every reachable
   axis combination yields exactly one export label or one named
   contradiction (same discipline as the roll-up badge table).
4. **Roll-ups** — composition vectors roll over export labels; badge total
   order unchanged with `Open/Not Met` inserted (position: between EX and
   MI in the OPEN→…→NA order — confirm in review).
5. **Fixture harness remap** — case assertions translated per the APPROVED
   rows of `FIXTURE_AXIS_MIGRATION.md`; ambiguous cases excluded until
   dispositioned (tracked as new labeled cases), with the exclusion listed
   in the harness output so coverage is never overstated.
6. **Tests** — updated schema/state/rollup/truth-table suites; the export
   mapping's guard tests (no exception softening; voluntary-expansion
   classes); all 26-case labels and merge-block semantics unchanged.

## Module standards

As S1 (BoundState headers, LOGGER, type hints, `extra="forbid"`, <50-line
functions, advisory-only posture per D-1).

## Done when

- Every S1 test that expressed an invariant (not a code-shape detail) still
  passes, ported.
- The §7.1 truth table is exhaustive and green; axis-coherence gates raise
  on every enumerated contradiction.
- Fixture harness green on approved translations; excluded cases explicitly
  reported.
- Full repo suite green; diff coverage ≥ 80%.

## Never touch

- `docs/ORACLE_DISPOSITION_SPEC.md` (v0.6.0 is stamped by the operator
  before this slice runs, never by the build), `docs/oracle_runs/*`,
  `tests/disposition/fixtures/*`, `docs/RDW_SPEC.md`,
  `docs/ERRATA_RFC_001_AXIS_MODEL.md`, `docs/FIXTURE_AXIS_MIGRATION.md`.
- Every existing `oracle/` module outside `oracle/disposition/`;
  `pipeline/*`; `.github/*`.

## Stop if

- Any approved fixture translation cannot be expressed on the six axes —
  that is an RFC defect, not a modeling choice; stop and report.
- The export truth table requires a seventh axis or a new label to close —
  same: stop and report.
- Behavioral contract change needed anywhere else — errata channel.
