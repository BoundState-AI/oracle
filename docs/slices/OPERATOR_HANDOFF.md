# Disposition Build — Operator Handoff (Claude Code, local)

**Your role:** build **operator**, not builder. The ensemble is fixed: Ben
(grok CLI) builds, Atlas (codex CLI) reviews, Beth (Anthropic API) gates —
orchestrated by `pipeline/oracle_build.py`. You operate the pipeline,
diagnose failures, keep git hygiene, and defend the contracts. You write
code directly only for trivial mechanical issues, and anything you touch
still goes back through the gate.

## Read first, in order

1. `docs/DISPOSITION_SLICE_PLAN.md` — canonical plan, decisions P-1..P-5
2. `docs/slices/S1_SPEC.md` — the current slice's contract
3. `docs/DISPOSITION_BUILD_RUNBOOK.md` — the run mechanics
4. `pipeline/README.md` — pipeline controls: CHECK stage, diff-coverage
   floor, protected paths, `--ben-model` pin, environment-failure triage
5. Reference only, NEVER edit: `docs/ORACLE_DISPOSITION_SPEC.md` (v0.5.0
   build contract), `docs/oracle_runs/*` (immutable run records),
   `tests/disposition/fixtures/*` (merge-blocking regression corpus)

## State as of handoff (2026-07-29)

- Working branch `build/disposition-s1`, which must be fast-forwarded to
  `origin/claude/loop-harness-engineering-l3nxl7` (verify with
  `git log --oneline -1 origin/claude/loop-harness-engineering-l3nxl7`;
  if behind: `git fetch` + `git merge` — safe, S1 work is untracked).
- Ben has built S1 as **untracked** files: `oracle/disposition/`
  (`__init__`, `codes`, `models`, `rollup`, `state`) and
  `tests/disposition/test_*.py` including `test_fixture_harness.py`.
  22 slice-local tests green.
- Engagement material and `oracle_campaign.py` were evacuated to
  `..\s1_overflow` — never bring them back into the tree; the tailoring
  docs are customer-identifying (D-3) and must not enter any diff or any
  LLM context.
- Full suite must show **0 failed** (~568 passed, ~6 skipped on Windows)
  before gating. The autouse conftest fixture strips vendor keys inside
  tests; the pipeline process itself keeps the key for Beth.

## The gate run

```
py pipeline\oracle_build.py docs\slices\S1_SPEC.md --repo . --fix-rounds 2 --coverage-floor 80 --check-cmd "py -m pytest tests -q" --skip-build
```

Artifacts land in `oracle_builds\<timestamp>\`: `PIPELINE_REPORT.md` (the
verdict), `PIPELINE_STATE.md` (round record + toolchain provenance),
`check_round*.md`, Atlas reviews, fix logs.

## Hard rules

- **Protected files are never edited by anyone** — the CHECK stage fails a
  round that touches them, and that includes you. A spec defect is an
  errata RFC per the plan's graded errata channel, never a quiet patch.
- **Never** edit the fixture to make a test pass; never relax, skip, or
  delete a test to get green; never inflate coverage with assertion-free
  tests. These are named gate offenses.
- Environment failures (missing packages, broken tooling) are operator
  work — the pipeline halts with an ENVIRONMENT marker instead of routing
  to Ben. Fix the env, re-run.
- **Commit only on Beth's APPROVED**: all S1 files to `build/disposition-s1`,
  message citing the slice, the verdict, and the report path. Never push to
  main. Never open a PR unasked.
- On CHANGES REQUIRED: read `PIPELINE_REPORT.md` + `PIPELINE_STATE.md`
  first. Prefer routing fixes through the pipeline's fix rounds (Ben, with
  provenance) over direct edits; if you do edit directly, re-run the gate —
  nothing is done without a green gate.
- Model pins: Atlas and Beth are pinned in code; pin Ben with
  `--ben-model` / `ORACLE_BEN_MODEL` (verify the grok CLI's flag name via
  `grok --help` before first pinned use — the pipeline assumes `--model`).

## After S1 lands (APPROVED + committed)

1. Cut `docs/slices/S1a_SPEC.md` from the plan's S1a section, same format
   as `S1_SPEC.md` (Goal / Deliverables / Module standards / Done when /
   Never touch / Stop if). Key content per decision P-4: append-only,
   hash-chained JSONL event log on the HEARTH evidence-store pattern —
   HEARTH was removed from the working tree; the reference implementation
   lives in git history: `git show 28b807a:hearth/db/evidence_store.py`
   and `git show 28b807a:hearth/audit/artifact.py` — atomic
   release-marking via write-temp-rename, single-writer file lock with the
   optimistic version-check contract implemented, authenticated actor
   identity on every transition.
2. Fresh branch `build/disposition-s1a` from the updated base; same gate
   command with the new spec path.
3. One slice per branch, one gate per slice, session-per-slice discipline.
4. Log operator lessons as you go — they feed the retro (`oracle retro`
   is designed but unbuilt; until then, a LESSONS section appended to the
   slice's PIPELINE_STATE.md or a note in the commit message suffices).
