# BoundState Python Header Convention

**Status:** Active
**Effective:** 2026-04-10
**Owner:** Dr. Joseph Wilde / Beth (Claude Opus 4.6)
**Applies to:** All BoundState-AI Python repositories

---

## 1. Purpose

All Python modules in BoundState-owned repositories carry a standardized header that establishes authorship, version, and classification. This document captures the convention, the current audit state (as of 2026-04-10), and the backfill plan for bringing the rest of the codebase into compliance.

The trigger for writing this down was discovering that the `mira/forge_claude/authority/` module — including [pack_gen.py](../../mira/forge_claude/authority/pack_gen.py) and [human_gate.py](../../mira/forge_claude/authority/human_gate.py) — had been written without the standard header, while sibling modules like [mira/compliance/conductor.py](../../mira/compliance/conductor.py) and [mira/pipeline/pipeline.py](../../mira/pipeline/pipeline.py) carry it correctly. The convention had drifted; this doc re-establishes it.

---

## 2. Canonical Header

```python
#!/usr/bin/env python3
"""
Module: <short name>
Purpose: <one-line purpose statement>

BoundState AI 2026
Version: <x.y.z>
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""
```

### Field rules

| Field | Rule |
|---|---|
| Shebang | `#!/usr/bin/env python3` on line 1 |
| Module | Short human-readable name (usually matches filename) |
| Purpose | Preserve any existing module docstring as this line — do not overwrite |
| Year | Current calendar year (`BoundState AI 2026`) |
| Version | `1.0.0` for new files; preserve existing versions |
| Classification | Always `BoundState Proprietary` unless the file is explicitly OSS |
| Co-Authors | Only list contributors who actually touched the file. **Do NOT fabricate.** |
| Compliance | Optional line (e.g., `Compliance: NASA-STD-8739.8B, SWE-013`). Only include when the file genuinely implements a compliance requirement. **Do NOT fabricate compliance claims.** |

### Scope by file type

| File type | Header style |
|---|---|
| Production Python modules (`mira/`, `oracle/`, `forge/`, `sentinel/`, etc.) | **Full header** |
| Test files (`tests/`, `test_*.py`) | **Lightweight:** `"""Tests for <module>. BoundState AI 2026."""` |
| One-off scripts (`scripts/`) | **Lightweight** one-liner with year attribution |
| Empty `__init__.py` stubs | **Leave empty** — a banner on an empty namespace marker is noise |
| Vendored / third-party code (`plugins/`) | **Skip** — do not modify upstream-sourced files |
| Auto-generated code | **Skip** — let the generator rebuild |

---

## 3. Audit Results — 2026-04-10

Scan run from `D:\mira-main` working copy against all Python files under these roots: `mira/`, `common/`, `core/`, `services/`, `athena/`, `sentinel/`, `sentinel-main/`, `govlaw-main/`, `scripts/`, `tests/`, `plugins/`, `miul_codex/`, `mira_v4/`, `data_laundering/`.

Detection: first 2000 bytes of each file must contain both the strings `BoundState AI` and `Classification:`.

### Summary

| Category | Count | % |
|---|---|---|
| Has BoundState header | 613 | 51% |
| **Missing header** | **572** | **48%** |
| Empty files | 11 | 1% |
| **Total tracked** | **1,196** | 100% |

### Missing by top-level root

| Root | Missing | Has | Disposition |
|---|---|---|---|
| `mira/` | 205 | 350 | Primary target for backfill |
| `govlaw-main/` | 117 | 0 | Nested directory; belongs to `BoundState-AI/govlaw` — handle from separate clone |
| `scripts/` | 103 | 4 | Lightweight headers |
| `tests/` | 100 | 74 | Lightweight headers |
| `sentinel-main/` | 36 | 0 | Nested directory; belongs to `BoundState-AI/sentinel` — handle from separate clone |
| `sentinel/` | 7 | 23 | Short cleanup |
| `common/` | 3 | 0 | Short cleanup |
| `plugins/` | 1 | 0 | Verify not vendored before touching |

### Missing in `mira/` by subpackage

| Subpackage | Missing | Notes |
|---|---|---|
| `mira/mua` | 61 | Predates convention entirely (0 headers present) |
| `mira/forge_claude` | 54 | **Triggered this audit** — contains authority/, scaffolder/, introspector/ |
| `mira/api` | 20 | Routers and auth middleware |
| `mira/pipeline` | 13 | GPTL stages |
| `mira/bsmh` | 9 | |
| `mira/miul` | 9 | |
| `mira/forge` | 7 | |
| `mira/mp_plan` | 6 | |
| `mira/fracture` | 5 | |
| `mira/oca` | 5 | |
| `mira/galvanic` | 4 | |
| `mira/h2` | 3 | |
| `mira/query` | 3 | |
| `mira/chat` | 2 | |
| `mira/guidance` | 2 | |
| `mira/providers` | 1 | |
| `mira/utils` | 1 | |

