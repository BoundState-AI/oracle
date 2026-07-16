# Idea-to-Platform Roadmap — after the deterministic layer

**Status:** Assessment / design note, not scheduled.
**Author:** Dr. Joseph Wilde / Claude
**Date:** 2026-07-16
**Follows:** `docs/LOOP_HARNESS_ASSESSMENT.md` (items 1–3 shipped 2026-07-16).
**Goal:** one system that takes an idea to a **running platform** — spec,
code, integration, deploy, and iteration — with humans at a small number of
named gates instead of everywhere.

---

## 1. Where the chain stands

```
idea ──(manual)──▶ spec ──ORACLE review──▶ converged spec ──(paste)──▶
  oracle_build: BUILD → CHECK → REVIEW → FIX → GATE ──▶ uncommitted diff
  ──(manual: commit, PR, merge, deploy, observe)──▶ platform
```

Everything left of "uncommitted diff" is now strong: adversarial spec review
to convergence, cross-vendor build/review, deterministic checks, fail-closed
gating. Everything right of it is manual. The MES build proved the middle;
"idea-to-platform" is about the two ends.

The structural insight: **the pipeline produces one diff and stops. A
platform is many increments over time on a living repo plus a running
environment.** That implies three missing layers:

1. **Program layer** (above single runs) — decompose a platform into
   milestone specs and run the pipeline once per milestone, compounding.
2. **Integration layer** — each APPROVED run must become a commit/PR with
   independent CI, or runs can't compound at all (the clean-tree guard
   *forces* a human commit between runs today).
3. **Operations layer** — deploy, smoke in the real runtime, and feed what
   the gate keeps catching back into the next build.

---

## 2. Tier 1 — fuse and compound (the program layer)

### 2.1 Commit-on-APPROVED *(do this first — it unblocks everything else)*

Today an APPROVED run leaves uncommitted changes; the next run refuses to
start until a human commits. Add to `oracle_build.py`:

- On **APPROVED + green CHECK**: commit the working tree to the current
  branch with a structured message (spec name, run id, gate verdict, link to
  the artifact dir). Never on CHANGES REQUIRED/REJECTED — those stay in the
  tree for inspection, exactly as now.
- `--branch <name>`: create/checkout a build branch before Stage 1, so main
  is never the working target. `--push` (off by default) pushes the branch
  and opens a PR — merge stays human.
- This is the *only* place the pipeline gains git-write powers, it is
  verdict-gated, and it never touches the default branch. It converts runs
  from disposable diffs into compounding increments.

### 2.2 Spec contract (assessment item 4)

The spec-review stage emits a required epilogue: `## Done when` /
`## Never touch` / `## Stop if`. The build side already consumes
`## Never touch`; `## Done when` becomes Beth's mechanical coverage
checklist; `## Stop if` gives `run_pipeline` deterministic early-abort
conditions (e.g. "more than N files outside `<scope>` changed" — checkable
from the diff). Build warns, not refuses, on free-form specs.

### 2.3 `oracle ship` orchestrator (assessment item 6)

Thin CLI: idea/spec in → ORACLE review to convergence → **human approval of
FINAL_SPEC.md** (TTY prompt; non-TTY fails closed, same as `promote-pack`)
→ `run_pipeline()`. No new machinery — sequencing two callables we already
trust, with the existing promotion-gate pattern between them.

### 2.4 Program mode: milestone decomposition + ledger

A platform is too big for one run (200K-char gate cap, one spec, one
sitting). Add:

- `PLATFORM_PLAN.md`: ordered milestone specs (each with its own contract
  sections), produced with ORACLE's help from the converged platform spec.
- **Review the plan itself** before any code: one adversarial ORACLE pass
  over the decomposition (bad sequencing and hidden coupling are cheapest to
  catch here — this is where a platform build actually fails).
- `oracle ship --plan PLATFORM_PLAN.md`: run milestones sequentially; each
  is a full BUILD→CHECK→REVIEW→FIX→GATE cycle committing on APPROVED
  (§2.1); stop the program on the first non-APPROVED milestone.
- `PROGRAM_LEDGER.md`, append-only: one line per run — timestamp, milestone,
  rounds used, verdict, commit SHA, artifact dir. The chain-of-custody for
  the whole build, in the spirit of HEARTH's audit artifacts.

---

## 3. Tier 2 — verification depth (the integration layer)

### 3.1 Named check lists (`.oracle_checks`)

`--check-cmd` runs one command. Platforms need several, individually named
in the gate evidence: lint, typecheck, tests, migration dry-run, dependency
audit, **boot smoke**. Add an `.oracle_checks` file at the target repo root
(ordered `name: command` lines); `--check-cmd` stays as the single-command
override. All results — not just pass/fail overall — go to Beth by name.

### 3.2 Boot smoke — a platform must *run*, not just pass tests

