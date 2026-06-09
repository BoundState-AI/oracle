# CLAUDE.md — boundstate_oracle

## What This Repo Is

ORACLE — Orchestrated Review And Compliance Liaison Engine. Standalone multi-oracle adversarial document review system with extensible compliance rule packs.

## Architecture

```
oracle/
├── cli.py               # Unified CLI entry point (7 commands)
├── oracle2.py            # Multi-oracle review engine (6 oracles, convergence loop)
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
| `GEMINI_API_KEY` | Review (Gemini; `GOOGLE_API_KEY` also accepted) |

## Testing

```bash
pytest tests/ -v
```

## Key Rules

- Never modify oracle2.py through ORACLE — it's a black box
- All packs register as "draft" — human promotion required
- Non-TTY promotion fails closed (requires --yes)
- Token budget fails hard if compliance context can't fit

## Tier-One Code Standards (Enforced on ALL New Code)

Every file in this repo must meet BoundState A-level engineering standards. These are non-negotiable for new code and modifications.

### File Headers (Python)
Every .py file MUST have this header format:
```python
"""
Module: [module name]
Purpose: [one-line WHY this module exists]

BoundState AI 2026
Classification: BoundState Proprietary

[If compliance-affecting: __safety_critical__: bool = True]
[Optional: Spec: BS-SPEC-ORACLE-001, Section X.Y]
"""

__safety_critical__: bool = True  # if applicable
```

### File Headers (TypeScript/React)
Every .ts/.tsx file MUST have a JSDoc module comment:
```tsx
/**
 * [Component/Module name] — [what it does in one line].
 * [Optional: WHY this exists as a separate module.]
 */
```

### Safety-Critical Marker
Add `__safety_critical__: bool = True` to any module that:
- Extracts compliance obligations (shall_extractor, pack builders)
- Makes routing/grading decisions (chat_engine, chat_grader)
- Validates compliance packs (pack_validator)
- Orchestrates review or compliance checks (oracle2, conductor, engines)
- Produces remediation language (remediation_formatter)

### WHY Comments (Non-Negotiable)
- Every regex pattern: WHY this pattern, what it detects, known false positive/negative risks
- Every magic number/threshold: WHY this value, what happens if changed
- Every architectural decision: WHY this approach was chosen over alternatives
- Every security decision: WHY this is safe, what threat it mitigates

### Composability
- Functions MUST be under 50 lines. If over, decompose into named helpers.
- "Can I explain this file's purpose in one sentence without 'and'?" — if not, split it.

### Pydantic Models
- All API boundary models: `model_config = ConfigDict(extra="forbid")`
- Parser/rule-pack models that accept extensible input: `extra="allow"` WITH a WHY comment

### Logging
- Use `LOGGER = logging.getLogger("oracle.[module]")` — always uppercase
- No `print()` in production code (CLI `main()` entry points are acceptable)

### Naming
- Python: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for constants
- TypeScript: `camelCase` for functions/variables, `PascalCase` for components/types
- Logger: always `LOGGER` (uppercase)

### Testing
- Every test file MUST have a module-level docstring: `"""Tests for [what this suite validates]."""`
- Test function names must be descriptive: `test_[what]_[condition]_[expected]`
- No `monkeypatch` unless mocking external APIs (use protocol mocks or fixtures)

### Frontend
- Tailwind for all styling — no inline `style={{ }}` attributes
- Trust boundary comments on any API proxy or auth middleware
- Component types exported when shared across files — no type duplication
