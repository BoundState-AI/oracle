# ORACLE — Orchestrated Review And Compliance Liaison Engine

Upload any document — spec, proposal, regulatory filing — and ORACLE runs it
through multi-oracle adversarial review to convergence against user-selected
rule packs. Upload a new regulatory standard and ORACLE generates a
structured rule pack from it, adds it to a persistent library, and makes it
available for all future reviews and grounded chat.

Three organs live in this repo:

| Organ | Where | What it does |
|---|---|---|
| Review engine | `oracle/` | Multi-oracle review (Beth coordinator + Fran/Codex/Grok/Gemini reviewers), pack generation (`shall_extractor` + rulepack builders), pack governance, grounded pack chat |
| Build pipeline | `pipeline/` | Spec → Ben (Grok) builds → deterministic CHECK (tests, diff coverage, protected paths) → Atlas (Codex) reviews → Beth (Fable) gates. See `pipeline/README.md` |
| Disposition module | `oracle/disposition/` | Requirement-by-requirement standards disposition with provenance (under construction — `docs/ORACLE_DISPOSITION_SPEC.md`, built slice-by-slice through the pipeline per `docs/DISPOSITION_SLICE_PLAN.md`) |

## Quickstart

```bash
pip install -e .

oracle review myspec.md --packs nasa_std_6030   # adversarial review
oracle generate-pack regulation.pdf              # standard → rule pack
oracle list-packs
oracle promote-pack <pack> --reviewer "Name"     # draft → reviewed (TTY only)
```

Web surface: `uvicorn server:app` (spec-review workspace, build-pipeline tab,
pack chat). Frontend in `frontend/` (Next.js).

## Configuration

API keys via environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`XAI_API_KEY`, `GEMINI_API_KEY`. Per-reviewer model overrides:
`ORACLE_BETH_MODEL`, `ORACLE_FRAN_MODEL`, `ORACLE_CODEX_MODEL`,
`ORACLE_GROK_MODEL`, `ORACLE_GEMINI_MODEL` (see `oracle/oracle2.py`).
Pipeline builder pin: `--ben-model` / `ORACLE_BEN_MODEL`.

## Testing

```bash
pytest tests/ -q
```

The suite is keyless-deterministic (vendor keys are stripped inside tests);
CI enforces a coverage floor, a server boot smoke, and a frontend build on
every push. Live-fire evaluation against real vendors (`eval/live/`) gates
releases, never CI.

## Repository notes

- `.oracle_protected` lists files no build pipeline run may modify.
- `docs/oracle_runs/` holds immutable review-run records.
- HEARTH (the buyer-side real-estate platform that once cohabited here) was
  removed 2026-07-29 and lives in git history before commit `28b807a`.
