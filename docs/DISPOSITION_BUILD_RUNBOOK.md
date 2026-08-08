# Disposition Module Build Runbook (v0.5.0 spec → `oracle/disposition/`)

**Status:** Ready to run (requires Joe's machine — grok + codex CLIs, ANTHROPIC_API_KEY)
**Spec:** `docs/ORACLE_DISPOSITION_SPEC.md` (v0.5.0, decision record applied)
**Target:** this repo, new subpackage `oracle/disposition/`, v1 scope per D-5

## Command

```sh
# from a clean tree on a fresh branch
git checkout -b build/disposition-v1
py pipeline/oracle_build.py docs/ORACLE_DISPOSITION_SPEC.md --repo . --fix-rounds 2 --coverage-floor 80
```

## What the pipeline will enforce

- **CHECK** each round: full `pytest tests -q` (auto-detected), diff coverage ≥ 80%
  of every line Ben adds, protected paths (`.oracle_protected` now covers the
  spec itself, the run records, and the disposition fixture — Ben cannot edit
  the contract, the history, or the regression corpus to get green).
- **Atlas** reviews against the spec; **Beth** gates with check evidence and
  cannot approve over red.

## What Ben must build (v1 scope, spec §14.9 / D-5)

Intake (§3), extraction extending `shall_extractor` with human boundary
confirmation (§7.3), authority report (§4), disposition matrix + proposals
(§5, §6, §8), §9.1 gates + §9.2 flags, countersign export (§12), scope-change
reopening (§3.2), fixture-driven tests per §15 (the 26 cases at
`tests/disposition/fixtures/oracle_eval_cs6030.json` become pytest
assertions — `expert_corrected`/`expert_discovered` regressions block,
`must_not_propose` cases assert OPEN), the §1.1 roll-up truth-table test, and
the spec-versus-fixture drift assertions (§15/§16). **Not in v1:** §11 deep
walking, §11.1 propagation, derived-SD minting, linker automation beyond
assisted suggestions.

## Notes

- The spec is ~50KB; with a full new subpackage the final-gate diff may
  approach the 200K strict cap — if the gate refuses on size, split the build
  into two spec-section runs (§3–§9 core, then §12+§15/§16 outputs+tests)
  rather than raising the cap.
- After APPROVED: run `/verify`-style manual smoke (CLI `oracle disposition`
  against the 6030 pack + a sample supplier doc), then commit; per the
  roadmap, commit-on-APPROVED automation is still a future pipeline item.
