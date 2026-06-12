# HEARTH — Buyer-Side Real Estate Intelligence Platform

> Bouncer gets you past the door, HEARTH gets you the house behind it.

The residential buyer's structural disadvantage is **unexplained defaults**:
pre-filled commission percentages, region-wide agreement scopes, backstop
clauses, contract deadlines the buyer doesn't know are negotiable. Every organ
of this platform exists to surface a default, cite the evidence against it,
and present a buyer-favorable alternative **for the buyer's licensed human to
draft and execute**.

This repository is a clone of the BoundState `oracle` repo: the ORACLE
multi-oracle review engine (which reviewed the HEARTH spec) lives in
`oracle/`, and HEARTH lives in `hearth/`. Spec: `docs/HEARTH_spec_v0.3.md`.

**Phase 1 status (founder field test):** DocScrubber CLI (findings-only),
CO-Larimer JurisdictionPack (provisional), data models, boundary-test
scaffold. No valuation engine, no MLS adapters, no optimizer, no LLM calls,
no UI beyond the CLI. See `BUILD_NOTES.md` for what is stubbed and why.

## Quickstart — scrub a document in two commands

```bash
pip install -e .
hearth scrub tests/fixtures/BDB24-6-24_greyrock_2026-06-11_SYNTHETIC.txt \
    --pack CO-Larimer --target-price 700000
```

(Without installing: `python -m hearth scrub <file> --pack CO-Larimer`.)

Supported inputs: `.pdf`, `.docx`, `.txt`, `.md`. Useful flags:

| Flag | Effect |
|------|--------|
| `--target-price USD` | enables `exposure_usd` math (e.g. backstop = fee% × price) |
| `--json PATH` | machine-readable findings |
| `--audit-dir DIR` | where the immutable audit artifact lands (default `hearth_audit/`) |
| `--packs-dir DIR` | use a pack library other than the built-in one |

### Exit codes — the scrubber FAILS CLOSED

| Code | Meaning |
|------|---------|
| 0 | scrub completed; findings (if any) are in the report |
| 2 | **REFUSED** — unparseable document, unusable pack, or unwritable audit trail. The document has NOT been reviewed. Never an empty success. |

## What Phase 1 deliberately does not do

- **No `suggested_template`, no generative legal language.** Findings-only
  mode until the Colorado UPL/brokerage counsel opinion (spec §8/§9) clears
  the gated-template path.
- **No LLM calls.** The `ClauseAnalyzer` protocol is stubbed
  (`NullClauseAnalyzer`); the pipeline is deterministic rule matching.
- **No network anything in `hearth/`.** Enforced by static scan and a
  runtime canary suite (`tests/hearth/test_boundary_*.py`): no BuyerPack
  field may reach an outbound call, a log, or a non-local store — that is a
  build-failing violation, not a guideline.
- **All pack rules are provisional** (no licensee/attorney review yet) and
  render under a PROVISIONAL banner. Findings are leads, not conclusions.

## Architecture (spec §1)

```
hearth/
├── api/            # FastAPI, single-tenant — /health only in P1
├── cli.py          # `hearth scrub ...`
├── core/
│   ├── scrubber/   # extraction → segmentation → rule match → findings
│   ├── boundary.py # testable BuyerPack-exfiltration definition (§1.1/§6)
│   └── valuation|signals|optimizer|fit|identity   # Phase ≥2 skeletons
├── data/           # Pydantic v2 contracts (§2, §11), extra="forbid"
├── packs/
│   ├── jurisdiction/CO-Larimer/pack.json  # 12 signed provisional micro-rules
│   └── signing.py  # STUB signer (drift detection, not authenticity)
├── audit/          # immutable per-run AuditArtifacts (§11)
└── utils/render.py # report rendering + mandatory banners (§8)
```

## Dependencies

Phase 1 added **zero** new runtime dependencies beyond the repo baseline
(pydantic v2, FastAPI, PyMuPDF, python-docx already shipped with ORACLE).
Phase 2 adds one: **cryptography** — Ed25519 per-reviewer rule signatures
(§13 P2-B); the stdlib has no Ed25519 implementation.

## Testing

```bash
pytest tests/hearth -v      # HEARTH Phase-1 suite (gates P1-A…P1-D)
pytest tests/ -v            # full repo: ORACLE + HEARTH
```

The Grey Rock BDB24-6-24 document is unit-test fixture #1
(`tests/fixtures/BDB24-6-24_greyrock_2026-06-11_SYNTHETIC.txt` — synthetic
reconstruction per handoff rule 3). The boundary canary BuyerPack is
fixture #2 (`tests/fixtures/buyerpack_canary.json`). Golden file:
`tests/hearth/golden/greyrock_findings.json` (regenerate deliberately with
`HEARTH_UPDATE_GOLDEN=1`).

## Legal posture (spec §8)

HEARTH is not a brokerage and performs no act defined as brokerage under
C.R.S. 12-10-201; it is an analytics and document-intelligence tool used by a
principal on their own behalf. Output banners are *in addition to* hard
workflow controls (findings-only mode, human-review gating, no direct-send),
never instead of them.

---
BoundState AI 2026 · Classification: BoundState Proprietary
Maintainer: Dr. Joseph Wilde
