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

---

## Fran's product review — `983ff9d` (2026-07-30) + Beth verification

Fran's verdict: **excellent foundation, not remotely done** — the branch
built the compliance-decision *chassis* (hash-pinned engine, axes with
derived views, curated pack, raw answers, structured actions: all real),
not the *product* (the AMR-by-AMR expert conversation, requirement-specific
closure planning, the working-guide deliverables, the 115-row corpus).
Beth concurs and retracts the earlier "we already built most of it"
framing — that was true of the chassis, not the product.

**All findings probe-verified by Beth on `983ff9d`:**

- **AF1 + AF2 CONFIRMED FIXED** (hyphen tokens and rationale leaks gone
  from the curated pack; ownerless action now → TBD Verify).
- **FR-CEO (critical):** intake asks "Confirm customer is assumed CEO?" —
  "y" changes nothing; "n" sets `confirmed=True, assumed_ceo=False`
  WITHOUT asking who the CEO is; no `ceo.identity` fact; intake completes.
  Broken for the founding engagement; AMR-2/AMR-4 hinge on CEO identity.
- **FR-NA-TRAP (critical):** the walk cannot complete an N/A — answering
  "no" elects `applicability=no` with no scope-citation prompt, the C1
  gate refuses, and the walk re-prompts the same question (3 refusals
  observed). Same class of gap for Meet evidence, MI intent/alternative,
  EX basis/closure, NMWP action fields, NYD trigger: the gates demand
  fields the interview never gathers.
- **AF3 still open** (advisor LOW over-broad; AMR-14 proposal unreachable
  in seeded sessions).
- **FR-LIVE:** `LiveAdvisor` only `explain()`s; propose/suggest fall back
  to deterministic templates ("Close gap for AMR-X").
- **INTEG-1 (Fran, confirmed):** LiveAdvisor swaps `model_id` AFTER
  `output_hash` is computed — stored hash does not represent stored
  output (probe: stored ≠ recomputed).
- **INTEG-2 (Fran, confirmed):** library export blocklist scans facts
  only — a disposition comment containing "Boeing" + a contract number
  exported cleanly (probe-confirmed).
- **FR-EXPORTS:** Appendix-A is a CSV skeleton truncating requirement
  text at `[:120]`; roadmap lacks the working-guide fields (what it
  requires / why / process interpretation / matrix comment / current
  evidence / controlled destination / objective evidence / done-when /
  related AMRs / gate-hold).
- **FR-LEARN:** import ingests facts + paired answers only — dispositions
  and action patterns are exported but never reused.
- **FR-FALLBACK (Fran rec 7):** loader silently falls back to the
  known-corrupt builtin when the curated pack is absent — should fail
  closed.

Handoff for the next round: `docs/slices/RDW_FIX3_HANDOFF.md`. The
binding blocker for the round after it is the **scrubbed 115-AMR corpus +
16 work packages** from the operator's engagement records — per Fran:
"the next move is not another roadmap — it is loading our real corpus and
making it pass end to end."

---

## Fix round 3 — BUILT BY BETH (uncommitted on `983ff9d`, 2026-07-30)

**Role flip: Beth built this round at the operator's request, so Beth
cannot gate it — Atlas and/or Fran must review the diff.** Scope: FR1–FR8
of `RDW_FIX3_HANDOFF.md`, all implemented; suites 577 passed / 5 skipped
(the 5th skip is the corpus golden skipping-with-reason, by design).

- FR1: intake records `ceo.identity` as an assumption on "y", asks WHO on
  "n" and records a confirmed identity + CEO org; graph fact edges
  ceo.identity → AMR-2/AMR-4.
- FR2 (AF3): LOW decided from unit-relevant input-gap facts
  (classification/ceo via graph edges) — AMR-14's Open/Not Met proposal
  now fires in a seeded session (test-pinned).
- FR3: interview completes all six dispositions — N/A citation prompt,
  Meet evidence citation (+registry registration when present), MI
  intent/alternative/class prompts + new election gate, EX basis+closure
  (action mini-form or relief), Open/Not-Met plan offer, Not-Yet-Due
  justification. Root cause found during build: units without a
  machine-extracted actor candidate never got an actor/ownership question,
  so org_responsibility stayed TBD forever — the question engine now asks
  regardless, and applicability=No is terminal (no moot questions).
- FR4: LiveAdvisor propose/suggest are real structured-JSON calls with
  schema validation, blocked-label stripping, §13.2+grader scrub, and
  deterministic fallback recorded as such; INTEG-1 fixed via
  finalize-hash-last (round-trip tested incl. fallback); default model id
  current-generation.
- FR5 (INTEG-2): blocklist scans every exported string (facts, paired
  answers, comments, citations, EX/MI fields, action fields) naming the
  offending field; import applies paired answers through the shared gated
  path and lands dispositions/actions as event-logged SUGGESTIONS the walk
  offers with provenance (normal election + attestation to apply).
