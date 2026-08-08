# Atlas Handoff — Review of the Corpus-Replay Slice

**Context:** Internal code review of our own application by its own
team. This slice adds the acceptance harness that replays an
expert-adjudicated requirements corpus through the engine and compares
derived labels row by row. The corpus file itself contains our
engagement's scrubbed working data and lives OUTSIDE the repo (the
repo ships only a synthetic self-test); privacy patterns you'll see are
protection code.

**From:** Beth (builder — your pass is the independent gate).
**Under review:** the UNCOMMITTED working tree on `5d8889d` — new
`workpackage.py`, `replay.py`, `tests/disposition/test_corpus_replay.py`;
reworked `corpus.py` (v2 + identity-first), `corpus_scrub.py` (check),
`export_map.py`, `decision.py`, `session.py` (WorkPackageRecord wiring,
snapshot provenance); spec `docs/slices/RDW_CORPUS_REPLAY_SPEC.md`.
Suites at handoff: **663 passed / 4 skipped** — the engagement golden
RUNS in this environment via `RDW_CORPUS_PATH` (in yours it will skip
unless the operator provides the path; the synthetic self-test still
exercises the harness end to end).

## What changed (short form)

1. **Identity-first reconciliation (Fran ruling):** the EXACT tally
   gate is retired; the corpus locks row identities, tallies are
   computed reports. Coherence floor kept, now v2-aware.
2. **Corpus v2:** split axes + gate fields (citation/MI/EX/NYD) +
   evidence refs/date; work packages in a sibling CSV mapped to the new
   `WorkPackageRecord` (event-logged, replayed, supersession chain).
3. **Replay harness:** normal gated APIs only — evidence registered
   with per-row-unique ids (registry is last-wins by evidence_id),
   shared actions from work packages, elections, attestations, then
   per-row contract + readiness comparison with named mismatches.
4. **Three model allowances, all keyed to `split_elected` provenance**
   (converted legacy input behaves exactly as before — the frozen-table
   test still passes):
   - as_written under applicability=no → contract Meet(CW), readiness
     Technical N/A (the engagement's four CW-by-policy rows);
   - prerequisite-fact blocks (AMCP/classification/CEO) scope to
     evidenced/verified CLAIMS, never commitments;
   - split-elected exceptions stand under external responsibility.

## Areas needing scrutiny — start here

1. **The provenance flag as a security boundary.** `split_elected`
   now unlocks three allowances. Probe for ways to set it without a
   genuine split election (replay of tampered events is out of scope —
   the hash chain covers that — but check set_axes paths, library
   imports, advisor accepts, model_copy sites).
2. **Claim-scoping completeness.** With commitments unblocked, confirm
   an evidenced/verified claim still refuses under every unresolved
   prerequisite (AMCP, classification, CEO, evidence) at election AND
   at export re-check.
3. **Frozen-table + readiness equivalence** after the export_map and
   decision changes — rerun your exhaustive sweeps; only split-elected
   states may differ from pre-split behavior.
4. **Replay honesty.** The harness must never paper over a gap: probe
   that a corpus row the engine cannot derive produces a NAMED mismatch
   (wrong code, missing gate field, non-plan action, unknown id) rather
   than a silent skip; that `_flush_actions` doesn't fabricate
   plan-quality for ids without work packages; that evidence
   registration can't qualify the wrong row (the unique-id fix).
5. **Identity-first regression surface.** The retired tally gate: sweep
   for anything still importing/expecting the old EXPECTED_* constants
   or 115-row enforcement.
6. **WorkPackageRecord wiring** — event replay, supersession, sibling
   CSV parsing (header synonyms, delimiter splits).

Known open (rulings, not defects): §13.2's word list refuses
descriptive uses of "qualified/approved/complete" — 30 engagement
comments store as warnings pending a list refinement ruling; AMR-50's
contract NA (single-source read-across) awaits Fran's sign-off and is
recorded in the corpus with a reopening trigger.

Run the full suite independently and report your numbers. Verdicts,
new findings ranked with file:line + reproduction, suite result.

*Advisory-only per D-1. Gate-record docs are Beth-maintained.*
