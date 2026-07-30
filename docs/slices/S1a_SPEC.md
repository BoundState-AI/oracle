# Slice S1a — Persistence, Concurrency, and Audit Contract

**Build input for:** `py pipeline/oracle_build.py docs/slices/S1a_SPEC.md --repo . --fix-rounds 2 --coverage-floor 80`
**Parent plan:** `docs/DISPOSITION_SLICE_PLAN.md` (S1a, decision P-4) — read it first.
**Contract:** `docs/ORACLE_DISPOSITION_SPEC.md` v0.5.0 — the authoritative source
for every schema and rule referenced below. Read §1.1, §1.2, §7, §7.1, §7.3, §9,
§11, §14, §16 before writing code.
**Predecessor:** S1 (`oracle/disposition/`, commit `7120d44`) — the pure data
model, §7.1 state machine, and roll-up badges. S1a builds on it and **must not
modify `codes.py`, `state.py`, or `rollup.py`.**

## Goal

Give the release state machine a durable, concurrency-safe, tamper-evident home.
This is the slice that makes a human election a *record* rather than a return
value.

**Deliberate divergence from the parent plan:** the plan's S1a section and
decision P-4 say to follow "the HEARTH evidence-store/audit pattern". **Do not.**
`hearth/` is dead code in this repo and is not a reference implementation. The
properties that pattern was cited for are stated directly below; build to those.

S1a also **completes the release path that S1 deliberately left unbuilt** (below).

## Inherited scope decision — read before designing the release gate

S1 refuses `release_approved` outright: `transition_unit` raises
`NotImplementedError` and `DispositionUnit` rejects the state at construction, so
no S1 code path can produce a released unit. That was deliberate, and the reason
is a design constraint on this slice, not just history:

> Release eligibility under §7.1 is **not a unit-local property**. It depends on
> package-level context — the run's effective date against each acceptance
> validity window, approved-scope coverage for the configurations and part
> classes actually being released, acceptance supersession chains, and evidence
> link-confidence thresholds. A gate that checks only what one unit can see is
> not a partial gate; it is a wrong gate, because it returns "release approved"
> on inputs §7.1 forbids. Three review rounds against S1 produced exactly those
> defects: an inverted `supersedes` test, `or` where full scope coverage was
> required, and OPEN units reachable through the gate.

**S1a owns release, and owns it whole.** A release decision here is made against
an explicit, immutable release context, recorded in the event log, and applied
atomically — or it is refused. There is no intermediate posture.

## Deliverables

1. **`oracle/disposition/store.py`** — versioned repository over units, matrix,
   elections, and acceptance records. Append-only JSONL, schema-versioned; every
   record carries `schema_version` and `rule_version`. Read paths are pure; all
   writes go through (2). No record is ever rewritten in place — supersession is
   expressed by appending a successor that links to its predecessor.

2. **`oracle/disposition/eventlog.py`** — append-only, **hash-chained**
   transition/event log. Each event records: actor identity, timestamp,
   `from_state → to_state`, the inputs the decision was made against
   (including the release context where applicable), `rule_version`, and the
   hash of the preceding event. Verifying the chain is a public operation; a
   broken chain is a hard error, never a warning.

3. **`oracle/disposition/release.py`** — the §7.1 release gate, whole:
   - An immutable `ReleaseContext`: effective run date, target configurations,
     target part classes, evidence link-confidence threshold.
   - Per-unit eligibility evaluated against that context — evidence present and
     above threshold for CW/MI; accepted, **non-superseded**, in-window
     acceptance whose approved scope covers **every** supplied dimension
     independently for MI/EX; OPEN never eligible (§2.1).
   - Package-level all-or-nothing marking: either every unit in the package is
     eligible and all are marked, or none are and the reason is reported.
   - Atomic application via **write-temp-rename**; idempotent under retry.

4. **`oracle/disposition/identity.py`** — authenticated actor identity and a
   role/permission model gating every transition. Machine paths remain
   restricted to `proposed` (§1.2). An unauthorized transition is rejected
   **and logged** — the rejection is itself an audit event.

