# Atlas Handoff — Review of the Model-Split Slice (round 1)

**Context:** Internal code review of our own application by its own team.
This slice restructures the disposition data model per the adopted spec
`docs/slices/RDW_MODEL_SPLIT_SPEC.md`: the contract election
(`fulfillment_path`) and the execution fact (`execution_state`) are now
separate axes, fixing the P0 where one field served both derivations and
made "contract CW + readiness Not Met with Plan" (the engagement's
dominant pattern) inexpressible.

**From:** Beth (builder — your pass is the independent gate).
**Under review:** the UNCOMMITTED working tree on `dded550` — changes in
`codes.py`, `export_map.py`, `session.py`, `readiness.py`, `decision.py`,
`walk.py`, `graph.py`, `advisor.py`; new `tests/disposition/
test_model_split.py`; updated walk scripts in `test_fix3.py` /
`test_atlas_round3.py`. Suites at handoff: **646 passed / 5 skipped**
(635 + 11). Smoke walk verified end-to-end.

## What changed (short form)

- Two new axes + migration tables in `codes.py`
  (`split_from_legacy` / `legacy_from_split`), validated by an exhaustive
  frozen-table test: all 504 legacy combinations derive the EXACT
  pre-split §7.1 labels, including which combinations are contradictions.
- `UnitAxesState` carries the split axes + `split_elected`; a
  before-validator is the single conversion point (old event payloads
  replay unchanged). `set_axes` write rules: split writes back-derive the
  legacy view; legacy writes re-derive the split; other-axis writes on
  legacy-driven units re-derive (migration depends on
  applicability/approval).
- The Meet evidence hard gate now protects the execution CLAIM
  (evidenced/verified without qualifying evidence refuses), not the
  commitment — AMR-106 (CW, execution not started, plan action) elects
  and reads readiness Not Met with Plan.
- Interview: obligated actor and our responsibility are separate
  questions (auto-`owner` removed); fulfillment and execution are
  separate questions; evidence is cited at the claim; Not Yet Due is a
  visible choice; the plan offer extends to CW/MI commitments whose
  execution is not complete.
- Readiness derives from execution + evidence + actions; support on a
  program/CEO obligation with tracked work reads External Action.
- 29 pack-derived CEO `reopen_fact` edges: they propagate re-review on
  CEO identity change but never block elections or drive advisor LOW
  (AMR-2/AMR-4 keep their richer blocking edges); a drift test re-derives
  the list from the curated pack.

## Areas needing scrutiny — start here

1. **Write-rule state machine.** `set_axes` decides which side governs
   from which fields the caller passed plus `split_elected`. Probe for
   sequences that leave the split axes and the legacy view incoherent —
   especially interleaving legacy writes, split writes, and
   applicability/approval-only writes; and replay vs live divergence
   after such sequences.
2. **model_copy bypasses.** The before-validator only runs on
   construction/validate. `_would_be_label` was fixed to rebuild through
   validation; sweep for other `model_copy(update=...)` sites on units
   where an axis change could skip conversion.
3. **Frozen-table fidelity.** `test_model_split.py::_legacy_expected` is
   my transcription of the pre-split truth table. Verify it against git
   history (`git show dded550:oracle/disposition/export_map.py`) — if my
   transcription is wrong, the equivalence proof is circular.
4. **The documented divergence.** Alternative-control + plan-quality
   action now reads Not Met with Plan (was TBD Verify by fallthrough).
   Confirm nothing else drifted: any OTHER reachable readiness combo
   whose label changed is a defect, not a documented change.
5. **Evidence-gate rescoping.** Election of CW with execution not
   started no longer requires evidence. Check the export path,
   attestation, and review flows for anywhere that treated label Meet as
   implying verified evidence.
6. **Interview completeness.** The new question chain (actor →
   responsibility → fulfillment → execution → approval) must still reach
   every §7.1 label and every readiness label; probe quit/EOF at each new
   prompt (AR3 discipline holds?), the evidence-cite-at-claim cancel
   (downgrades to 'implemented'), and the extended plan offer.
7. **Reopen-only edge semantics.** Confirm reopen_fact edges cannot
   block any election, never put units at advisor LOW, DO reopen
   accepted units on CEO change, and that cycle detection ignores them.

Out of scope (spec round 2): registry-required evidence strictness (M3),
release gating on accepted review state (M4), advisor-after-elections
context enrichment + PROMPT_VERSION hash (M5); corpus-replay golden and
WorkPackageRecord (next slice).

Run the full suite independently and report your numbers. Verdicts,
new findings ranked with file:line + reproduction, suite result.

*Advisory-only per D-1. Gate-record docs are Beth-maintained.*
