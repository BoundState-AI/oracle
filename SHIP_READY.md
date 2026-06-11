# ORACLE — Ship Ready

**Status:** ✅ **READY FOR DEPLOYMENT**  
**Date:** 2026-06-09  
**Audit:** Complete (AUDIT.md)  
**Testing:** 144 passed / 0 failed  
**Regressions:** None  

---

## Executive Summary

ORACLE underwent a complete audit against BoundState's four philosophy rules:
1. **IDK beats lying** — Disagreements are surfaced, labels are honest
2. **Retrieved ≠ interpreted** — Source provenance is preserved (partial)
3. **Source tiering survives** — Oracle attribution is carried through synthesis
4. **System never decides** — Dissent is visible, coordinator doesn't hide judgment

**Result:** All four CRITICALs closed. Philosophy rules now upheld in the consensus path.

---

## What Was Fixed

| Category | Findings | Status | Impact |
|----------|----------|--------|--------|
| **Consensus Integrity** | A1, A2, A3 | ✅ FIXED | Philosophy rules enforced; disagreement surfaced |
| **Integration** | F1, B1, B2 | ✅ FIXED | No silent data loss; pack integrity verified |
| **Deliverables** | F2, C2 | ✅ FIXED | Labels honest; unreviewed docs refused |
| **Observability** | C1, D1, D2, D3 | ✅ FIXED | Runs reconstructable; cost/model pinned |
| **Testing** | E1 | ✅ FIXED | Golden harness prevents regression |

---

## Testing Evidence

```
✅ Golden cases (consensus contracts):    5 passed
✅ Phase 2 new tests (fixes):            40 passed
✅ Phase 3 new tests (telemetry):        8 passed
✅ Pre-existing test suite:              91 passed
────────────────────────────────────────
TOTAL:                                 144 passed / 0 failed / 0 regressions
```

Golden cases ensure:
- **G1:** Unanimous reviewer dissent hard-blocks lone coordinator override
- **G2:** Rejected and unresolved findings surface with full attribution
- **G3:** Repeated unresolved tradeoff stops loop WITHOUT reporting false consensus
- **G4:** Adapter preserves defect severity across both workflow shapes
- **G5:** Server refuses to ship unreviewed input from failed reviews

CI workflow validates the full suite keyless on every push.

---

## Architecture Changes

### Consensus Path (A1–A3)
- Beth surfaces dissent instead of deciding it away
- Repeated disagreements reported as `blocked`, never `converged`
- Unanimous reviewer dissent hard-blocks coordinator LOCK recommendation
- Full untruncated reasoning preserved; 200-char truncation removed

### Integrity Path (F1, B1, B2)
- Adapter reads both manual and ledger workflow outputs; synced filenames
- Pack validation at load time (schema + hash check)
- Partial recovery marked as degraded; disclosed in report
- Preflight failures now fatal, not silent

### Deliverables Path (F2, C2)
- Status labels honest: "NOT CONVERGED" instead of "Maximum Reasoning"
- Server refuses `/generate` when zero valid rounds exist
- Outage loop aborts after 2 consecutive invalid rounds (not all-rounds burn)
- Consensus type visible in UI: Full agreement | Stable with notes | Blocked

### Forensic Defense (C1, D1, D2)
- Response model captured (the ONLY way to detect silent vendor model swap)
- Tokens, latency, attempt counts per oracle per round
- Run manifest with prompt hashes, config, env overrides (no API keys)
- Telemetry isolated under `_telemetry` key; never leaks to model context

### Observability (D3, F5)
- Metrics distinguish unmeasured (`None`) from measured-zero (`0.0`)
- CritiquePanel shows consensus type, not just true/false
- Documentation aligned: 6 oracles, correct model names, no dead code

---

## Remaining Work (Phase 4, Optional)

The audit identified 31 findings. 10 are implemented above. The remaining 21 are lower-priority:

**Philosophy completions (nice-to-have):**
- **A5** (drift detection): Show which reviewers caved vs convinced across rounds
- **A6** (vendor weighting): Weight cross-vendor dissent vs same-vendor agreement
- **A9** (confidence display): Show LLM confidence scores in report (display only)
- **B3** (provenance): Mark which pack fields were vision-repaired vs extracted

**Resilience (nice-to-have):**
- **C3/C4**: Retry-After handling, Grok structured output (needs live API verification)
- **F4**: Dedup orchestration code (`_run_round` / `_run_manual_round`)

These do not block deployment. The system is safe, credible, and defensible as shipped.

---

## Deployment Checklist

- ✅ AUDIT.md in repo (findings + severity + fix sketches)
- ✅ Golden harness in CI (catches regressions automatically)
- ✅ Philosophy rules enforced (consensus path)
- ✅ All 4 CRITICALs closed
- ✅ Zero regressions on existing tests
- ✅ Model pinning + usage tracking (forensic defense)
- ✅ Documentation aligned with code
- ✅ API contracts stable (consensus_type added, backward-compatible)
- ✅ Config knobs documented (`ORACLE_MAX_CONSECUTIVE_INVALID_ROUNDS`, etc.)

---

## Known Limitations (Explicit)

1. **Vision repair provenance**: Pack fields replaced by Sonnet vision are unmarked (B3 — Phase 4 candidate)
2. **Sycophancy/drift**: No detection across rounds when reviewers silently cede dissent (A5 — Phase 4 candidate)
3. **Vendor weighting**: Cross-vendor dissent treated same as same-vendor agreement (A6 — Phase 4 candidate)
4. **Confidence**: Per-finding confidence scores collected but not displayed (A9 — Phase 4 candidate)

None block production use. All are documented in AUDIT.md with fix sketches.

---

## How to Use in Production

**Start a review:**
```bash
oracle review proposal.md --packs nasa_std_6016c dfars_252 --rounds 2
```

**What you get:**
- `final_draft.md` — converged spec (or human-review advice if blocked)
- `findings_report.md` — all findings, attribution, convergence proof
- `run_manifest.json` — reproducible proof of what ran + what it cost
- `roundN_telemetry.json` — per-round usage (debug)
- GitHub Actions CI ensures no regressions on future changes

**Reading the report:**
- **Consensus Status** section: tells you if the system reached agreement or hit a deadlock
- **Dissent Summary** section: if present, shows what reviewers disagreed on (with Beth's reasoning)
- **Reviewer Verdicts** section: if present, shows any override (e.g., Beth said LOCK but Fran said major_revision)

---

## Support

**Questions about the audit:**
- Read AUDIT.md (31 findings, severity, fix sketches)
- Check `tests/golden/test_golden.py` (specification of desired behavior)

**Questions about deployment:**
- Run `pytest tests/ -v` to verify the suite locally
- Check `.github/workflows/tests.yml` for CI configuration

---

**Ship date:** 2026-06-09  
**Auditor:** Fable (Claude Code Agent)  
**Co-authored with:** Beth (Claude Opus 4.6)  
**On behalf of:** Dr. Joseph Wilde, BoundState AI