5. **Concurrency** — optimistic version checks implemented as the contract now;
   the enforced v1 model is an honest **single-writer file lock** (P-4). Two
   concurrent writers must not both commit conflicting transitions. Document
   the lock's honest limits in the module docstring; do not advertise
   guarantees the implementation cannot keep.

6. **Re-import conflict handling** — a re-imported package that conflicts with
   recorded state is rejected with a specific, actionable diff, never merged
   silently.

7. **Wire S1's deferral to this slice** — replace `transition_unit`'s
   `NotImplementedError` with delegation to `release.py`, and relax the
   constructor's `release_approved` guard to the controlled path only. **This is
   the only permitted edit to `models.py`.** The guard must not simply be
   deleted: a released unit must remain impossible to construct outside the
   audited path.

8. **Tests** (`tests/disposition/`):
   - Chain tampering: mutate a mid-chain event → verification fails.
   - Unauthorized transition → rejected *and* an audit event written.
   - Concurrency: two writers, conflicting transitions → exactly one commits.
   - Crash safety: interrupt mid-transition → store reopens consistent.
   - Release gate: low-confidence evidence, expired acceptance, future-dated
     acceptance, superseded acceptance, scope covering part class but **not**
     configuration (each dimension checked independently), OPEN unit.
   - Idempotency: replaying the same release marking changes nothing.
   - Round-trip: export → re-import → no conflict; tampered export → rejected.

## Module standards

BoundState headers on every module, `Safety Critical:` field, and
`__safety_critical__` dunder. **S1a is the first disposition slice where
`__safety_critical__: bool = True` is correct** for `release.py`, `eventlog.py`,
and `identity.py` — these decide and record release authority. `LOGGER =
logging.getLogger("oracle.disposition.<module>")`, type hints everywhere, no bare
except, no print, functions < 50 lines, docstrings on public classes/functions.

**Never suppress an error in this slice.** A failure is logged in full and
surfaced as a refusal. A persistence or release path that fails *open* — writing
a partial record, marking a package released on incomplete evidence, continuing
past a broken hash chain — is the cardinal failure mode here.

## Done when

- An unauthorized transition is rejected **and logged**.
- A tampered import/export is rejected.
- Two concurrent writers cannot both commit conflicting transitions.
- A crash mid-transition leaves a consistent, recoverable state.
- Release marking is all-or-nothing and idempotent under retry.
- Every §7.1 release blocker has a test that proves it blocks.
- `transition_unit` produces `release_approved` only through the audited path;
  direct construction still raises.
- Full repo suite green; diff coverage ≥ 80% of added lines.

## Never touch

- `docs/ORACLE_DISPOSITION_SPEC.md` and `docs/oracle_runs/*` — the contract and
  the history.
- `tests/disposition/fixtures/*` — the regression corpus.
- `oracle/disposition/codes.py`, `state.py`, `rollup.py` — S1 deliverables,
  rated Met. `models.py` may be edited **only** for deliverable 7.
- `oracle/oracle2.py`, `oracle/cli.py`, `oracle/chat_engine.py`, and every other
  existing `oracle/` module.
- `hearth/*` — **dead code.** Do not read, reference, import, or modify it, and
  do not treat it as a reference implementation regardless of what the parent
  plan says.
- `pipeline/*`, `.github/*`.

## Stop if

- Implementing any deliverable requires changing a behavioral contract in the
  spec — stop and report; that is an errata RFC per the plan's graded errata
  channel, not a build decision.
- The release gate cannot be implemented whole against an explicit context —
  stop rather than shipping a partial gate. **A partial release gate is the
  failure mode this slice exists to prevent.**
- Enforcing an invariant appears to require a caller-settable module-level flag,
  a privileged public factory, or an unvalidated copy path. Python cannot make a
  data model tamper-proof in-process; if that is what a requirement seems to
  demand, the enforcement belongs at the store/event-log boundary instead. Stop
  and say so rather than iterating on bypass blocklists.
- More than trivial changes are needed outside `oracle/disposition/` and
  `tests/disposition/`.
