# Atlas Handoff — Fix-Round Review of `2ab4e81`

**From:** Beth. **Requested by:** Dr. Wilde, 2026-07-30.
**Branch:** `build/rdw-mvp-grok` (local, not pushed). HEAD = `2ab4e81`
"fix(disposition): enforce decision gates on elections and export (review
C1-C3, H1-H5)". ~715 insertions across 14 files.

## Scope — what to do and what to skip

**Do:** adversarial *new-hole discovery* on the `2ab4e81` diff only.
**Skip:** re-verifying the bundled findings — Beth re-ran every known attack
against this commit and recorded results in
`docs/slices/RDW_REVIEW_BUNDLE_2bc0276.md` § "Fix verification — 2ab4e81"
(C1–C3, H1–H5, M1–M3, M6 all confirmed fixed by execution). Re-treading that
table is wasted effort; your value both prior rounds was finding attacks
nobody listed.

**Also requested:** one independent full-suite run. Grok reports 111
disposition / 528 full, 4 skipped; Beth's environment (VSCode extension)
auto-rejects pytest invocations, so her confirmation is pending an
operator-run result. Your prior run was interrupted at 88.

## Known residuals — already logged, don't re-report

1. `ReviewPackage.decide()` without `session=`/`unit=` skips the
   review-coherence check (standalone-JSON path). Closes with the model
   unification slice.
2. `set_axes(enforce_decision=False)` is a caller opt-out (used for
   skip/quit → TBD); export re-checks, so defense-in-depth.
3. walk.py answer-retry catches broad `Exception` (standards nit).

New *angles* on these are in scope; their existence is not news.

## Suggested attack surface (new in this diff)

1. **Event replay, three new event types** — `propagation_rereview`,
   `rereview_cleared`, `review_decision` (session.py `_replay_into`).
   Ordering effects, duplicate events, cleared-then-repropagated units,
   replay of a `review_decision` for a unit id absent from the current pack,
   diff payload growth (before-images are embedded in `propagation_rereview`
   events — size/PII posture on the hash-chained log).
2. **Pin auto-detect + compat fallback** (session.py `resume`) — the
   `PackPinError` retry that falls back from composite to single-pack pin:
   can any sequence make a *changed* pack resume without `repin` (silent
   drift), or mask which pin actually validated? Interaction of
   `multi_pack=None` auto-detection with explicit `pack_path`.
3. **Export refusal path** (export.py `build_matrix_rows`) — interplay with
   roll-up rows, TBD rows carrying stale comments, units elected under
   `enforce_decision=False`, and the golden/CLI paths: can a blocked label
   still reach CSV/DOCX/XLSX via any writer, or does refusal on one row
   block the whole export (DoS-by-one-bad-row is also worth judging)?
4. **Graph-driven class gating** (decision.py) — the hardcoded AC-5 unit set
   was replaced by `fact_key == "classification.primary"` edges. Did any
   unit fall out of coverage relative to the seeds (e.g. AMR-11 has
   unit→unit edges but check its fact-edge)? Can a curated pack with no
   fact edges silently lose all class gating?
5. **§13.2 gate at set_axes** — the walk's accept/edit comment flow now
   stores comments through the gated path: can a refusal mid-interview crash
   or wedge the walk loop? Is the generated-comment soften step
   (`complete`→`finish`) still coherent with the hard gate?
6. **`record_review_decision`** — actor on the event is the reviewer string,
   uncorrelated with any assignment; `review_state` transitions have no
   legality check (e.g. `accepted` → `proposed` regression via a later
   event).
7. **Evidence date handling** (evidence.py) — fail-closed parsing landed;
   probe boundary formats (timezone suffixes, `YYYY-MM`, empty string) and
   the `as_of` path.

## Constraints

- No source changes; branch must stay clean at `2ab4e81`.
- Probes in temp dirs (pattern: Beth's scratchpad probes; golden runs fine
  against `tmp` session dirs).
- `docs/slices/RDW_REVIEW_BUNDLE_2bc0276.md` and this file are the only
  untracked files — leave them alone or reference them, don't rewrite.
- Protected files per `.oracle_protected` remain untouchable.

## Context documents

- Merged findings + fix verification:
  `docs/slices/RDW_REVIEW_BUNDLE_2bc0276.md`
- Build spec: `docs/slices/RDW_MVP_BUILD_SPEC.md`; product spec
  `docs/RDW_SPEC.md`; engine contract `docs/ORACLE_DISPOSITION_SPEC.md`
  (v0.5.0, protected); governance `docs/ERRATA_RFC_001_AXIS_MODEL.md`
  (box 3 open — merge posture gated on it; the build itself is sanctioned
  under box 2's deferral).

Report format: findings ranked by severity with file:line and a reproducible
probe per finding, same as your `2bc0276` review. If the diff is clean, say
so plainly — "no new findings" is a valid and useful result.

*Advisory-only per D-1.*
