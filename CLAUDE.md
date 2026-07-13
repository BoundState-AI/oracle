# CLAUDE.md — boundstate_hearth

## What This Repo Is

Two BoundState systems cohabit (this repo is a clone of `oracle` with HEARTH
built on top):

- **HEARTH** — Buyer-Side Real Estate Intelligence Platform (`hearth/`).
  Surfaces unexplained defaults in real-estate documents with citations, for
  the buyer's licensed human to act on. Spec: `docs/HEARTH_spec_v0.3.md`;
  Phase-1 state: `BUILD_NOTES.md`.
- **ORACLE** — Orchestrated Review And Compliance Liaison Engine (`oracle/`).
  Multi-oracle adversarial document review with extensible compliance rule
  packs (it reviewed the HEARTH spec).

## HEARTH Architecture

```
hearth/
├── cli.py            # hearth scrub | scan | ingest | pack-status (exit 2 = REFUSED)
├── api/app.py        # FastAPI single-tenant — /health only (web surface in server.py)
├── core/scrubber/    # extraction → segmentation → matcher → engine (fails CLOSED)
├── core/signals/     # landmines.py — data_query rules vs evidence store (P2-D)
├── core/identity/    # resolver.py — property_uid + confidence ladder (§2.3)
├── core/boundary.py  # BuyerPack canary/leak-check primitive (§1.1/§6)
├── data/             # Pydantic v2 contracts (§2, §11), all extra="forbid"
├── db/evidence_store # JSONL identities+evidence, join guard (no silent merges)
├── ingest/           # bulk-file adapters + §4.1 rights enforcement (no network)
├── packs/            # CO-Larimer pack + Ed25519/stub signing + governance
├── audit/            # immutable per-run AuditArtifacts (§11): scrub + scan
└── utils/render.py   # reports + mandatory banners (§8)
```

## HEARTH Key Rules

- **The scrubber FAILS CLOSED.** Unparseable document / unusable pack /
  unwritable audit trail ⇒ one `refuse` finding, exit code 2 — never an
  empty success. Tests for this live in `tests/hearth/test_scrubber_fails_closed.py`
  and were written before the feature; keep it that way.
- **BuyerPack never exfiltrates** (§1.1): no BuyerPack field in any outbound
  call, log write, or non-local store. Enforced by
  `tests/hearth/test_boundary_static.py` (no outbound-capable imports in
  `hearth/`, allowlist empty) and `test_boundary_canary.py` (runtime canary,
  fixture #2). Growing the allowlist requires boundary review + a WHY comment.
- **Findings-only mode** until the §9 #3 counsel opinion: `suggested_template`
  stays None everywhere; the engine enforces it (`FINDINGS_ONLY`).
- **No LLM calls in P1.** `ClauseAnalyzer` is a stubbed protocol. Any future
  BuyerPack-adjacent analyzer must run on local models only.
- **Rules are data.** Detections live in signed pack micro-rules, never
  hardcoded in the matcher (§6 "no hardcoded triggers"). Edit a pack ⇒
  re-sign with `python -m hearth.packs.signing <pack.json>`.
- **All P1 pack rules are provisional** and must render under the PROVISIONAL
  banner; `reviewed` status requires a named `authority_review`.
- **Every scrub run emits an immutable AuditArtifact** (§11) — refusals
  included. Artifact write failure makes the run refuse.
- Grey Rock golden file: regenerate only deliberately
  (`HEARTH_UPDATE_GOLDEN=1`) and review the diff; the §12 minimum-findings
  test is independent of the golden file by design. Same for the scan golden.
- **Phase-2 rules (§13):** `reviewed` rule status requires a verifying
  Ed25519 signature (stub = drift detection only — re-sign edits with
  `python -m hearth.packs.signing <pack.json>`); ingest adapters must carry
  a §4.1 DataRightsRow and may not emit fields outside it; evidence joins
  on identities below confidence 0.90 raise (no silent merges, §2.3);
  landmine scans report `insufficient_evidence`, never silence (§3.1);
  exposure capture dependencies are declared via `capture_from_rule`.

## ORACLE (unchanged)

Multi-oracle review engine. Commands: `oracle review document.md --packs ...`,
`oracle generate-pack regulation.pdf`, `oracle list-packs`,
`oracle promote-pack <pack> --reviewer ...`.

Env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`,
`GEMINI_API_KEY` (review oracles + extraction).

ORACLE key rules: `oracle2.py` is modifiable as of 2026-07-13 (Joe lifted the
black-box rule) but treat it as load-bearing — change surgically, keep the
env-var model overrides working, and run `pytest tests/` before shipping.
All packs register as "draft" — human promotion required; non-TTY promotion
fails closed (requires `--yes`); token budget fails hard if compliance
context can't fit.

## Testing

```bash
pytest tests/hearth -v   # HEARTH Phase-1 gates (P1-A…P1-D)
pytest tests/ -v         # full repo (ORACLE + HEARTH); CI runs this
```

## Code Standards

General A-level standards (file headers, WHY comments, `<50`-line functions,
Pydantic `extra="forbid"`, no `print` in library code, naming,
no-`monkeypatch` testing, Tailwind) live in the **`code-quality` skill** +
global `CLAUDE.md` — not duplicated here. Repo-specific deltas:

- **Logger namespace:** `LOGGER = logging.getLogger("oracle.<module>")` /
  `logging.getLogger("hearth.<module>")` (uppercase `LOGGER`).
- **ORACLE:** mark `__safety_critical__: bool = True` on compliance-obligation
  extractors, routing/grading deciders, `pack_validator`,
  review/compliance orchestrators, and remediation-language producers.
- **HEARTH:** every module header carries `Safety Critical:` and
  `Financially Critical:` fields plus matching dunders. Financially-critical
  modules (scrubber, pack loader/signing, audit, boundary, render, cli)
  follow the **never-suppress-error** pattern: a failure is logged in full
  and surfaced as a refusal — a scrub that fails OPEN is the cardinal
  failure mode.
- Parser/rule-pack models that accept extensible input use `extra="allow"`
  **with a WHY comment** (everything at the API boundary stays
  `extra="forbid"`). In HEARTH the one open surface is `MicroRule.payload`
  (a typed `dict`), validated by its consumers.
