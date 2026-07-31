# Atlas Handoff — Review of Fix Round 3 (BUILT BY BETH)

**From:** Beth (builder this round — role flip). **Requested by:** Dr.
Wilde, 2026-07-30.
**Under review:** the UNCOMMITTED working tree on `983ff9d`,
branch `build/rdw-mvp-grok` — 8 modified files + `oracle/disposition/
corpus.py`, `tests/disposition/test_fix3.py`, `docs/slices/
RDW_FIX3_HANDOFF.md` (~980 insertions). Review locally in the repo; if
you need a pinned commit instead, tell the operator and Beth will commit
a checkpoint marked pending-review first.

## Why this review is THE gate

Beth wrote this diff, so Beth's own verification is weak evidence — the
builder testing the builder's code. Your adversarial pass is the only
independent gate before commit. Scope: the fix-round-3 diff (spec:
`RDW_FIX3_HANDOFF.md`, FR1–FR8) plus anything it destabilized. Suites at
handoff: 577 passed / 5 skipped (5th = corpus golden skip-with-reason).
Please run the full suite independently.

## Builder's disclosed weak spots — start here

These are the risks I know I carry; I could not attack my own code
honestly, so you should:

1. **FR3 sub-prompt answers are NOT raw-answer-logged.** The main loop
   records every answer via `record_answer`, but the follow-up prompts
   inside `_apply_answer`/`_gather_*` (citations, evidence doc/rev, MI
   fields, EX basis, action mini-form, NYD justification) bypass it —
   Stage A's "every answer verbatim" is weaker than it claims. Judge
   severity; the fix is threading `record_answer` into the gather
   helpers.
2. **`_would_be_label` dry-run vs real election divergence.** The probe
   uses `model_copy(update=...)` while `set_axes` also clears TBD reasons
   when an axis leaves TBD. I believe the mapping is insensitive to this
   (snapshot() only passes reasons for axes still TBD) — try to construct
   a state where the dry label and the elected label differ, which would
   make the walk gather the wrong fields or none.
3. **FR3 flow combinatorics.** Cancel/quit inside sub-prompts (evidence
   'cancel', action-form blank title, EX 'relief' with empty basis),
   EOF mid-form, resume mid-unit, re-prompt loops. Also: quit/skip
   consume `enforce_decision=False` — look for any path that leaves a
   gated label recorded without its fields.
4. **FR4 live-advisor validation is keys-only.** Proposed axis VALUES are
   not vocabulary-checked at parse time (bad values surface later at
   election). Also attack: malformed band strings, scrub-raising inside
   question lists (should fall back, hash still valid), double-fallback
   paths, and hash round-trip on every constructor path I missed.
5. **FR5 synthetic paired citation.** A paired "no" auto-fills
   `scope_citation` = "Paired scope question ... answered 'no' by
   <actor>". Is that a defensible §10.1 positive rationale, or citation
   laundering? Domain judgment — flag if you think it needs the operator
   to supply a real citation instead.
6. **FR5 blocklist coverage.** I scan facts, paired answers, and accepted
   units' comment/citation/EX/MI fields + action fields. Hunt for any
   exported string I missed (e.g. provenance fields, axes values,
   library re-export of imported suggestions).
7. **FR6 guide field sourcing.** "Process interpretation" falls back to
   `intent_statement or comment` — is that mislabeling content? XLSX
   escaping of full shall_texts (quotes/newlines/ampersands in
   `_xlsx_sheet_xml`); open the workbook in a real Excel/LibreOffice if
   you can.
8. **FR7 blast radius.** `load_rdw_default_packs` now raises when the
   curated pack is missing — sweep every caller (session multi-pack
   resume, golden, CLI export/audit/walk) for a context where fail-closed
   bricks a legitimate flow with no escape.
9. **FR8 label vocabulary.** Corpus reconciliation encodes Fran's exact
   phrasing ("TBD", "Program Action") which differs from the readiness
   enum ("TBD Verify", "External Action"). Reconciliation is
   corpus-internal so it works, but the eventual corpus→replay comparison
   will need a mapping — assess whether that should land now.
10. **FR1 intake edge cases.** Repeated intake (idempotency of the CEO
    org append), multiple customer orgs, "n" then blank name, the
    interaction with `ceo.identity` graph edges (AMR-2/AMR-4 Meet AND N/A
    both block while CEO unresolved — too aggressive?).

## Also in scope

New question-engine behavior (actor question without candidates;
applicability=No terminal), MI election gate ripple across older tests,
`apply_paired_answer` on session, `library_imported` event replay,
`finalize_hash` convention, export product set changes
(`appendix_a` now .xlsx; `appendix_a_csv`, `implementation_guide` added).

## Out of scope / known open

The 115-row corpus itself (blocked on operator data); FastAPI shell
stretch; ERRATA box 3; AMBIG fixture cases; model-unification slice.
Gate-record docs are Beth-maintained — reference, don't edit.

## Report format

Findings ranked with file:line + reproducible probe each, plus your
independent suite result. "No new findings" is a valid result but please
say explicitly which of the ten disclosed weak spots you attacked and
what survived.

*Advisory-only per D-1.*
