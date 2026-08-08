# CLAUDE.md — boundstate_oracle

## What This Repo Is

**ORACLE** — Orchestrated Review And Compliance Liaison Engine. Three organs
cohabit:

- **Review engine** (`oracle/`) — multi-oracle adversarial document review to
  convergence with extensible compliance rule packs, pack generation from
  regulatory PDFs, and grounded pack chat. Spec: `docs/ORACLE_SPEC.md`.
- **Build pipeline** (`pipeline/`) — spec → build → deterministic CHECK →
  review → gate automation (Ben/Atlas/Beth ensemble). See `pipeline/README.md`.
- **Disposition module** (`oracle/disposition/`, under construction) —
  requirement-by-requirement standards disposition with traceable provenance.
  Contract: `docs/ORACLE_DISPOSITION_SPEC.md` (v0.5.0, protected — never
  edited by builds). Plan: `docs/DISPOSITION_SLICE_PLAN.md`. Operators read
  `docs/slices/OPERATOR_HANDOFF.md`.

HEARTH (buyer-side real-estate platform) was removed 2026-07-29; it lives in
git history before commit `28b807a` if ever needed.

## Commands

```bash
oracle review document.md --packs ...   # multi-oracle adversarial review
oracle generate-pack regulation.pdf     # build a rule pack from a standard
oracle list-packs
oracle promote-pack <pack> --reviewer ...
py pipeline/oracle_build.py <spec> --repo .   # gated build pipeline
```

Env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`,
`GEMINI_API_KEY` (review oracles + extraction). Reviewer model overrides:
`ORACLE_BETH_MODEL`, `ORACLE_FRAN_MODEL`, `ORACLE_CODEX_MODEL`,
`ORACLE_GROK_MODEL`, `ORACLE_GEMINI_MODEL`; pipeline builder pin:
`ORACLE_BEN_MODEL` / `--ben-model`.

## Key Rules

- `oracle2.py` is modifiable as of 2026-07-13 (Joe lifted the black-box rule)
  but treat it as load-bearing — change surgically, keep the env-var model
  overrides working, and run `pytest tests/` before shipping.
- All packs register as "draft" — human promotion required; non-TTY promotion
  fails closed (requires `--yes`); token budget fails hard if compliance
  context can't fit.
- **Protected files** (`.oracle_protected`): the disposition spec, run
  records (`docs/oracle_runs/*`), and the regression fixture
  (`tests/disposition/fixtures/*`) are never edited — by builds (the CHECK
  stage enforces it) or by anyone else. Spec defects route through the
  errata channel in the slice plan.
- The test suite's contract is **keyless determinism**: an autouse conftest
  fixture strips vendor keys inside tests; CI runs keyless. Red always means
  regression, never vendor outage.
- Golden consensus fixtures (`tests/golden/fixtures/*`): regenerate only
  deliberately and review the diff.

## Testing

```bash
pytest tests/ -v         # full repo; CI runs this with a coverage floor
```

## Code Standards

General A-level standards (file headers, WHY comments, `<50`-line functions,
Pydantic `extra="forbid"`, no `print` in library code, naming,
no-`monkeypatch` testing except env-var isolation, Tailwind) live in the
**`code-quality` skill** + global `CLAUDE.md`. Repo-specific deltas:

- **Logger namespace:** `LOGGER = logging.getLogger("oracle.<module>")`
  (uppercase `LOGGER`).
- Mark `__safety_critical__: bool = True` on compliance-obligation
  extractors, routing/grading deciders, `pack_validator`,
  review/compliance orchestrators, and remediation-language producers.
- Parser/rule-pack models that accept extensible input use `extra="allow"`
  **with a WHY comment** (everything at the API boundary stays
  `extra="forbid"`).
- Disposition module: advisory-only posture per spec D-1 — no
  safety-critical or compliance badge asserted until the §17 assurance case
  is approved by domain authority.
