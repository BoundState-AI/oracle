# PASTE THIS INTO CLAUDE CODE

Build Phase 1 of HEARTH per the attached spec `HEARTH_spec_v0.3.md`. Section 12 is the
authoritative scope for this session — read it first, then Sections 1, 2, 3.3, 6, 8, 11
for context. Build ONLY the four Phase-1 deliverables (P1-A repo+models, P1-B scrubber
CLI findings-only, P1-C CO-Larimer pack skeleton, P1-D boundary-test scaffold).

Ground rules:
1. Work the deliverables in order. Each must pass its ACCEPT criteria (pytest) before
   you start the next. Show me the test run at each gate.
2. The scrubber FAILS CLOSED. An unparseable document is a `refuse` finding with exit
   code 2 — never an empty success. Write the test for this before the feature.
3. The Grey Rock BDB24-6-24 document is unit-test fixture #1. I will place it at
   tests/fixtures/ — if it is missing, create a faithful text fixture from the clause
   content described in spec Section 2.5 and mark it SYNTHETIC in the filename.
4. No scope creep: no valuation engine, no MLS/portal adapters, no LLM calls (the
   ClauseAnalyzer is a stubbed protocol), no UI. If you believe something out of scope
   is necessary, STOP and write the reasoning in BUILD_NOTES.md instead of building it.
5. Every module gets the BoundState header (boundstate-architecture skill format) with
   the `Financially Critical` field. Financially-critical modules use the
   never-suppress-error pattern.
6. Commits: small, message cites the spec section implemented.
7. When all four gates are green: write BUILD_NOTES.md summarizing what exists, what is
   stubbed, every deviation from spec, and your top 3 recommended next steps for Phase 2
   — then stop. Do not begin Phase 2.

Definition of done: `pytest` fully green including the Grey Rock golden-file test
(fee/warn + scope/flag + backstop/flag with exposure_usd=21000 + default_trap/flag),
the provisional-banner render test, and the boundary canary test; `hearth scrub --help`
works; README quickstart lets me scrub a document in two commands.