- FR6: Appendix-A as a real XLSX worksheet (full verbatim text, numeric
  document order, Meta sheet) + CSV untruncated; new
  `implementation_guide.md` with the ten working-guide fields per non-Met
  AMR, explicit "— (not yet established)" gaps, never invented content.
- FR7: `load_rdw_default_packs` fails closed when the curated pack is
  missing; `allow_builtin=True` is the only escape and logs the corruption.
- FR8: `corpus.py` — CSV corpus format, loader, and EXACT dual-view
  reconciliation (85/6/7/17 and 2/39/34/18/21/1 + 16 work packages);
  golden test skips with reason until `RDW_CORPUS_PATH` points at the
  scrubbed corpus.

End-to-end smoke verified: seeded session → advisor proposes Open/Not Met
on AMR-14 → attested election → suggested EFCP action recorded
(plan-quality) → readiness Not Met with Plan → comment → seven export
products including the Appendix-A XLSX and a populated guide section.

*Prepared by Beth from Atlas's and Fran's reviews of 2026-07-30 and
Beth's probe-verified reviews of `ea6cd88`, `2bc0276`, `2ab4e81`, fix
round 2, the assistant slice, and `983ff9d`; fix round 3 built by Beth
and pending independent review. Advisory-only per D-1.*

---

## Atlas review of fix round 3 (2026-07-31) — 13 findings, ALL FIXED by Beth

Atlas reviewed the uncommitted fix-round-3 diff on `983ff9d` and found
2 critical / 4 high / 7 medium (independent suite 575/7 at review time).
Beth (builder this round) fixed all 13; every finding has a pinned
regression in `tests/disposition/test_atlas_round3.py` (24 tests).

- **AR1 (critical)** Live advisor could show one label while its axes
  elected another. `derive_label_from_axes` + `verify_proposal_label`
  (advisor.py) now verify agreement after blocked-label stripping; a
  divergent proposal never surfaces — deterministic fallback recorded as
  such. The deterministic EFCP path self-verifies too.
- **AR2 (critical)** Sticky `not_yet_due` could contradict a later Meet.
  `set_axes` now refuses an explicit NYD+concrete-implementation election
  and auto-clears a stale carried marker when implementation leaves TBD.
- **AR3 (high)** Sub-prompts treated EOF-as-"quit" as data (a probe stored
  `scope_citation="quit"`), and none were raw-answer-logged. New `_sub_ask`
  helper: EVERY follow-up prompt (citations, evidence, MI/EX fields, action
  form, NYD justification, intake, advisor/library/comment confirms) is
  raw-logged under a namespaced question key and quit/EOF cancels the
  sub-flow with an explicit TBD fallback. Intake can no longer store
  "quit" as the CEO or classification.
- **AR4 (high)** `open(multi_pack=False)` loaded the corrupt builtin with
  no flag. `allow_builtin` is now plumbed through
  `_load_records/open/resume` (including the H2 legacy-pin retry) and the
  CLI (`--allow-builtin` on walk/export/audit); default fails closed.
- **AR5 (high)** Paired "no" synthesized a scope citation (laundering).
  `apply_paired_answer` takes `scope_citation`; the walk prompts for a
  real one; without it both paired units land TBD(scope_decision_not_made).
  Library bundles carry `paired_citations` so reuse stays honest.
- **AR6 (high)** Blocklist missed action free-text (due_or_trigger,
  work_package, ids, provenance). Export now full-tree-scans every string
  leaf of the serialized bundle (defense in depth over the per-field pass).
- **AR7 (med)** Suggestions weren't reusable: axes now export
  `obligated_actor`; a gate-refused suggestion seeds its ungated axes and
  hands the rest to the interview; imported action patterns are offered
  as prefilled plans at the Open/Not-Met step (previously unconsumed).
- **AR8 (med)** Unresolved prerequisite facts (ceo.identity) blocked N/A
  even with a valid citation. decision.py blocks N/A only when no scope
  rationale exists; Meet stays blocked.
- **AR9 (med)** Invalid MI control class silently became "integral"; now
  re-prompts until valid (blank takes the announced default).
- **AR10 (med)** Paired answer was recorded before elections (crash could
  suppress the question with no effects applied). Elections run first;
  the record event is provably last in the event log.
- **AR11 (med)** Corpus accepted structurally meaningless data and no
  XLSX. Loader now enforces unique requirement_ids, canonical
  contract/readiness label vocabulary (full forms normalized), axis-value
  vocabulary, and reads .xlsx directly (stdlib OOXML reader).
- **AR12 (med)** Appendix A included 8 EFCR rows; both CSV and XLSX are
  now AMR-only (EFCR stays in internal products).
- **AR13 (med)** Guide listed unregistered refs as "objective evidence"
  and comments as "process interpretation". Objective evidence now shows
  registry-verified refs only (explicit unverified note without a
  registry); interpretation comes from intent_statement or an explicit gap.

Suites after fixes: **601 passed / 5 skipped** (577 + 24 AR regressions).
End-to-end smoke re-verified (advisor proposal → election → plan →
comment → seven export products). Built and fixed by Beth — Atlas/Fran
re-review still gates the commit. Advisory-only per D-1.

