# Oracle Pipeline — multi-agent build & review tools

Standalone CLIs (no imports from the ORACLE/HEARTH app) that automate Joe's
manual oracle workflow for **code**. The spec-review sibling lives at
`D:\BoundState\oracle.py`.

| Tool | What it does |
|---|---|
| `oracle_review.py` | Parallel adversarial code review of a diff: Atlas (Codex `gpt-5.6-sol` medium / `--atlas terra-high`), Ben (Grok Build `-p`), Beth (Claude Fable). Beth synthesizes `MERGED_REVIEW.md` with SHIP / FIX FIRST / BLOCK. |
| `oracle_build.py`  | Full pipeline: polished spec → Ben (Grok Build, auto-approved) implements → Atlas (Codex terra-high) reviews → Ben fixes (`--fix-rounds`) → Beth (Fable, high effort) final gate: APPROVED / CHANGES REQUIRED / REJECTED → `PIPELINE_REPORT.md`. |

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
