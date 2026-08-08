# Build Learning Loop — making run N+1 better than run N

**Status:** Design note, not scheduled.
**Author:** Dr. Joseph Wilde / Claude
**Date:** 2026-07-16
**Follows:** `docs/LOOP_HARNESS_ASSESSMENT.md`, `docs/IDEA_TO_PLATFORM_ROADMAP.md` (§4.2 expanded here).
**Question answered:** how does the idea-to-platform system *learn from builds*?

---

## 1. The principle: the weights are frozen — the harness learns

Ben, Atlas, and Beth are vendor models. We cannot train them, and their
in-context "memory" dies with each fresh process (by design — fresh context
is why the loop works). So "learning" has exactly one honest meaning here:

> **Convert run evidence into harness artifacts that change future runs.**

And there is a ladder for where each lesson should land. Always push a
lesson to the *lowest* rung that can hold it:

| Rung | Artifact | Properties |
|---|---|---|
| 0 | Deterministic check (`.oracle_checks`, `.oracle_protected`, lint/CI config) | Cannot be ignored, costs zero tokens, never drifts |
| 1 | Signed pack micro-rule (rules-are-data, per-repo build-lessons pack) | Versioned, signed, human-promoted — same lifecycle packs already have |
| 2 | Prompt lesson (`.oracle_lessons` → BUILD_PROMPT; lens addenda for reviewers) | Cheap to add, **weakest**: can be ignored, taxes every future run's context, rots |
| 3 | Loop tuning (`--fix-rounds` defaults, timeouts, model presets) | Telemetry-driven config, changed by a human |

The discipline that makes or breaks the system: **a lesson that can be a
check must become a check.** "Ben keeps leaving bare excepts" is not a
prompt lesson — it's a lint rule in `.oracle_checks`. Prompt memory is the
rung of last resort, reserved for what can't be mechanized (architecture
preferences, "we chose X over Y because…", domain constraints).

This is the same shape ORACLE already chose for compliance: detections live
in signed rule packs, never hardcoded, never vibes. Lessons are rules about
*our own builds* — they get the same treatment.

---

## 2. The signal: what runs already emit, ranked by label quality

Every run writes structured evidence. Ranked by how trustworthy the label is:

1. **Post-merge human fixes** *(strongest — requires commit-on-APPROVED)*.
   Diff what the pipeline committed against what the human actually merged
   or hot-fixed after. Anything the human changed is a defect the entire
   ensemble missed — ground truth, no model opinion involved.
2. **Gate residual findings.** Beth's `## Residual Findings` survived build,
   deterministic checks, adversarial review, and fix rounds. High-value.
3. **Dismissal outcomes.** Ben dismisses findings with reasons
   (`PIPELINE_STATE.md` records them); the gate adjudicates. *Overturned*
   dismissal → builder blind spot (lesson for Ben). *Upheld* dismissal →
   reviewer false-positive pattern (lesson for Atlas's lens — handle with
   care, §6).
4. **Recurring CHECK failures.** The same failure class across rounds or
   runs (import cycles, missed migrations, golden-file touches) → builder
   lesson, or evidence an existing lesson isn't working.
5. **Gate residuals that a check could have caught.** Every residual gets
   one explicit question in retro: *could a command have detected this?*
   Yes → new `.oracle_checks` entry (rung 0), not a prompt lesson.
6. **Telemetry.** Rounds-to-converge, verdict flips, stage durations, spend
   → rung-3 tuning signal only.

`PIPELINE_STATE.md` already structures 2–4 per run; the program ledger
(roadmap §2.4) accrues them across runs; item 1 needs the commit flow.

---

## 3. The mechanism: `oracle retro`

A separate command, not a pipeline stage — learning should look at *many*
runs, and must never block a build:

```
oracle retro --repo <target>            # scans <repo>/oracle_builds/*/
oracle retro --repo <target> --promote  # interactive promotion (TTY only)
```

**Pass 1 — deterministic harvest (no LLM).** Parse every run's
`PIPELINE_STATE.md`, check reports, and `PIPELINE_REPORT.md` into a run
table: findings, dismissals + outcomes, check failures, verdicts, rounds,
cost. Where the ledger has commit SHAs, compute post-merge deltas.

**Pass 2 — Fable distillation.** One high-effort pass over the table
proposes candidate lessons, each with:

- `rung`: 0/1/2/3 (with the §2.5 question forced: "why is this not a check?")
- `provenance`: run ids + quoted evidence (a candidate without provenance
  is discarded on sight — no claims without evidence, house rule)
- `recurrence predicate`: how a future retro will know the lesson fired or
  prevented (e.g. "check `no-bare-except` fails", "gate residual mentions
  migration ordering")
- `consumer`: Ben / Atlas lens / Beth lens / checks / config

Output: `LESSONS_DRAFT.md`. **Drafts are inert.** Nothing reads them.

**Pass 3 — human promotion.** Same pattern as `promote-pack`: interactive,
per-lesson accept/edit/reject, **non-TTY fails closed**. Accepted lessons
are routed to their consumer artifact:

- rung 0 → an `.oracle_checks` / `.oracle_protected` entry (deterministic
  from then on; retire any prompt-lesson ancestor it replaces)
- rung 1 → micro-rule appended to the repo's `build-lessons` pack, re-signed
- rung 2 → `.oracle_lessons` at the target repo root; `BUILD_PROMPT` gains
  one standing line: *"Read `.oracle_lessons` at the repo root first and
  obey it."* Reviewer-lens lessons land in a separate
  `.oracle_lessons_review`, consumed by the review-request builder.
- rung 3 → a config recommendation in the retro report; a human edits
  defaults.

**The system never edits its own active memory.** Auto-promotion is scope
creep into a self-modifying agent — the exact thing the pack-promotion gate
exists to prevent. Drafting is automated; authority is human.

---

## 4. Memory hygiene: lessons pay rent

Unbounded append-only memory is the article's own named killer (context
rot), and every rung-2 lesson taxes every future build's context. So:

