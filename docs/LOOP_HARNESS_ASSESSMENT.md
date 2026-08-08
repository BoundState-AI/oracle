# Loop & Harness Assessment — Oracle Build Pipeline vs. "7 files, 5 steps"

**Status:** Assessment / design note, not scheduled.
**Author:** Dr. Joseph Wilde / Claude
**Date:** 2026-07-15
**Motivates:** end-to-end idea → spec → code that works unattended.
**Evaluates:** the "Loop and Harness engineering: 7 files, 5 steps" framework
  (ArchiveExplorer, 2026-06-28) against `pipeline/oracle_build.py` and
  `pipeline/oracle_review.py`.

---

## 1. Verdict up front

The article's core diagnosis is right and applies to us, but most of its
*prescriptions* are things the oracle pipeline already does — often better
than the article's version. The framework's value here is as a **failure-mode
checklist**, not an architecture to adopt.

Measured against it, the pipeline has **one large hole and three small ones**:

1. **No deterministic verification anywhere in the loop.** Nothing ever runs
   `pytest`. This is the article's "confident garbage" failure mode, and it is
   real for us. *(Large — fix first.)*
2. No per-round state file → the same finding can be re-litigated every fix
   round. *(The "Ralph Wiggum loop" risk, in miniature.)*
3. Builder permissions are all-or-nothing (`--always-approve`) with no
   protected-paths check afterward.
4. Specs enter the build stage as free-form markdown — no machine-checkable
   "Done when / Never touch / Stop if" contract, which is exactly what the
   spec-review half of the toolchain could emit.

Everything else the article warns about, we already handle. The recommended
work is four bounded changes to `pipeline/`, not a `.claude/` folder build-out.

---

## 2. What we already have (scorecard)

| Article concept | Oracle pipeline today | Grade |
|---|---|---|
| Fresh context per iteration (Ralph pattern) | Every Ben/Atlas pass is a new CLI process; state lives on disk in `oracle_builds/<ts>/` | ✅ Have it |
| Verifier in a fresh context | **Cross-vendor** adversarial review: Grok builds, Codex reviews, Fable gates. Stronger than the article's same-vendor Haiku verifier — a different lab's model can't "agree with itself" | ✅ Better than the article |
| Goal spec on disk, re-read each iteration | `spec_path` is handed to BUILD, FIX, every REVIEW round, and the GATE | ✅ Have it |
| Fail-closed loop control | Verdict parsing defaults to FIX FIRST / CHANGES REQUIRED; gate refuses on truncated diff; non-APPROVED exits non-zero | ✅ Have it |
| Sub-agent fan-out | `oracle_review.py` runs three reviewers in parallel (`ThreadPoolExecutor`) | ✅ Have it |
| Context rot containment | Diff hard-capped at 200K chars; strict mode refuses rather than truncates at the gate; each stage is a fresh context | ✅ Have it |
| Per-run persistence | Timestamped artifact dirs: build log, per-round reviews, fix logs, `PIPELINE_REPORT.md` | ✅ Have it |
| Bounded blast radius | Clean-tree guard, never commits/pushes, Codex read-only, damage bounded to uncommitted changes in one repo (authorized 2026-07-13) | ✅ Have it |
| **Deterministic policy floor (hooks)** | **Nothing. No test run, no lint, no protected-path check between stages** | ❌ Missing |
| State file the loop updates (`IMPLEMENTATION_PLAN.md`) | Fix rounds don't carry forward what was dismissed and why | ❌ Missing |
| Standing context for the builder (`CLAUDE.md` equivalent) | BoundState standards are inlined in `BUILD_PROMPT`; Ben re-derives each target repo's shape every build | ⚠️ Partial |
| Machine-checkable goal-spec shape | Any markdown accepted as spec | ⚠️ Partial |
| Scheduler (cron) | None — human-triggered | ➖ Deliberately absent (see §5) |
| MCP servers | None — agents read the repo directly | ➖ Not needed |
| Cross-session memory (`MEMORY.md`) | None | ➖ Premature (see §5) |

