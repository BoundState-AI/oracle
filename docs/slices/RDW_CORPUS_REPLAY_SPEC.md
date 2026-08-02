# RDW Build Spec — Corpus-Replay Golden (identity-first)

**Builder:** Beth. **Governing rulings:** Fran 2026-08-02 (identity-first:
"the golden should lock adjudicated row identities and compute its
totals — not enforce totals"; the six-row contract adjudication) and the
operator's AMR-57 single-source confirmation. **Anchors:** AMR-2, 14,
29, 38, 51, 57, 97, 106, 110, 113, 115.

## CR1 — WorkPackageRecord

New session-level record mirroring the engagement Gap Action Register:
`wp_id, title, gate, priority, status (open|blocked|closed), owner,
objective, affected_unit_ids, dependencies, execution_actions,
deliverables, objective_evidence, exit_criteria`. Event-logged
(`work_package_recorded`, supersession by wp_id like actions), replayed
into `SessionState.work_packages`. ActionRecord.work_package references
a wp_id; readiness/roadmap exports may group by it.

## CR2 — Corpus v2 (identity-first)

`CorpusRow` gains the columns replay needs, all optional for legacy
files: `obligated_actor, fulfillment_path, execution_state,
scope_citation, intent_statement, alternative_control, control_class,
exception_basis, permanent_relief_basis, closure_action_id,
not_yet_due (bool-ish), not_yet_due_justification, evidence_date`.
Work packages ride in a sibling CSV (`<corpus stem>.workpackages.csv`,
auto-discovered; header = WorkPackageRecord fields).

**Reconciliation is rewritten per Fran:** the EXACT tally gate
(EXPECTED_CONTRACT/EXPECTED_READINESS equality) is RETIRED. The corpus
file itself is the identity lock; `assert_reconciled` now enforces
per-row coherence (existing floor) + unique ids only, and `check()`
REPORTS computed contract/readiness tallies and work-package count.
Tallies are outputs, never gates.

## CR3 — Replay harness (the golden)

`oracle/disposition/replay.py`: `replay_corpus(corpus_path, session_dir)`
builds a REAL session through normal APIs only — open (curated packs),
register+attach evidence (rows with refs+date), record work packages
and actions, elect axes (split axes preferred; legacy conversion
otherwise; gate fields from the corpus row), attest accepted
(accepted_with_tbd where axes remain TBD) — then derives per row:
`export_label()` vs the row's locked contract code and
`map_readiness(...)` vs the row's locked readiness label. Returns a
row-by-row report; ANY mismatch is a failure with the row named.

Tests:
- `test_corpus_replay_synthetic.py`: a SYNTHETIC corpus (explicitly
  marked; identities are NOT engagement truth) covering every label
  class end-to-end keylessly — the harness itself is CI-tested.
- `test_corpus_replay_golden.py`: skips without `RDW_CORPUS_PATH`;
  with it, full 115-row replay + the eleven in-repo anchor rows
  (standard-scoped ids + expected labels only — the full map stays
  outside the repo).

## CR4 — Synthetic fixtures marked

`test_fix3.py` corpus builders renamed/documented SYNTHETIC; no test
asserts engagement row identities from synthetic data (operator
instruction 2026-08-02).

## Deferred to the guide round

Full 115-section implementation guide + 16 work-package chapters +
DOCX rendering (consumes CR1; separate build so this slice stays
reviewable).

## Non-goals

The corpus file in the repo (never); editing the protected fixture
(its historical counts stand with their own hedge note); tally
enforcement anywhere.

*Advisory-only per D-1. Atlas gates before commit.*