- **Hard caps.** `.oracle_lessons` ≤ ~40 lessons / ~300 lines. At cap,
  promotion requires retiring something — forced prioritization.
- **Hit tracking.** Retro evaluates every *active* lesson against the new
  runs via its recurrence predicate:
  - Failure class recurred anyway → lesson is ineffective: escalate a rung
    (make it a check/rule) or rewrite it. Repeated ineffectiveness is
    itself the strongest possible signal the lesson belongs at rung 0.
  - Quiet for M runs (default 5) → flagged for retirement at next
    promotion session. Rung-0 checks are exempt — they cost nothing and
    stay forever.
- **Scope.** Lessons are per-target-repo by default. A lesson observed
  across ≥2 repos may be promoted to the shared standards layer (global
  CLAUDE.md / code-quality skill / BUILD_PROMPT itself) — that promotion is
  a reviewed code change to this repo, nothing looser.
- **Format.** One lesson = one line + provenance ref:
  `L-014 [rung2] [hits:2 quiet:0] Alembic migrations: never import app models — copy column defs inline. (runs 20260714_1, 20260715_2)`

---

## 5. Proving it learned: the measurement loop

Without measurement, "learning" is vibes with extra files. Two instruments,
both extensions of infrastructure this repo already runs:

**5.1 The ledger scorecard** (per run → trended per program): rounds to
converge, findings by severity per stage, dismissal-upheld rate,
check-catch rate (failures caught before any reviewer token), gate verdict,
spend — and the **true-north metric: post-merge human fixes per milestone**.
That number trending toward zero is the only definition of "the next build
is better" that can't be gamed by the pipeline agreeing with itself faster.

**5.2 A seeded-defect build eval** (`eval/live` pattern, build flavor).
`eval/live` already release-gates the *spec-review* system: planted defects
must be detected, known-sound docs must not attract inventions, budgeted
false positives. Build the sibling: a small corpus of (spec, repo, prepared
diff) cases with planted defects — one per class the pipeline claims to
catch (logic bug, missed spec requirement, protected-path edit, failing
test, dependency smuggling). Run CHECK→REVIEW→GATE over them in
`--skip-build` mode (no Ben — cheap and deterministic to set up) and score
detection + false-positive budgets.

**Run it whenever a prompt, lens, lesson file, or check list changes.**
Prompt and lesson edits are code changes to the pipeline's brain; this is
their regression suite. Without it, "learning" can silently lobotomize a
reviewer — the exact failure `oracle.drift` exists to catch on the spec
side, measured instead of asserted.

**Anti-Goodhart pairing:** never celebrate rounds-to-converge dropping on
its own. Pair it with gate residuals and post-merge fixes. Faster
convergence + rising residuals = the loop got sycophantic, not smarter
(drift.py's lesson, generalized to the whole pipeline).

---

## 6. Failure modes designed against

- **Lesson bloat / context rot** → caps + rent + retirement (§4).
- **Over-generalizing one incident** ("never use threads!") → provenance
  required; default rule: rung-2 promotion wants **two** independent
  occurrences, one occurrence promotes only to rung 0 if mechanizable.
- **Reviewer echo chamber** → lessons anchored to *ground truth* (check
  failures, post-merge fixes, gate-upheld outcomes) outrank lessons
  anchored to model opinion. Lens addenda for Atlas/Beth are the riskiest
  artifact class: gate them behind the seeded eval (§5.2) before activation.
- **Self-modification creep** → the pipeline never writes its own active
  memory; drafting ≠ authority (§3). Same reason non-TTY promotion fails
  closed everywhere else in this codebase.
- **Fine-tuning temptation** → premature and impossible (vendor CLIs).
  The harness is the tunable surface. Revisit only if a local model ever
  takes over a leg (HEARTH Phase-2 local-analyzer path is the precedent).

---

## 7. Order of work

| # | Change | Depends on | Size |
|---|---|---|---|
| 1 | `oracle retro` pass 1: deterministic harvest over `oracle_builds/*` | nothing (state files exist today) | ~150 lines |
| 2 | Retro pass 2+3: Fable distillation → `LESSONS_DRAFT.md` → TTY promotion routing | 1 | ~200 lines |
| 3 | `BUILD_PROMPT` reads `.oracle_lessons`; review requests read `.oracle_lessons_review` | 2 | trivial |
| 4 | Hit tracking + retirement (recurrence predicates) | 2 | ~80 lines |
| 5 | Ledger scorecard fields + true-north metric | roadmap §2.4 ledger | ~60 lines |
| 6 | Seeded-defect build eval (regression gate for prompt/lesson edits) | none (skip-build mode exists) | corpus + runner |
| 7 | Post-merge fix capture into retro | roadmap §2.1 commit flow | ~60 lines |

Items 1–3 close the loop crudely (evidence → drafted → promoted → consumed).
Items 4–6 make it *trustworthy*. Item 7 upgrades the label quality to ground
truth. After that, the system doesn't just build platforms — every platform
it builds makes the next one cheaper, faster, and cleaner, with a human
signature on every rule it taught itself.