The check a test suite can't give you: start the thing and poke it.
Convention: a `smoke:` entry in `.oracle_checks` (e.g. start uvicorn, curl
`/health`, exit non-zero on anything but 200, kill). For frontends, an
optional Playwright script slot. This closes the classic "tests green, app
won't boot" gap — the difference between code and platform.

### 3.3 Dependency-diff flag

Ben can add dependencies silently. Deterministically diff the manifest files
(`pyproject.toml`, `requirements*.txt`, `package.json`) and surface any
additions as a named gate item; the gate requires a justification from the
build summary for each new dep. Cheap, and it is the supply-chain surface of
an unattended builder.

### 3.4 CI parity on the PR

With §2.1's PR flow, the target repo's Actions should run the same checks
(this repo's `tests.yml` is the model: fully mocked, so red = regression,
never vendor outage). The human merge gate then has an *independent* green —
not the pipeline grading its own homework.

### 3.5 `AGENTS.md` read-first (assessment item 5 — trivial, fold in anywhere)

One line in `BUILD_PROMPT` (+ a missing-file warning) so Ben stops
re-deriving each target repo's shape every build.

---

## 4. Tier 3 — operate and learn (the operations layer)

### 4.1 Scripted staging deploy + post-deploy smoke

Deploys here are already one-liners (Procfile/uvicorn). Make "deploy to
staging + run the smoke check + attach the gate report" a single scripted
command that program mode can invoke after a human merge. **Production stays
a human button** — the pipeline never gains prod credentials. Same posture
as pack promotion: automation right up to the irreversible step, never
through it.

### 4.2 Cross-run lessons (`.oracle_lessons`)

The assessment called memory premature at single-run scale. Program mode
changes that: when the same gate residual or dismissed-finding pattern shows
up across runs, distill it into a capped per-repo `.oracle_lessons` file
that `BUILD_PROMPT` tells Ben to read. Feed the loop's outputs back into its
inputs — this is the cheapest quality lever once volume exists. Keep it
pruned (the state files from §2.4 are the raw material).

### 4.3 Run telemetry and cost accounting

Per run: stage durations, rounds used, check outcomes, verdict flips,
Fable token spend; per program: roll-up. Lands in the report + ledger.
This answers the questions you'll actually ask after three platform builds:
is `--fix-rounds 1` right? Where does wall-clock go? What does a milestone
cost? (`eval/live` and oracle2's run-telemetry patterns are the in-house
prior art.)

### 4.4 Bring `oracle.py` (spec polisher) into this repo

The chain's first tool lives at `D:\BoundState\oracle.py`, outside version
control here. For a product whose pitch is "one system, idea to platform,"
half the front door being an unversioned desktop script is the wart to fix:
import it under `pipeline/` (or `oracle/`), test its verdict/convergence
parsing the way the build side now is.

### 4.5 Idea intake (optional, last)

`document_generator.py` covers the *output* side (polished docx/pptx).
The *input* side — a structured interview that turns a raw idea into a
draft spec ORACLE can start reviewing — is missing but cheap to add as a
prompt stage in `oracle ship`. Human-written idea docs work fine until then.

---

## 5. Still deliberately out of scope

- **Autonomous production deploys** — human button, always.
- **Cron/scheduled builds** — nothing here is periodic; a scheduler widens
  the blast radius the 2026-07-13 authorization deliberately bounded.
- **Parallel multi-repo fan-out / worktree swarms** — revisit only after
  program mode has shipped two platforms sequentially; sequencing with
  commits is the 80% and carries none of the merge-conflict machinery.

---

## 6. Recommended order

| # | Change | Layer | Size |
|---|---|---|---|
| 1 | Commit-on-APPROVED + `--branch`/`--push` PR flow | program | ~80 lines |
| 2 | Spec contract emitted by spec review, consumed by build | program | small |
| 3 | `oracle ship` orchestrator (human spec gate) | program | ~150 lines |
| 4 | Program mode: plan review, milestone loop, ledger | program | ~200 lines |
| 5 | `.oracle_checks` named check lists + boot smoke | integration | ~80 lines |
| 6 | Dependency-diff gate item | integration | ~40 lines |
| 7 | `AGENTS.md` read-first in BUILD_PROMPT | integration | trivial |
| 8 | Lessons file fed to BUILD | operations | ~50 lines |
| 9 | Telemetry + cost in report/ledger | operations | ~80 lines |
| 10 | Scripted staging deploy + smoke | operations | ~60 lines |
| 11 | Import `oracle.py` into the repo + tests | operations | move + tests |
| 12 | Idea-intake interview stage | operations | later |

The end state, with humans at exactly three gates: **approve the spec,
merge the PR, press the prod button.** Everything between those is the
pipeline's job — and after items 1–5 it can do that job for a platform, not
just a diff.
