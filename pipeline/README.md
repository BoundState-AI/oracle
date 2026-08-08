# Oracle Pipeline — multi-agent build & review tools

Standalone CLIs (no imports from the ORACLE app) that automate Joe's
manual oracle workflow for **code**. The spec-review sibling lives at
`D:\BoundState\oracle.py`.

| Tool | What it does |
|---|---|
| `oracle_review.py` | Parallel adversarial code review of a diff: Atlas (Codex `gpt-5.6-sol` medium / `--atlas terra-high`), Ben (Grok Build `-p`), Beth (Claude Fable). Beth synthesizes `MERGED_REVIEW.md` with SHIP / FIX FIRST / BLOCK. |
| `oracle_build.py`  | Full pipeline: polished spec → Ben (Grok Build, auto-approved) implements → deterministic CHECK (tests + diff coverage + protected paths) → Atlas (Codex terra-high) reviews → Ben fixes (`--fix-rounds`) → Beth (Fable, high effort) final gate: APPROVED / CHANGES REQUIRED / REJECTED → `PIPELINE_REPORT.md`. Red checks can never gate APPROVED. |
| `oracle_scaffold.py` | Pours the platform floor into a target repo before the first build: CI workflow with a 70% coverage floor, day-zero test, self-protecting `.oracle_protected` (the builder cannot edit CI or the protection file), `AGENTS.md` stub, `.gitignore`, minimal `pyproject.toml`. Idempotent; never overwrites existing files. |

## Deterministic layer (`oracle_build.py`)

Every round starts with a CHECK stage before any reviewer tokens are spent
(see `docs/LOOP_HARNESS_ASSESSMENT.md` §3 for the rationale):

- **Tests** — `--check-cmd` runs before each review round (default `auto`:
  `pytest tests -q` when a `tests/` dir exists, plain `pytest -q` when only a
  pytest config is present, skipped-with-warning when neither; `none`
  disables). Failures skip Atlas and go straight back to Ben as a fix round;
  the final check report is fed to Beth as gate evidence, and a gate over
  failing checks is clamped to CHANGES REQUIRED even if Beth says APPROVED.
  With auto-detection, pytest exit 5 (no tests collected) is a warning, not a
  failure; an explicit `--check-cmd` must exit 0.
- **Diff coverage** — `--coverage-floor N` (0 = off; 70–85 recommended for
  platform builds) measures the fraction of *added* executable product lines
  that the test run actually executes, via `pytest --cov` in the pipeline's
  interpreter (requires pytest-cov). New modules never imported by any test
  count as 0% covered. Legacy repo coverage never blocks a build — only the
  lines the build adds are gated — and coverage can't be inflated by deleting
  code or writing assertion-free tests (both are named gate offenses in the
  fix prompts). Uncovered line numbers are listed in the check report so Ben
  knows exactly what to test.
- **Protected paths** — globs from the spec's `## Never touch` section plus a
  `.oracle_protected` file at the target repo root (one glob per line, `#`
  comments). Any touched path matching a pattern fails the round with a named
  violation; Ben is instructed to revert, and the next round re-checks.
- **Platform floor** — every check report notes whether the target repo has
  CI workflows and a `tests/` directory (informational; Beth is instructed to
  treat their absence on a platform build as disqualifying). Run
  `oracle_scaffold.py` on new platforms so the floor exists before Ben's
  first line — generated platforms ship with CI/CD by construction, not by
  prompt.
- **`PIPELINE_STATE.md`** — a round-by-round record (build summary, check
  results, Atlas verdicts, Ben's fix/dismissal summaries) written into the
  artifact dir as the run progresses. It is appended to every review request —
  Atlas must rebut a stated dismissal reason instead of re-raising the same
  finding each round — and to the gate input.

## Usage

```sh
# Review the uncommitted changes in a repo
py pipeline/oracle_review.py --repo D:/BoundState/boundstate_mira

# Review a branch against main
py pipeline/oracle_review.py --repo D:/BoundState/boundstate_mira --base main

# Build a spec end-to-end (never commits/pushes; requires clean tree)
py pipeline/oracle_build.py FINAL_SPEC.md --repo D:/BoundState/some_repo
```

## Requirements

- `codex` CLI ≥ 0.144 (0.117 fails every model with "not supported with a
  ChatGPT account") — Atlas
- `grok` CLI (Grok Build) — Ben; `grok -p` is the headless mode
- `ANTHROPIC_API_KEY` — Beth/synthesis/gate on `claude-fable-5`; falls back to
  the user-level registry value when the process env is stale
- Codex/Grok legs bill to their subscriptions; only the Fable leg uses API credits

Artifacts land in `<target repo>/oracle_reviews/` and `<target repo>/oracle_builds/`
— add both to the target repo's `.gitignore`.

Grok Build runs with `--always-approve` in `oracle_build.py` (authorized by Joe
2026-07-13): unattended writes bounded to uncommitted changes in the target repo.

**Model pins:** Atlas is pinned by preset (`gpt-5.6-terra @ high` for builds),
Beth is pinned (`claude-fable-5`). Ben is pinned via `--ben-model` /
`ORACLE_BEN_MODEL` (unset = the grok CLI's own default). Every run records the
three legs' identities in `PIPELINE_STATE.md` ("Toolchain"), so the report
always says who built and who judged — an unpinned Ben is recorded as UNPINNED
rather than silently unknown. Note the spec-review engine (`oracle2`) is a
separate model roster: Fran/Codex are OpenAI (`gpt-5.6-terra`), Grok is
`grok-4.5`, and coordinator Beth defaults to `claude-opus-4-8` unless
`ORACLE_BETH_MODEL` overrides it.

## Web UI (local dev server)

When running `python server.py` + the Next frontend, the **Pipeline** tab in the
workspace lets you:

- Paste a polished spec
- Enter the target repo path
- **Be prompted for the save location** — the "Use this directory" button
  populates the output field with `<repo>/oracle_builds/<timestamp>`
  (exactly the default the CLI would choose). You can override freely.
- Watch live stage streaming (same events as CLI banners)
- Download PIPELINE_REPORT.md and logs from the chosen local dir

The same `run_pipeline(..., progress=...)` callable is used. No commits/pushes.
CLI remains the primary tool; the UI is convenience for watching in-browser.