---

## 4. Backfill Plan

**Execute from primary workstation, not travel laptop.** The audit and this document were produced on the LG Gram travel machine; mass-editing 572 files across multiple repos should happen on the main dev box where full test suites can run.

### Phase 1 — `mira/` production code

- **Target:** `mira/` package only (205 files)
- **Priority order:**
  1. `mira/forge_claude/authority/` (5 files — the trigger for this audit)
  2. `mira/api/` (20)
  3. `mira/pipeline/` (13)
  4. `mira/chat/` (2) and `mira/compliance/` (already clean, spot-check)
  5. `mira/forge/`, `mira/forge_claude/` remainder (~56)
  6. `mira/mua/` (61 — largest single block)
  7. Remaining subpackages
- **Commit to:** `BoundState-AI/mira` (origin)
- **Style:** Full header

### Phase 2 — Support files

- **Target:** `common/` (3), `plugins/` (1 — verify not vendored), `sentinel/` (7)
- **Commit to:** `BoundState-AI/mira` (origin)
- **Style:** Full header

### Phase 3 — Tests and scripts

- **Target:** `tests/` (100), `scripts/` (103)
- **Commit to:** `BoundState-AI/mira` (origin)
- **Style:** Lightweight one-liner

### Phase 4 — Nested foreign repos (separate clones required)

`govlaw-main/` (117 files) and `sentinel-main/` (36 files) exist as nested directories inside the `mira-main` working copy but actually belong to separate GitHub repos:
- `govlaw-main/` → `BoundState-AI/govlaw`
- `sentinel-main/` → `BoundState-AI/sentinel`

These **must not** be committed through `mira-main`. They must be handled from fresh clones of the owning repos to avoid pushing content to the wrong remote or creating cross-repo drift. See [BOUNDARIES.md](../../BOUNDARIES.md) for repo ownership rules.

### Effort estimate

| Phase | Files | Per-file time | Total |
|---|---|---|---|
| 1 (`mira/`) | 205 | ~30s scripted | ~2 hours |
| 2 (common/plugins/sentinel) | 11 | ~30s scripted | ~5 min |
| 3 (tests/scripts lightweight) | 203 | ~10s template fill | ~30 min |
| 4 (nested repos, separate clones) | 153 | ~30s + clone overhead | ~1.5 hours |
| **Total if scripted** | **572** | | **~4 hours** |

---

## 5. Automation Notes

The backfill should be scripted, not hand-edited. A safe backfill script must:

1. **Parse existing module docstring** (if any) and preserve its content as the `Purpose:` line
2. **Insert the full header above** the existing docstring (or replace the existing docstring if it is purely boilerplate)
3. **Detect existing headers** and skip files that already have `BoundState AI` + `Classification:` in the first 2000 bytes
4. **Skip empty `__init__.py` files**
5. **Skip vendored code** — check for `# generated by`, `# vendored from`, or presence in a `plugins/` or `third_party/` directory
6. **Preserve shebangs** — if a file already has `#!/usr/bin/env python3`, don't duplicate it
7. **Commit per phase** — one atomic commit per phase (not per file), with `git status` verification before and after
8. **Run pytest before and after** — a header backfill should not change any test outcome; if it does, the script has a bug

---

## 6. Anti-Patterns to Avoid

- **Do NOT fabricate co-authors.** If Fran (GPT-5), Grok, or any other contributor didn't actually touch a file, don't list them. Co-author lines are audit trails, not decoration.
- **Do NOT fabricate compliance claims.** `NASA-STD-8739.8B` and `SWE-013/033` only belong on files that genuinely implement software assurance requirements. A rogue compliance claim on a utility file is worse than no claim.
- **Do NOT backfill headers into vendored third-party code.** Check `plugins/` carefully — if a file came from upstream (e.g., Clerk SDK stubs), leave it alone.
- **Do NOT overwrite existing module docstrings.** The existing docstring usually explains *what the file does*; that content goes in the `Purpose:` line, not into the bitbucket.
- **Do NOT push to the `mira-dev` remote.** Per Dr. Wilde as of 2026-04-10, the `mira-dev` remote is inactive. Push production changes to `origin` (which resolves to `BoundState-AI/mira`).
- **Do NOT mass-edit from a travel laptop.** Header backfills should run on a machine with the full test suite available.

---

## 7. Enforcement

Once Phase 1–3 backfill is complete, add a pre-commit hook or CI check that:

1. Runs on every PR touching `*.py` files
2. Verifies any new or modified Python file has the canonical header
3. Fails the PR with a clear error pointing to this document if the header is missing

This prevents the convention from drifting again.

---

*This document was generated as part of the 2026-04-10 header audit. The audit itself was a non-destructive scan run from the `mira-main` working copy on the LG Gram travel machine. No files were modified as part of producing this document.*
