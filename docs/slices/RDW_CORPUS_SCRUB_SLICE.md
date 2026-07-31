# RDW Slice — Corpus Intake + D-3 Scrub Helper

**Builder:** Beth. **Requested by:** Dr. Wilde, 2026-07-31. **Goal:**
unblock the 115-row behavioral golden (FR8) by making it trivial to turn
the operator's RAW Fran-session export into the scrubbed corpus
`RDW_CORPUS_PATH` expects — with D-3 guarantees enforced by tooling, not
operator care.

## Requirements

- **CS1 — raw intake.** Read the operator's raw export as CSV or XLSX
  (XLSX via the existing corpus reader: named `Corpus` sheet or single
  sheet). Tolerate real-world headers: map columns to the corpus schema
  by normalized-name matching plus a small synonym table
  (e.g. "Req ID" → requirement_id, "Disposition" → contract_label),
  with explicit `--map "RawHeader=field"` overrides winning.
- **CS2 — terms file OUTSIDE the repo, REQUIRED to write.** Engagement
  identifiers are supplied in an operator-owned terms file (path
  argument), one per line: `term` (replaced with `[REDACTED]`) or
  `term=Replacement`. The repo never contains the identifiers; the tool
  never writes the terms file anywhere. Writing WITHOUT a terms file is
  refused — pattern scanning cannot catch bare names — unless the
  operator passes `--no-terms` as an explicit attestation (Atlas G1).
  The output path may never resolve to the raw export or the terms file
  (G2). Replacement text is literal, never regex syntax (G7).
- **CS3 — scrub then scan, fail closed.** Apply term replacements
  (case-insensitive), then scan EVERY output cell against the D-3
  blocklist patterns (reused from the library module) AND the terms.
  Any remaining hit → refuse to write, report row/column/what matched.
  Writing happens only with `--apply` and a clean scan, via a temp file
  + atomic rename so a failed write never leaves partial output (G3).
- **CS4 — canonical output the loader ACCEPTS.** Before writing, every
  row passes loader-level validation (label/axis vocabulary, unique
  requirement ids) and labels are normalized; a row the loader would
  reject refuses the write with the exact errors (G5). Unmapped corpus
  fields render blank; extra raw columns are dropped (and named in the
  report so nothing vanishes silently). Explicit `--map` assignments
  always win over synonym matching, and unknown `--map` headers are an
  error (G4).
- **CS5 — check mode.** `corpus check <file>` loads any corpus file and
  reports: row count, contract/readiness tallies vs the engagement
  targets, work-package count, and per-row coherence errors (all of
  them, not just the first) — the dry-run for reconciliation.
- **CS6 — keyless deterministic tests.** Synthetic raw files with
  planted identifiers; no network, no keys, no real engagement data.

## Non-goals

Auto-redaction of pattern hits (a contract number's safe replacement is
a domain call — the operator fixes the source or adds a term); editing
the raw file in place; committing any corpus content to the repo.

## CLI

```
oracle disposition corpus scrub RAW.xlsx OUT.csv --terms terms.txt \
    [--map "Req ID=requirement_id"] [--apply]
oracle disposition corpus check OUT.csv
```

*Advisory-only per D-1. Atlas gates before commit.*
