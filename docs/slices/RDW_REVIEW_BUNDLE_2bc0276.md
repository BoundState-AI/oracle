# RDW Review Bundle — `2bc0276` (phases 0–5) + `ea6cd88` (MVP spine)

**Reviewers:** Atlas (adversarial execution review) + Beth (spec-conformance
review with live probes). Findings merged, deduplicated, ranked.
**Verdict (joint): changes required.** The build is a genuine vertical
prototype — decision engine, dependency graph, evidence service, review
objects, audit lineage, multi-pack load, stdlib XLSX all exist and the golden
session reproduces its claimed labels. It is not "Phases 0–5 complete": the
recurring defect, in both reviews independently, is that **guards are
computed and then not enforced** on the path that actually produces customer
artifacts.

**Verification status:** every finding below marked *verified* was confirmed
by execution (Atlas's adversarial run and/or Beth's temp-dir probes). Beth
did not independently rerun the test suites (operator paused suite runs
during the Grok build); Atlas confirmed the 107-test disposition suite green
and got 88 passes into the full suite before his environment interrupted —
the reported 524 full-suite result is unconfirmed by either reviewer.

This review is the gate contemplated by ERRATA_RFC_001 box 2 ("Atlas + Beth
still review the built diff at the gate").

---

## Critical

### C1. Guards bypass on the product path (enforcement gap) — [Both, verified]

`evaluate_unit` (decision.py) computes §10.1 blocks; nothing consumes them:
`set_axes` accepts any election, `walk.py` never calls the decision engine,
and export maps axes → label directly without consulting `DispositionUnit`,
the coherence gates, or the release gate. `UnitAxesState` (the model the
product actually persists) omits `scope_citation`, workflow/Review state,
acceptance records, boundary confirmation, and qualifying evidence — so the
canonical model's validators (models.py:517ff) can never fire.

Adversarial results (Atlas), reproduced independently (Beth):

```
decision blocks Meet on AMR-2 ("no approved AMCP present") → set_axes elects Meet anyway → exports Meet
UNSUPPORTED_NA allowed=True → exports N/A with no scope rationale field anywhere on the row
comment="The supplier is compliant and complete." → exported (edited comments skip §13.2)
Meet with zero evidence → soft block only (decision.py:144-149 "gate flags for release")
```

Violates FR-009, AC-4, engine rule that absent evidence maps to OPEN, and
§13.2. Fix: elections must refuse labels the decision engine blocks; evidence
gate hard when applicability=yes; §13.2 checks on *stored* comment text, not
just generated text. Structural fix (own slice): unify `UnitAxesState` with
`DispositionUnit` so there is one guarded model.

### C2. §7.1 truth table leaks compliance on rejected/partial — [Beth, verified]

export_map.py:175-188:

| Axes | Exports as | Problem |
|---|---|---|
| alternate_proposed + approval **rejected** | Meets Intent | customer rejected the tailoring; label claims it anyway |
| partial + approval **rejected** | Meets Intent | same |
| not_met + approval **rejected** | Exception | rejected relief still shown as live exception |
| **partial** + approval approved | Meets Intent | no alternative proposed; §13.2 prohibits MI when implementation absent |

Only the Meet path degrades correctly on rejection. ERRATA_RFC_001's deferred
review question 2 predicted exactly this ("Where does `partial` map, and does
it leak compliance?"). Consequence in the golden: **AMR-1** (`not_met +
required`, approval externally owned) exports as **Exception** although no
relief was requested — contradicts AC-3, and the golden test enshrines the
wrong label as expected output. Needs domain ruling (below).

### C3. Review controls spoofable and non-governing — [Both, verified]

- Any caller claiming `disposition_author` accepts unassigned units
  (review.py:117 exempts the role from the assignment check). [Both]
- Assignment check matches reviewer *name* only — an assigned technical
  reviewer can record a decision as quality reviewer (review.py:113-120). [Atlas]
- `ReviewPackage` holds unit ids only — never sees axes, so
  `gate_review_coherence` (accepted requires non-TBD axes or explicit
  accepted-with-TBD election) still has zero callers; a unit with all axes
  TBD accepts cleanly. [Beth]
- The package is mutable JSON via save/load, outside the hash-chained event
  log (§16 requires reviews on the immutable log), and neither session nor
  export consumes its decisions. [Both]

---

## High

### H1. Re-review is volatile; inferred facts propagate as committed — [Both, verified]

`propagation_rereview` events are appended but `_replay_into` has no handler
and `resume()` re-inits `_needs_rereview` empty (session.py:474, 477ff):
eight flagged classification units → zero after restart. `clear_rereview()`
is unlogged. Additionally `assert_fact` sets `confirmed=(not assumed)` — a
`kind="inferred"` fact auto-confirms and propagates with no recorded human
acceptance, and no before/after diff is retained for the §10.2 re-election.
[inferred-fact + diff findings: Atlas]

### H2. Levy pin mishandled in both directions — [Both, verified]

- CLI `disposition export` and `disposition audit` resume with `repin=True`
  (cli.py:3577, 3591): a changed pack silently rewrites the session header —
  even from the nominally read-only audit command. Contradicts the immutable
  levy rule (drift = new run, never substitution). [Atlas]
- Any session opened with an explicit `pack_path` (or any pre-2bc0276
  session) fails `PackPinError` on default resume because `multi_pack=True`
  now composes a composite pin. [Beth]

### H3. Reviewed packs mutable before promotion; revision impact too narrow — [Atlas, verified against code by Beth]

`promote_to` checks meta status only — draft content edited after
`mark_reviewed()` promotes without hash recompute (packs.py:139-154).
`pack_revision_diff` compares only `shall_text` + section; page, actors,
triggers, provenance don't enter `reevaluate`, and removed ids are reported
but excluded from `reevaluate` (packs.py:157-183).

### H4. The interview silently omits NASA-STD-6033 — [Atlas, verified against code by Beth]

Sessions seed 6030+6033 (123 units) but `run_walk` reloads only the builtin
6030 pack (walk.py:465) — EFCR units are never interviewed and their exported
rows lack source metadata. The 6033 seed carries 8 of the specified 31 EFCRs.
Phase 0 exit ("all AMRs/EFCRs reviewed against source") not met.

### H5. Evidence service exists but is unwired and fails open — [Both, verified]

- `is_expired` swallows `ValueError` → `expiration_date="not-a-date"` passes
  the Meet evidence gate (evidence.py:69-77). [Atlas]
- `known_artifact_ids` (phantom-ref refusal, case 23) is never supplied by
  golden/CLI export even though `EvidenceStore.known_doc_ids()` exists to
  feed it — one-line fix. [Beth]
- CLI audit never passes an `EvidenceStore` or `ReviewPackage` into
  `build_lineage`. [Atlas]
- XLSX has Matrix/Assumptions/TBD/OpenActions/Meta but no evidence register
  or Appendix-style matrix (FR-015). [Atlas]

---

## Medium

- **M1** `DispositionSession.open()` self-deadlocks ~30 s when the session
  exists (nested non-reentrant lock via `resume()`), session.py:312-323. [Beth, verified]
- **M2** Walk crashes with `ValidationError` on unrecognized free-text
  answers (walk.py:343-365) instead of re-prompting. [Beth, verified]
- **M3** Export-event replay shape mismatch: live appends `meta`, replay
  appends the whole payload with `_schema`/`event_type` keys — "reload =
  replay" false for `state.exports`. [Beth, verified]
- **M4** 26-case regression corpus not exercised behaviorally: harness checks
  counts/pointers/mappability, never runs the decision engine against the
  cases; 7 cases excluded. Can regress expert-corrected outcomes while
  green. [Atlas]
- **M5** Test quality: phase-1 AMCP assertion near-vacuous
  (`"MEET" in str(d.blocked).upper()`); `date.today()` in evidence gates
  (date-boundary flake). [Beth]
- **M6** decision.py hardcodes the AC-5 unit set, duplicating what the graph
  encodes. [Beth]

---

## Governance

ERRATA_RFC_001 §6: box 2's deferral **authorizes this build** ("build
proceeds on the v0.2 draft… risk accepted; Atlas + Beth still review the
built diff at the gate" — this bundle is that gate). But box 3 (engine spec
v0.6.0 stamp, slice re-plan, S1R activation) is open, and the closing line
keeps v0.5.0 binding until all three boxes complete. Practical reading: the
build itself is sanctioned; **merging it as "the axis model, consumed"
is not** until box 3 closes. [Atlas raised; Beth qualified]

---

## Domain rulings needed (Dr. Wilde)

1. **AMR-1 export label** — Exception is wrong per AC-3. Open/Not Met, or a
   new axis distinction between "relief requested" and "approval externally
   pending"?
2. **Truth-table targets** for the four C2 cells (recommended: all four →
   Open/Not Met).
3. **The 7 AMBIG fixture cases** (1, 4, 5, 8, 16, 17, 21) still need
   per-case disposition (errata box 1 note).
4. **6033 scope** — curate the full 31 EFCRs now, or descope Phase 0 exit?
5. **Box 3 timing** — stamp v0.6.0 after this fix round, or later?

## Bundled fix order

1. **Enforcement wiring** (C1): elections refuse decision-engine blocks;
   hard evidence gate; §13.2 on stored comments.
2. **Truth table + golden** (C2): four cells per ruling 2; AMR-1 per ruling 1.
3. **Re-review durability + fact provenance** (H1): replay handler,
   `rereview_cleared` event, inferred-fact confirmation requires human
   acceptance, retain before/after diff.
4. **Review binding** (C3): role checked against assignment; no author
   exemption; decisions onto the event log; review-coherence gate at
   `decide()`; export consumes review state.
5. **Pin lifecycle** (H2): CLI `repin=False` default, audit strictly
   read-only; resume compat for single-pack pins.
6. **Pack governance** (H3): hash recompute at promote; widen revision diff;
   removed → reevaluate.
7. **6033 in the walk** (H4) per ruling 4.
8. **Evidence wiring** (H5): fail-closed dates, arm `known_artifact_ids`,
   audit CLI wiring, registers in XLSX.
9. **Robustness** (M1–M3) and **test hardening** (M4–M5).
10. **Model unification** (C1 structural): own slice — single guarded
    disposition model; everything above gets simpler after it.

---

## Fix verification — `2ab4e81` (Beth, 2026-07-30)

All claimed fixes re-probed adversarially by execution. **Results: C1, C2,
C3, H1, H2, H3, H4, H5, M1, M2, M3, M6 verified fixed.**

- **C2**: all four leaking cells → Open/Not Met; `not_met + required +
  external org` → Open/Not Met (AMR-1 per AC-3); live relief path (owner)
  still maps Exception; Meet paths unregressed. Golden now reports
  AMR-1 = Open/Not Met.
- **C1**: AMR-2 Meet refused (AMCP + evidence blocks both enforced); Meet
  without evidence refused hard; Meet **with** evidence elects (no
  over-block); N/A without `scope_citation` refused, with citation elects;
  §13.2 refuses prohibited language on *stored* comments. The
  `election=False` bypass is caught at export: `build_matrix_rows` refuses
  blocked labels.
- **H1**: 8 re-review flags survive resume (event replay); before/after
  diffs retained; `clear_rereview` logged and durable; inferred facts
  refuse auto-confirmation.
- **C3**: unassigned author refused; role spoof refused; TBD-accept with
  session refused via review-coherence check.
- **H2/M1**: `open()` on existing session 0.01 s (was 30 s deadlock);
  single-pack sessions resume; CLI audit/export no longer silently repin.
- **H3/H5**: post-review draft tampering refuses promotion; removed ids and
  page changes enter `reevaluate`; unparseable expiration dates fail
  closed with a named reason; `known_artifact_ids` armed from EvidenceStore.

Residuals (non-blocking, carry to next slice):

1. `ReviewPackage.decide()` **without** a `session`/`unit` argument still
   accepts blind — the standalone-JSON package path skips the coherence
   check. Closes naturally with model unification; until then callers must
   pass `session=`.
2. `set_axes(enforce_decision=False)` is an opt-out any caller may pass
   (used legitimately for skip/quit → TBD). Export re-checking makes this
   defense-in-depth rather than a hole.
3. walk.py answer-handler catches `Exception` in its retry tuple —
   repo standard violation (no bare/broad except), minor.

Intentionally open, as agreed: model unification slice; domain rulings on
the 7 AMBIG cases; 31-EFCR curation vs 8-seed; ERRATA box 3 (v0.6.0 stamp);
M4 behavioral 26-case harness (partial). Suite counts (111 disposition /
528 full) are Grok's; Beth's environment (VSCode extension) auto-rejected
pytest invocations this round, so independent confirmation is pending an
operator-run result.

---

## Atlas round 2 — new holes in `2ab4e81` (2026-07-30) + triage

Atlas found eight new defects (probe-verified, bundled findings excluded).
Triaged by Beth under the **product-direction ruling by Dr. Wilde
(2026-07-30): the assistant is the core** — integrity guards stay, and the
next slice after fixes is the assistant layer (explain / suggest-closure /
learn). **Board ruling (Dr. Wilde, 2026-07-30): single-user tool, no
multi-user — the six-role review board is subtracted to single-operator
attestation (role recorded, not enforced); multi-user enforcement parks
until a later phase.** A4/A7 are fixed by that subtraction (handoff F6).

| # | Finding (Atlas) | Sev | Triage |
|---|---|---|---|
| A1 | Prerequisite fact change leaves stale `accepted` Meet exportable (`needs_rereview` never checked at export; review_state untouched) | Critical | **Fix** (F1) |
| A2 | Expired / revision-mismatched evidence satisfies Meet gate (`bool(evidence_refs)`); phantom check ignores revision; `export_all` synthesizes known-set from the refs under validation (tautology) | Critical | **Fix** (F2) |
| A3 | Fact append + propagation event not atomic — crash between them loses re-review on replay | High | **Fix** (F3, deterministic re-propagation at replay) |
| A4 | `record_review_decision()` bypasses assignment/role/transition checks — unassigned auditor accepts; `accepted → proposed` regression | High | **Fix required either way** — mechanism pending board ruling (F6) |
| A5 | Curated packs silently lose classification gating (graph = static AMR seeds; pack loader imports no dependency edges) | High | **Deferred to Phase 4 pack slice** — pack-declared dependencies (§9.1 Logic group) |
| A6 | Whitespace passes as N/A `scope_citation` | High | **Fix** (F4) |
| A7 | Replay drops `accepted_with_tbd` election | Medium | **Fix required either way** — mechanism pending board ruling (F6) |
| A8 | §13.2 refusal on edited comment aborts the whole walk | Medium | **Fix** (F5) |

Suite: Atlas sharded all 532 collected tests → **526 passed, 6 skipped**
(2-skip delta vs Grok's 528/4 is environment-sensitive CLI-presence cases
in `test_pipeline_build.py`/`test_pipeline_review.py`, not regressions).
Monolithic runs are killed by an environmental gremlin in both reviewer
environments; not a test failure.

Fix handoff for Grok: `docs/slices/RDW_FIX2_HANDOFF.md`.

---

## Fix round 2 verification — working tree on `2ab4e81` (Beth, 2026-07-30)

All Atlas round-2 probes re-run against Grok's uncommitted F1–F6 diff.
**F1, F3, F4, F5, F6 verified fixed. F2 verified with one residual gap.**

- **F1**: accepted AMR-17 → `superseded` on classification supersede;
  export refuses re-review units by name, no bypass.
- **F2**: expired + revision-mismatched evidence refuses Meet; qualifying
  registered evidence elects cleanly; phantom check on `(doc_id, revision)`;
  `export_all` with no registry stamps "phantom-ref check: skipped (no
  evidence registry)" into Meta. **Gap:** the walk still calls
  `export_csv`/`export_docx` directly (walk.py:568-570), so a walk-produced
  export with no registry silently skips the phantom check with no stamp —
  the exact silent skip F2 forbade, surviving on one path. Fix: walk calls
  `export_all` (two-line change).
- **F3**: simulated crash between fact append and propagation event →
  resume still recovers all 8 re-review units (replay recomputes).
- **F4**: whitespace `scope_citation` refused at validation.
- **F5**: prohibited edited comment re-prompts; walk survives and
  continues.
- **F6**: all-TBD accept without election refused; `accepted_with_tbd`
  election works and **round-trips replay** together with `review_state`;
  `accepted → proposed` regression refused ("illegal review transition").
- Golden regression: labels unchanged (AMR-1 Open/Not Met, AMR-14
  Open/Not Met, AMR-17 TBD), 8 re-review units.
- Suites: **independently confirmed** — operator ran disposition
  (120 passed); Beth ran the full suite twice monolithically
  (**537 passed, 4 skipped**) after the fixes below.

### Post-verification fixes applied by Beth (2026-07-30)

1. **The "environment gremlin" was a repo bug — found and fixed.**
   `store.py _pid_alive()` used `os.kill(pid, 0)` as a liveness probe; on
   Windows signal 0 is `CTRL_C_EVENT`, so probing a *live* pid sent Ctrl+C
   to the console process group. S1a lock-contention tests probe live pids
   (including pytest's own), so monolithic suite runs died
   nondeterministically in every environment (Atlas exit 137, operator's
   silent terminal deaths, Beth's harness interrupts). Also a real product
   bug: a stale lock with a reused pid would Ctrl+C the user's terminal.
   Fixed with a true probe (`OpenProcess` + `GetExitCodeProcess` via
   ctypes). Monolithic runs now complete.
2. **F2 residual closed:** walk export routed through `export_all`
   (walk.py) — registry resolved, missing registry stamped into Meta,
   XLSX now included in walk exports. Probe-verified.

**Round is commit-ready:** Grok's F1–F6 + the two fixes above; full suite
green (537/4) with all of it in the tree.

### Pack-integrity finding (via Fran's tailor-helper review, verified 2026-07-30)

`oracle/builtin_packs/nasa_std_6030_rulepack.json` is **not authoritative**:
77/115 `shall_text`s end with a dangling `[`, AMR-2 terminates mid-sentence,
~80 suspicious endings total (probe-verified on this branch). Everything
downstream that presents "verbatim" text (walk, exports, future assistant
explanations) is presenting corrupted extractions. Phase 0 re-curation from
the source PDF with human review (FR-003) is a prerequisite for the
assistant slice. The pack is protected from builds — re-extraction is a
deliberate curation task, not a build task.

---

## Assistant-slice review — uncommitted build on `6ddf073` (Beth, 2026-07-30)

**Verified by execution:** Stage 0 pack (115 complete, zero dangling `[`,
AMR-2 whole, pages + rationale, source_hash matches the pinned PDF, loader
prefers curated, builtin untouched); Stage A (EX closure gate refuses
without basis and elects with basis+closure; `not_yet_due` requires
justification and maps to Not Yet Due; raw answers and ActionRecords
replay including supersession); Stage B (LOW proposes nothing; blocked
labels never proposed; context/output hashes present; rationale-grounded
explain; §13.2 + grader scrub refusals); Stage D (blocklist export
refusal; imports land as unconfirmed assumptions); Stage E (supplier
suite + `appendix_a_matrix.csv` + `readiness_roadmap.md`, banner, stamps,
computed counts, phantom-skip note); Stage C (`walk --advisor` survives a
scripted interview, verbatim-first, labeled interpretation, band +
readiness shown). Full suite **553 passed / 4 skipped independently
confirmed** (monolithic).

**Findings (fix round requested before commit):**

1. **AF1 (medium-high) — curated-pack fidelity: cross-line dehyphenation.**
   Sentence-level sweep vs the PDF: 11 records deviate — compound terms
   lost internal hyphens at line breaks: `NASASTD-5019` (amr-15),
   `NASA-STD5009` (amr-20), `insitu` (amr-21), `postbuild` (amr-30),
   `postAM` (amr-70), plus join artifacts in amr-10/12/13/24/65/80.
   And **amr-9 + amr-13 embed the `[Rationale:` block inside
   `shall_text`** (field-separation violation). Repair the 11 + de-dup
   the 2, add the sentence-sweep as a Stage 0 test, then operator review.
2. **AF2 (medium) — readiness "plan-quality" floor not enforced:** an
   ownerless/exit-less open action still yields Not Met with Plan
   (readiness.py fallback branch). Spec floor: owner + exit_criteria.
   Probe: not_met + ownerless action → "Not Met with Plan" (want TBD
   Verify).
3. **AF3 (medium) — advisor LOW gating over-broad:** any
   assumed-classification fact (which the seed context creates by
   default) marks EVERY unit LOW, making the AMR-14 Open/Not Met proposal
   path unreachable in real sessions. Scope the LOW check to
   unit-relevant facts (graph edges), not a global fact-blob scan.
4. **AF4 (low):** LiveAdvisor default model id is outdated
   (`claude-sonnet-4-20250514`); bump to a current-generation default
   (env override already exists).
5. **AF5 (low, design note):** imported paired answers suppress the
   paired question in a new session without setting axes — no false
   closure (units stay TBD and get individual questions), but the
   ask-once-apply-to-all machinery doesn't fire on import.

*Prepared by Beth from Atlas's reviews of 2026-07-30 and Beth's reviews of
`ea6cd88`, `2bc0276`, `2ab4e81`, fix round 2, and the assistant slice
(probe-verified). Advisory-only per D-1.*