---

## 3. The gaps, ranked, with the concrete fix

### 3.1 Deterministic verification — the one that matters

The article's three killer failure modes are (a) confident garbage,
(b) context rot, (c) repeated iterations. We've engineered (b) and (c) down.
**(a) is wide open**: verification in the pipeline is 100% LLM opinion.

- `BUILD_PROMPT` tells Ben to *write* tests and *say* how to run them — nobody
  runs them.
- Atlas reviews in a `--sandbox read-only` Codex session — he *can't* run them.
- Beth gates on spec + diff + review history — no test output in evidence.

An implementation whose tests fail (or don't collect) can currently reach
SHIP/APPROVED on vibes. This is also the expensive path: we spend
Atlas-terra-high and Fable-high tokens reviewing code that `pytest` would have
rejected in 30 seconds.

**Fix:** add a CHECK stage to `run_pipeline()` between BUILD and REVIEW and
after every FIX round:

1. Run the target repo's test command (`pytest tests/ -q` here; make it a
   `--check-cmd` flag with a per-repo default) with a timeout.
2. On failure: skip Atlas, feed the failure tail straight back to Ben as a fix
   round (deterministic failures are the cheapest possible review findings).
3. Always append the final CHECK output to the gate input, so Beth judges with
   test evidence, not just prose. A gate with failing tests fails closed to
   CHANGES REQUIRED regardless of her verdict.

This is the article's "hooks = policy floor" idea, landed at the pipeline
level where our loop actually lives. It is the single highest-value change.

### 3.2 Round-state file — stop re-litigating findings

Each Atlas round re-reviews the whole diff fresh. Ben dismisses findings with
reasons (`FIX_PROMPT` requires it), but the dismissals live only in that
round's fix log — round N+1's review request never sees them, so Atlas can
re-raise the identical Medium every round and Ben re-dismisses it. That is the
Ralph Wiggum loop in miniature: bounded by `--fix-rounds`, but it wastes the
rounds we have.

**Fix:** maintain `PIPELINE_STATE.md` in the artifact dir — findings
addressed (with the change), findings dismissed (with the reason), decisions
deferred. Append it to each round's review request: *"Previously dismissed
with reasons below — re-raise only if the reason is wrong, and say why."*
The gate gets it too; it already gets the review history, so this completes
the record.

### 3.3 Protected-paths check — permissions with teeth

Ben runs `--always-approve` with the whole working tree writable. The
guardrails (clean tree, no commit/push) bound the *blast radius* but not the
*target*: nothing stops a build from editing merged migrations, signed packs
(HEARTH packs require re-signing — a stale signature is drift), or golden
files.

**Fix:** deterministic post-build/post-fix check (part of the CHECK stage):
diff the touched paths against a protected list. Source the list from a
`## Never touch` section in the spec plus a small per-repo default
(`db/migrations/`, `*.golden`, `hearth/packs/*.json`, …). Violation ⇒ the
round fails with a named finding before any LLM sees it. This is cheaper and
more portable than per-CLI permission systems (grok's permission model is
coarse; a diff check works for any builder).

### 3.4 Spec contract — make the handoff machine-checkable

The article's goal-spec shape (`# Done when / # Never touch / # Stop if`) is
the piece that connects our two halves. Today ORACLE reviews a spec to
convergence, then a human pastes free-form markdown into the build pipeline.
If the spec-review stage **emits those three sections as a required
epilogue**, then:

