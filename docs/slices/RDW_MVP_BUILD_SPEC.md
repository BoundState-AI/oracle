# RDW MVP — Build Spec (Grok handoff)

**Build:** manual Ben (Grok) build, then gate with:
`py pipeline/oracle_build.py docs/slices/RDW_MVP_BUILD_SPEC.md --repo . --fix-rounds 2 --coverage-floor 80 --check-cmd "py -m pytest tests -q" --skip-build --ben-model <model>`
**Authority:** RDW_SPEC v0.2 (product), ORACLE_DISPOSITION_SPEC v0.5.0
(engine invariants), ERRATA_RFC_001 box-1 approval (axis model approved by
domain authority; targeted pass deferred). Where this spec is silent, those
documents govern — read RDW §7/§7.1/§10/§11/§13 and engine §1.2/§2.1/§7.1
before writing code.
**Base:** branch `build/disposition-s1` (S1 as committed). Harvest patterns
from `feat/tailor-helper` (`oracle/tailor/`) where useful — but the
disposition data model in THIS spec is authoritative; do not merge that
branch.

## Goal

The interactive tailoring walkthrough, CLI-first: ingest the builtin
NASA-STD-6030 pack, walk a user requirement-by-requirement through an
axis-based disposition interview with deterministic guardrails, persist
facts/dispositions append-only, and export the matrix + registers. No LLM
calls anywhere in this build (Stage E hookup comes later under P-2
governance) — everything here is deterministic.

## Stage A — Axis model refactor (`oracle/disposition/`)

Per `docs/slices/S1R_SPEC.md` deliverables 1–6, summarized:

1. `DispositionUnit` v2: six axes — applicability (Yes/No/TBD),
   obligated_actor (program/CEO/producer/supplier/subtier/other),
   organization_responsibility (owner/support/external/TBD),
   implementation_state (meets_as_written/alternate_proposed/partial/
   not_met/TBD), approval_state (not_required/required/draft/submitted/
   approved/rejected/TBD), plus the existing workflow_state machine as the
   Review axis (untouched).
2. The five codes (CW/MI/EX/NA/OPEN) become a computed read-only property
   implementing RDW §7.1, **plus** the customer-label view
   (Meet/Meets Intent/N/A/TBD/Open-Not Met/Exception). Exhaustive truth
   table test: every reachable axis combination → exactly one label or one
   named contradiction.
3. Closed TBD-reason vocabulary: existing sub-reasons + `customer_input_missing`
   (alias of scope_decision_not_made) + `classification_unresolved`. Every
   TBD on any axis carries exactly one reason.
4. RDW §10.3 axis-coherence gates as pure validators (all six), raising on
   construction/transition.
5. All S1 hardening survives verbatim (frozen models, no model_copy bypass,
   evidenced impossibility, acceptance gates, roll-ups non-dispositional;
   roll-up badges roll over export labels with Open/Not Met between EX and
   MI in the precedence order).
6. Fixture harness remap per the **clean rows only** of
   `docs/FIXTURE_AXIS_MIGRATION.md`; the 7 AMBIG cases (1, 4, 5, 8, 16,
   17, 21) are excluded pending domain disposition and the exclusion is
   printed in the harness output. Labels and merge-block semantics
   unchanged.

## Stage B — Requirement records from the builtin pack (`oracle/disposition/rulepack.py`)

1. Adapter: load `oracle/builtin_packs/nasa_std_6030_rulepack.json` into
   requirement records per RDW §9.1 — verbatim `shall_text`, locator
   (standard/revision/section/page), subject as actor-candidate, keywords,
   `applies_to` as trigger-candidates. Records carry the pack id + a
   content hash (levy-manifest-lite pinning: a changed pack file is
   detected and refuses to load over an existing session without an
   explicit `--repin`).
2. Actor/trigger fields are CANDIDATES (machine-extracted, marked so);
   confirming them is interview work, never silent fact.
3. Dependency seeds: a small, human-authored dependency table (Python data,
   not prose) for the known chains — classification (AMR-5/6/8/10/11/12)
   gating class-conditional requirements; AMCP (AMR-2) gating references to
   it; EFCP (AMR-14 → 6033). Extendable structure; do NOT attempt full
   automatic dependency extraction.

## Stage C — Project context + fact ledger + session store (`oracle/disposition/session.py`)

1. Project context per RDW §9.2 (organizations with assumed-CEO flag,
   hardware, classification states, plans present/absent, subtiers,
   capability model per engine §3.1).
2. Fact ledger: asserted/inferred/evidenced facts; author, timestamp,
   source, confidence band (high/medium/low — never a float), supersession
   chain. Assumptions are facts with `assumed=True` and an owner —
   an assumption never silently becomes confirmed.
3. Persistence: append-only JSONL event log per session (hash-chained
   prev-hash field; write-temp-rename; single-writer lock file) — the
   S1a-lite store. Events: fact asserted/superseded, axis set, election,
   evidence ref attached, export produced. Reload = replay. No mutation of
   prior lines, ever.
