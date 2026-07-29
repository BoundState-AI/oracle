# Slice S1 — Disposition Data Model + Release State Machine

**Build input for:** `py pipeline/oracle_build.py docs/slices/S1_SPEC.md --repo . --fix-rounds 2 --coverage-floor 80`
**Parent plan:** `docs/DISPOSITION_SLICE_PLAN.md` (S1) — read it first.
**Contract:** `docs/ORACLE_DISPOSITION_SPEC.md` v0.5.0 — the authoritative
source for every schema and rule referenced below. Read §1.1, §1.2, §2,
§2.3, §7, §7.1, §15, §16 before writing code.

## Goal

Create the new subpackage `oracle/disposition/` containing the disposition
module's data model and release state machine — the pure, deterministic
spine everything else builds on. No I/O in domain code; the only file access
in this slice is the test harness's read-only loading of the fixture,
schemas, and static manifests.

## Deliverables

1. **`oracle/disposition/models.py`** — Pydantic v2 models, `extra="forbid"`
   everywhere, per spec §7: the disposition unit (all fields, exact names),
   locator, evidence entry, acceptance record (append-only semantics
   expressed in the model: `immutable: True`, `supersedes` chaining),
   levy manifest, scope declaration (typed: policy /
   physical_impossibility / derived), capability model entry. Every
   record carries `schema_version` and `rule_version`.
2. **`oracle/disposition/codes.py`** — the five disposition codes and the
   §2.3 OPEN sub-reason vocabulary as closed enums. Unknown values must be
   impossible by construction.
3. **`oracle/disposition/state.py`** — the §7.1 workflow_state machine:
   `proposed → human_confirmed → release_approved`, with
   `proposed|human_confirmed → rejected`. Transitions carry actor identity;
   machine actors can set only `proposed`; every other transition requires a
   named human actor. Illegal transitions raise. Pure functions — no
   persistence (that is slice S1a).
4. **`oracle/disposition/rollup.py`** — §1.1 parent roll-up: composition
   vectors, the badge total order (OPEN → EX → MI → MIXED → CW → NA), and
   the rule that a parent is never a disposition target. Exhaustive: every
   possible child-code combination resolves to exactly one badge.
5. **Tests** (`tests/disposition/`):
   - Truth-table test enumerating ALL child-code combinations → exactly one
     badge each (spec §16 names this test explicitly).
   - State-machine tests: every legal transition, every illegal transition
     raises, machine-actor restriction enforced.
   - Schema tests: required-field enforcement per code (e.g. OPEN requires
     exactly one §2.3 sub-reason; NA requires scope_citation; MI/EX require
     intent_statement + alternative_control + control_class).
   - Fixture harness goes live: load
     `tests/disposition/fixtures/oracle_eval_cs6030.json` read-only; assert
     the case count and label breakdown match spec §15's stated numbers;
     assert every `spec_rules` pointer in the fixture resolves to a section
     present in `docs/ORACLE_DISPOSITION_SPEC.md`.

## Module standards

BoundState headers on every module (`Safety Critical:` field reads
"advisory-only per spec D-1"), `LOGGER = logging.getLogger("oracle.disposition.<module>")`,
type hints everywhere, no bare except, no print, functions < 50 lines,
docstrings on public classes/functions. Follow the existing `oracle/`
package style.

## Done when

- Every §7 field is typed and validated; unknown fields rejected.
- Illegal state transitions raise; machine code paths can set only `proposed`.
- The §1.1 truth-table test passes for every child-code combination.
- Fixture harness assertions pass (26 cases; 19/3/2/2 label split; all
  spec_rules pointers resolve).
- Full repo suite green; diff coverage ≥ 80% of added lines.

## Never touch

- `docs/ORACLE_DISPOSITION_SPEC.md` and `docs/oracle_runs/*` — the contract
  and the history.
- `tests/disposition/fixtures/*` — the regression corpus.
- `oracle/oracle2.py`, `oracle/cli.py`, `oracle/chat_engine.py`, and every
  existing `oracle/` module — S1 adds `oracle/disposition/`; it modifies
  nothing that exists.
- `hearth/*`, `pipeline/*`, `.github/*`.

## Stop if

- Implementing any deliverable requires changing a behavioral contract in
  the spec — stop and report; that is an errata RFC per the plan's graded
  errata channel, not a build decision.
- Any deliverable requires I/O in domain code (files, network, environment)
  — the design is wrong or the slice boundary is being crossed; stop and say so.
- More than trivial changes are needed outside `oracle/disposition/` and
  `tests/disposition/`.