- "Done when" gives Atlas and Beth explicit acceptance criteria instead of
  inferring them (Beth's `## Spec Coverage` section becomes mechanical).
- "Never touch" feeds the §3.3 protected-paths check.
- "Stop if" gives `run_pipeline()` legitimate early-abort conditions
  (e.g. "more than N files outside `<scope>` changed") checked
  deterministically from the diff.

`oracle_build.py` should warn (not refuse) when a spec lacks the sections, so
existing free-form specs keep working.

### 3.5 Standing context for the builder — small, do last

Ben re-derives each target repo's shape every build. Codex reads `AGENTS.md`
by convention; grok picks up repo context files too. **Fix:** `BUILD_PROMPT`
gains one line — "Read `AGENTS.md` / `CLAUDE.md` at the repo root first and
obey it" — and the pipeline logs a warning when the target repo has neither.
Keep those files under ~300 lines; the article's context-bloat warning is
consistent with what we've seen on oracle2 token budgets.

---

## 4. End-to-end: closing the idea → spec → code seam

Both halves already live in this repo: ORACLE spec review to convergence
(`oracle review` / the web workspace) and spec → code
(`pipeline/oracle_build.py`). The seam is a human copy-paste. Two options:

- **Keep the human seam (recommended for now).** It's our human promotion
  gate, same philosophy as pack promotion (non-TTY fails closed). With §3.4's
  spec contract, the paste becomes a *review-and-approve* of a
  machine-checkable artifact rather than free-form transcription.
- **Later:** a thin `oracle ship idea.md --repo …` orchestrator that runs
  spec review to convergence, stops for explicit human approval of
  `FINAL_SPEC.md` (fail closed when non-TTY, like `promote-pack`), then
  invokes `run_pipeline()`. No new machinery — sequencing two existing
  callables with the same gate pattern we already trust.

Do **not** put a scheduler on this. Unattended `--always-approve` builds on a
cron tick would widen the exact blast radius the 2026-07-13 authorization
deliberately bounded, and nothing about our workload is periodic.

---

## 5. What to skip from the article, and why

- **The `.claude/` seven-file layout.** Our builder is Grok and our reviewer
  is Codex; `.claude/` only configures Claude Code sessions. The *concepts*
  transfer (and are handled above); the folder does not. A minimal
  `.claude/settings.json` for developing *this* repo with Claude Code is a
  separate, optional nicety.
- **MCP servers.** Reviewers read the repo directly with their own tools;
  adding MCP is attack/maintenance surface with no consumer.
- **Skill libraries / fan-out frameworks** (194 agents, 60+ agent types).
  `oracle_review.py` already fans out; three named reviewers with distinct
  lenses is the right size. Adding shapes speculatively is the article's own
  anti-pattern ("three skills built when you hit the task a third time beat
  fifty built speculatively").
- **`MEMORY.md` cross-session memory.** Per-run artifact dirs already persist
  everything. Cross-run memory earns its keep when the same correction recurs
  across builds — revisit after §3.2 exists, since `PIPELINE_STATE.md` files
  are exactly the raw material such a memory would be distilled from.
- **The article's citations.** Repo star counts and the arXiv number don't
  check out at face value; treat the piece as a practitioner checklist, not a
  literature review. The checklist itself is sound.

---

## 6. Recommended order of work

> **Update 2026-07-16:** items 1–3 shipped in `pipeline/oracle_build.py`
> (tests in `tests/test_pipeline_build.py`; repo defaults in
> `.oracle_protected`; usage in `pipeline/README.md`).

| # | Change | Where | Size |
|---|---|---|---|
| 1 | ✅ CHECK stage: run tests + feed failures back to Ben, test evidence into the gate, fail closed on red | `pipeline/oracle_build.py` | ~80 lines |
| 2 | ✅ `PIPELINE_STATE.md` carried across fix rounds | `pipeline/oracle_build.py` | ~40 lines |
| 3 | ✅ Protected-paths diff check (spec `## Never touch` + per-repo defaults) | `pipeline/oracle_build.py` (CHECK stage) | ~40 lines |
| 4 | Spec contract sections emitted by spec review, warned-on by build | spec-review prompt + `oracle_build.py` | small |
| 5 | `AGENTS.md` read-first line in `BUILD_PROMPT` + missing-file warning | `pipeline/oracle_build.py` | trivial |
| 6 | `oracle ship` orchestrator with human approval gate | new thin CLI | later |

Items 1–3 turn the existing loop from "LLM opinions all the way down" into
the article's plan → act → **verify** shape without changing its
architecture. Item 4 is what actually makes idea → spec → code one system
instead of two tools and a paste buffer.
