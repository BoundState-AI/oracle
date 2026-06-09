# CLAUDE.md — boundstate_oracle

## What This Repo Is

ORACLE — Orchestrated Review And Compliance Liaison Engine. Standalone multi-oracle adversarial document review system with extensible compliance rule packs.

## Architecture

```
oracle/
├── cli.py               # Unified CLI entry point (7 commands)
├── oracle2.py            # Multi-oracle review engine (5 oracles, convergence loop)
├── oracle2_adapter.py    # Parses oracle2 output files → ReviewResult contract
├── pack_validator.py     # JSON Schema validation for all pack types
├── shall_extractor.py    # Obligation extraction from PDFs (regex + NLP)
├── build_far_rulepack.py # FAR/DFARS rule pack builder
├── build_gpcm_rulepack.py# GPCM (NASA tagged standards) pipeline
└── gpcm_rulepack_adapter.py # Enrichment and Sonnet vision repair
```

## Safety

All modules that touch compliance decisions have `__safety_critical__: bool = True`.

> The system SHALL NOT infer new regulatory interpretations. All outputs are draft artifacts pending responsible human review.

## Running

```bash
# CLI
oracle generate-pack regulation.pdf
oracle review document.md --packs nasa_std_6016c
oracle promote-pack nasa_std_6016c --reviewer "Dr. J. Wilde"
oracle list-packs

# As Python module
python -m oracle review document.md --packs pack1
```

## Environment Variables

| Variable | Required For |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Review (Beth, Sonnet) + generic extraction |
| `OPENAI_API_KEY` | Review (Fran, Codex) |
| `XAI_API_KEY` | Review (Grok) |

## Testing

```bash
pytest tests/ -v
```

## Key Rules

- Never modify oracle2.py through ORACLE — it's a black box
- All packs register as "draft" — human promotion required
- Non-TTY promotion fails closed (requires --yes)
- Token budget fails hard if compliance context can't fit

## Code Standards

General A-level standards (file headers, WHY comments, `<50`-line functions, Pydantic
`extra="forbid"`, no `print`, naming, no-`monkeypatch` testing, Tailwind) live in the
**`code-quality` skill** + global `CLAUDE.md` — not duplicated here. ORACLE-specific deltas:

- **Logger namespace:** `LOGGER = logging.getLogger("oracle.<module>")` (uppercase `LOGGER`).
- **Mark `__safety_critical__: bool = True`** on: compliance-obligation extractors
  (`shall_extractor`, pack builders), routing/grading deciders (`chat_engine`,
  `chat_grader`), `pack_validator`, review/compliance orchestrators (`oracle2`,
  `conductor`, engines), and remediation-language producers (`remediation_formatter`).
- Parser/rule-pack models that accept extensible input use `extra="allow"` **with a WHY
  comment** (everything at the API boundary stays `extra="forbid"`).
