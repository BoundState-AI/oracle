# BUILD_NOTES — HEARTH Phase 1 (founder build, spec v0.3 §12)

Build date: 2026-06-11 · Builder: Claude (Claude Code session), directed by the
Phase-1 handoff (`docs/HEARTH_phase1_handoff.md`) against spec v0.3
(`docs/HEARTH_spec_v0.3.md`). All four gates green: **69 HEARTH tests, 273
repo-wide (ORACLE suite untouched and passing).**

---

## 1. What exists

### P1-A — repo skeleton + models (§1, §2, §11)
- `hearth/` package per the §1 tree. Phase-≥2 organs (`core/valuation`,
  `core/signals`, `core/optimizer`, `core/fit`, `core/identity`, `db`,
  `ingest`, `packs/buyer`, `skills/`) are header-only skeletons that state
  their phase and constraints — imports are stable, nothing pretends to work.
- Pydantic v2 contracts in `hearth/data/`: `BuyerPack`, `JurisdictionPack` +
  `MicroRule`, `PropertyIdentity`, `PropertyEvidence`, `ScrubFinding`,
  `AuditArtifact`. All `extra="forbid"`; JSON→model→JSON proven lossless
  (`tests/hearth/test_models_roundtrip.py`).
- Every module carries the BoundState header with `Safety Critical:` and
  `Financially Critical:` fields plus `__safety_critical__` /
  `__financially_critical__` dunders.
- FastAPI app with `/health` only; a test fails if any other route appears.

### P1-B — DocScrubber CLI, findings-only (§2.5, §3.3, §11)
- `hearth scrub <file> --pack CO-Larimer [--target-price N] [--json P]
  [--audit-dir D]`; also `python -m hearth ...`.
- Pipeline: fail-closed extraction (`.txt/.md/.pdf/.docx`; PyMuPDF /
  python-docx, lazily imported) → clause segmentation keyed on section
  numbers (¶-paragraph fallback) → deterministic micro-rule matcher (rules
  are data; named regex captures feed exposure math) → `ScrubFinding`s.
- **Fails CLOSED everywhere**: missing/empty/undecodable/garbage/unsupported
  documents, packs with no executable or no effective rules, malformed rule
  specs, exploding analyzer, unwritable audit dir — all converge to a single
  `refuse` finding (category `integrity`, basis `hearth.fail_closed`) and
  exit code 2. Tests were written before the feature (handoff rule 2) —
  `tests/hearth/test_scrubber_fails_closed.py`.
- Grey Rock golden test green: fee/warn (§7, pre-filled 3%), scope/flag
  (§2, region-wide), backstop/flag (§7.3, `exposure_usd = 21000` at
  `--target-price 700000`), default_trap/flag (§8, fee survives default).
  The §12 minimum-findings assertions are deliberately independent of the
  golden file so regenerating the golden cannot weaken the gate.
- Every run — refusals included — writes an immutable `AuditArtifact`
  (create-only file, self content-hash, verification + tamper tests).

### P1-C — CO-Larimer pack skeleton (§2.2)
- 12 micro-rules, all `status: provisional`, `authority_review: null`,
  stub-signed, real source citations:
  - 4 × BDB24-6-24: fee negotiability, scope breadth, buyer backstop
    (exposure = fee% × target price), default survival.
  - 4 × CREC CBS §3.1 deadlines (inspection objection, inspection
    resolution, appraisal, loan availability), payload = `lever` +
    `risk_if_waived`, with clause_regex detections that fire on CBS-style
    documents.
  - 4 × landmines as **data_query detection specs only** (metro-district
    mills warn ≥45 / flag ≥60, radon Zone 1 norm, wildfire-insurance
    check, ECMC 2,000-ft well-radius query). Adapters intentionally NOT
    built (§12).
- Pack validates against the §2.2 model, round-trips losslessly, and every
  rule's signature is verified at load; tampering or a malformed regex makes
  the pack unusable (refusal), never quieter.
- Provisional banner proven at the renderer AND the real CLI surface.

### P1-D — boundary-test scaffold (§1.1, §6)
- `hearth/core/boundary.py`: canary collection + `find_leaks()` — the
  testable definition of BuyerPack exfiltration; this same primitive becomes
  the §3.4 disclosure leak check later.
- Static scan: zero outbound-capable imports (stdlib or third-party,
  function-level included) anywhere in `hearth/`; allowlist exists, is
  empty, and growing it requires review.