4. Evidence in v0 is a typed reference record (doc id, revision, date,
   note) — no file storage yet.

## Stage D — Interview CLI (`oracle disposition walk`)

TTY-interactive (fails closed non-TTY, promote-pack posture). Flow:

1. Session open/resume → project-context intake wizard (only unanswered
   fields) → authority-dependent requirements surfaced FIRST (engine §4.2
   report order), then units in pack order.
2. Per unit: verbatim text + locator FIRST, then candidate actor/trigger
   marked as machine-extracted, then dependency state (blocked-by facts),
   then the allowed-states computation with an explicit
   **"why can't this be Meet"** line naming each deterministic blocker.
3. One question at a time: the highest-value unresolved fact for this unit
   (deterministic priority: applicability trigger facts → actor confirmation
   → implementation evidence → approval state). Known context is never
   re-asked (fact ledger lookup); paired questions asked once and applied to
   every paired unit (case 19 machinery).
4. Elections: the user sets axes from the ALLOWED set only; "don't know" /
   skip / quit-mid-unit = TBD with a reason, never silence (engine §2.1).
   Every election is an event with the human actor's name.
5. Comment: v0 generates the RDW §13.1 four-part pattern from template +
   facts (deterministic string assembly, no LLM), runs the §13.2
   prohibited-language checks over it, and stores it as `proposed` — the
   user edits/accepts in-flow.
6. Progress/exit screen: per-axis and per-export-label counts (computed),
   TBD-by-reason table, open actions.

## Stage E — Exports (`oracle/disposition/export.py`)

1. Supplier matrix as CSV (stdlib) + DOCX (python-docx, already a dep):
   unit id, verbatim text ref, axes, export label, comment, evidence refs,
   actions. Assumptions log + open-action register + TBD register as
   sections.
2. Every count computed from the matrix at render (case 22 rule); zero
   placeholder tokens (case 23 rule — refuse to export a row referencing a
   nonexistent artifact); every export stamped with session id, pack hash,
   spec versions.
3. Advisory banner on every artifact (D-1): supports, never substitutes
   for, a qualified human compliance determination. No XLSX in v0 (new dep
   requires justification — CSV imports cleanly).

## Tests (deliverable, not optional)

- Stage A: ported S1 suites + §7.1 truth table + coherence gates + harness
  with reported exclusions.
- Stage B: adapter round-trip on the real 115-AMR pack; hash pinning;
  candidate-marking.
- Stage C: event-log replay equals in-memory state; hash chain detects
  tampering; assumption-never-auto-confirms; supersession.
- Stage D: scripted interview walkthrough (pexpect-style or injected I/O)
  over ≥3 AMRs incl.: skip→TBD-with-reason, blocked-Meet explanation
  present, paired question asked once, authority-first ordering.
- Stage E: export truth (counts computed, banner present, refuse-on-phantom-
  ref), golden export snapshot for the scripted session.

## Standards

As S1: BoundState headers (advisory-only per D-1), `LOGGER`, type hints,
`extra="forbid"`, <50-line functions, no prints in library code (CLI
presentation layer excepted), no bare except, tests keyless-deterministic.

## Never touch

`docs/ORACLE_DISPOSITION_SPEC.md`, `docs/RDW_SPEC.md`,
`docs/ERRATA_RFC_001_AXIS_MODEL.md`, `docs/FIXTURE_AXIS_MIGRATION.md`,
`docs/oracle_runs/*`, `tests/disposition/fixtures/*`,
`oracle/builtin_packs/*`, every existing `oracle/` module outside
`oracle/disposition/`, `oracle/tailor/*` (read-only harvest), `pipeline/*`,
`.github/*`. Files you did not create this build are never yours to delete,
move, or modify.

## Stop if

- An approved fixture translation cannot be expressed on the six axes, or
  the truth table cannot close without a new axis/label → RFC defect: stop
  and report.
- Any deliverable requires an LLM call, a network call, or a new dependency
  beyond stdlib + existing deps → stop and report with justification.
- The interview requires asking a question whose answer the fact ledger
  already holds → the design is wrong; stop and say so.
- More than trivial changes needed outside `oracle/disposition/` +
  `tests/disposition/` (CLI wiring in `oracle/cli.py` is permitted as a
  minimal subcommand registration only).

## Done when

- All stage tests green; full repo suite green; diff coverage ≥ 80% of
  added lines.
- A human can run `oracle disposition walk`, complete intake, disposition
  AMR-1, AMR-14, and AMR-17 against the seed context (RDW Appendix B,
  scrubbed), quit mid-way, resume, finish, and export — with AMR-17
  landing TBD(`classification_unresolved`), AMR-14 landing Open/Not Met,
  and the export containing no claim beyond the entered facts.
- The 7 excluded fixture cases are listed in the test output verbatim.