---

## Atlas re-review (2026-07-31) — 12/13 confirmed, AR11 partial, 10 new findings; ALL FIXED by Beth

Atlas independently confirmed AR1-AR10, AR12, AR13 fixed (his own probes),
graded AR11 PARTIAL, and found 1 critical / 2 high / 6 medium / 1 low in
the fix code itself (independent suite 599/7, inventory matching). Beth
fixed all ten + completed AR11 the same day; regressions in
`tests/disposition/test_atlas_round3b.py` (16 tests).

- **N1 (critical)** AR8 over-generalized: class-gated AMR-17 could elect
  AND export N/A on a bare operator assertion. decision.py now blocks N/A
  unconditionally when the unresolved prerequisite is
  `classification.primary` (classification determines applicability — no
  citation substitutes); other facts (ceo.identity) keep the AR8 behavior.
  Re-probed: refused at election and at export.
- **N2 (high)** The AR7 partial seed set applicability="yes", which
  skipped the classification question (it only fires while applicability
  is TBD). Partial seed now seeds actor/org only.
- **N3 (high)** CLI export validated the session's (builtin) pin then
  rendered from the curated default set — source-provenance mismatch in a
  deliverable. Sessions now retain `loaded_records` (the exact pinned
  set); CLI export/audit and the walk render from those, never re-loading
  defaults. Re-probed: builtin session renders builtin text/locators.
- **N4 (med)** Legacy sessions with a pre-fix prohibited comment wedged
  every axis update and crashed the walk quit path. §13.2 now refuses
  only the comment being SET in the call (carried violations warn until
  repaired); walk quit/skip teardown is exception-safe.
- **N5 (med)** Paired elections were separately-persisted events — a
  crash between them left the pair divergent. New `EventLog.append_many`
  writes the whole batch in one atomic temp+rename;
  `apply_paired_answer` validates all elections (deferred), then persists
  elections + the paired record as ONE batch. AR10 ordering preserved.
- **N6 (med)** Multi-sheet XLSX corpus silently read the numerically
  first sheet. The reader now selects by NAME: a sheet named "Corpus"
  wins, a single sheet is unambiguous, anything else refuses.
- **N7 (med)** Whitespace drift in EvidenceRef demoted registered
  evidence (blocked Meet, gap-marked the guide). doc_id/revision are now
  stripped at model validation; case left alone (may be significant).
- **N8 (med)** `library export/import` CLI lacked the `--allow-builtin`
  escape walk/export/audit had. Added.
- **N9 (med)** Paired-library metadata now self-describing: sessions
  record which units each paired answer applied to (`paired_units`,
  replay-safe with legacy default), bundles carry `paired_units` +
  `paired_citations`, import applies to the bundled pair. Schema bumped
  to `rdw-library/v2`; reader accepts v1+v2 and refuses unknown versions
  with a version message.
- **N10 (low)** Malformed worksheet XML inside a valid zip now fails as
  CorpusError, not a raw ElementTree exception.
- **AR11 completed**: `assert_reconciled` enforces a coherence floor —
  every row carries all four axes, and label/axis invariants hold
  (NA→applicability no, MI→alternate_proposed, Met→meets_as_written,
  Not Yet Due→implementation tbd, Technical N/A→applicability no,
  NMWP→has a plan action). Deliberately NO CW/EX→applicability rule:
  Fran's real targets (21 Technical N/A vs 17 contract NA) mean some
  technically-N/A rows answer CW — that rule would reject the real
  corpus. Atlas's blank-axes probe now refuses.

Suites after fixes: **617 passed / 5 skipped** (601 + 16 N regressions).
Atlas's N1/N3 probes re-run: both refuse/render correctly. Built and
fixed by Beth — independent re-verification still gates the commit.
Advisory-only per D-1.

---

## Gate CLEARED (2026-07-31) — Atlas round 3: all N1-N10 + AR11 completion CONFIRMED-FIXED, no new findings

Atlas independently confirmed every fix with his own probes: N1 refused at
election AND export; N2 seeded actor/org only with classification question
firing; N3 builtin pin rendered builtin locators consistently; N4 no wedge
or crash; N5 simulated rename failure persisted ZERO batch events (true
atomicity) and the success path chained election, election, paired_answer
with a valid hash chain; N6 named-sheet selection + ambiguity refusal; N7
whitespace normalization qualified Meet; N8 library CLI escapes exit=0;
N9 custom-pair round-trip + v1 accepted + v99 refused; N10 CorpusError
boundary; AR11 blank-axis corpus refused immediately. Independent suite:
**615 passed / 7 skipped** (622-test inventory matching Beth's 617+5; two
extra environment-conditional skips). No repository changes by reviewer.

Operator authorized commit+push (Dr. Wilde, 2026-07-31). This closes fix
round 3: FR1-FR8 build + AR1-AR13 + N1-N10, all independently gated.
Advisory-only per D-1.