- Runtime canary (fixture #2 `tests/fixtures/buyerpack_canary.json`): full
  P1 workload runs under a mocked socket layer + log capture + filesystem
  watch with a sentinel-valued BuyerPack in memory; zero canaries may appear
  anywhere.
- **Red-on-leak proven two ways**: (1) meta-tests leak deliberately through
  each channel (log, network, file) and assert the detectors fire; (2) local
  branch `demo/deliberate-leak` commits two leaks into product code
  (BuyerPack dump logged in `HearthModel.to_json_dict`; `import httpx` in
  `hearth/utils/render.py`) — observed result:
  `test_phase1_workflows_leak_no_canary` FAILED,
  `test_no_outbound_capable_imports_anywhere_in_hearth` FAILED,
  2 failed / 67 passed. Main stays green.

---

## 2. What is stubbed (all honest stubs, none load-bearing lies)

| Stub | Where | Real version blocked on |
|------|-------|------------------------|
| `ClauseAnalyzer` LLM stage | `NullClauseAnalyzer` returns `[]` | Phase-2 local-model analyzer; boundary tests already gate it |
| Rule signatures | HMAC with a **public** key, `STUB1:` prefix — drift detection, not authenticity | Per-reviewer key management (pre-production blocker) |
| `model_hash` / `prompt_hash` in AuditArtifact | Constants `P1-STUB:no-{model,prompt}-in-deterministic-pipeline` | Existence of a model/prompt (§12 allows stub constants) |
| Phase-≥2 organs | header-only packages | their build phases (§10 build order) |
| Landmine adapters | detection specs as pack data | ingest adapters + data-rights matrix rows (§4.1) |
| FastAPI surface | `/health` only | later phases |

## 3. Deviations from spec (every one, with why)

1. **`integrity` added to the §2.5 category enum.** Fail-closed refusals
   (§3.3/§12) need a category and none of the six document categories means
   "could not analyze". Refusals use `category=integrity`,
   `jurisdiction_basis=hearth.fail_closed`.
2. **Per-rule `status` field added to §2.2 `MicroRule`.** The spec shows
   `status` only in governance, but §2.2's auto-invalidation ("dependent
   rules flip to provisional") and §12 P1-C ("all rules `status:
   provisional`") both require rule-level status. `reviewed` requires a
   named `authority_review` (validator-enforced).
3. **Type widening for losslessness:** `PropertyEvidence.value` is
   `int|float|str` (spec: `float|str`); `SoftPreference.target` is
   `bool|int|float|str`. JSON distinguishes 600 from 600.0; the P1-A
   lossless gate forces the honest union.
4. **`requires_human_review` is `Literal[True]` on every finding**, not just
   template output — strictly more conservative than §2.5.
5. **Exposure needs `--target-price`.** "Configured target price" (§12) is a
   CLI flag with no default; without it `exposure_usd` is `None`, never a
   fabricated number (§6 "no advice past the data").
6. **Grey Rock fixture is SYNTHETIC** (filename-marked), reconstructed from
   spec §2.5/§12 clause content per handoff rule 3 — the real document was
   not provided. Swap in the real text later; the golden file regenerates
   with `HEARTH_UPDATE_GOLDEN=1`.
7. **§8 vs §12 conflict (logged per §12 for v0.4):** §8 says provisional
   rules "cannot solely drive user-shown flag/refuse"; the P1 golden test
   requires flag findings from an all-provisional pack. §12 founder mode
   wins for Phase 1 (single self-represented user, provisional banner on
   everything). **For any non-founder user this becomes a hard gate again.**
8. **P1-B ⊂ P1-C ordering:** P1-B's ACCEPT needs the 4 BDB rules, so a
   4-rule pack shipped inside P1-B and P1-C expanded it to 12. Gates were
   still run strictly in order.
9. **Repo layout:** spec §1 draws `hearth/` as the repo root; this repo is a
   clone of `oracle` (as commissioned), so `hearth/` is a top-level package
   beside `oracle/`, and `data/`, `db/`, `ingest/` etc. live inside it.
10. **Python 3.11/3.12:** spec says 3.12; built and tested on 3.11, CI
    matrix runs both, no 3.12-only features used.
11. **Run-date injection:** `scrub_document(..., run_date=...)` exists so
    effective-window behavior is testable; CLI always uses today.

## 4. Scope-creep watch (handoff rule 4)

Nothing out of scope was built: no valuation, no MLS/portal adapters, no LLM
calls, no UI beyond the CLI, no DB. Nothing out of scope was found necessary.

## 5. Top 3 recommended next steps for Phase 2

1. **PropertyIdentity + PropertyEvidence ingest for Larimer** (build order
   §10 step 2): assessor + permit adapters behind explicit §4.1 data-rights
   rows, `property_uid`-keyed store with match-confidence joins. This is the
   highest-leverage step because the four landmine rules already ship
   executable *thresholds as data* — the moment evidence rows exist, metro
   mills / radon / wildfire / ECMC alerts light up without touching the pack
   format. Boundary rule: adapters live outside `hearth/`'s no-network
   invariant only via an explicit, reviewed allowlist entry + runtime
   boundary test.
2. **Real signing + governance loop for JurisdictionPacks:** per-reviewer
   keys (Ed25519), signature verification in `load_pack` swaps from stub to
   real with the same fail-closed contract, and a monitored-sources watcher
   that flips dependent rules to provisional on form/statute changes (§2.2
   auto-invalidation). Audit artifacts already pin pack hashes, so rollback
   and diff procedures (§11) can be built on what exists.
3. **Local-model ClauseAnalyzer behind the existing protocol** for novel
   documents (findings-only, every finding still citing a motivating
   rule_id, §3.3). The protocol, the findings-only enforcement, and the
   boundary tests are already in place — a third-party-API analyzer
   physically cannot ship without turning CI red. Gate any template output
   on the §9 #3 counsel opinion, which remains the blocking item it was.

*(Runner-up: the valuation engine should not start until its backtest
harness exists — §3.1's calibrated-interval promise is unfalsifiable
without it.)*
