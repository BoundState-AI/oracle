# Atlas Handoff — Review of the Corpus Intake + Scrub Slice

**Context:** Internal code review of our own application by its own team.
The new module helps the operator convert their raw engagement export
into the privacy-scrubbed corpus file our test harness expects. The
identifier patterns involved are privacy-PROTECTION code: they block
personal and contract identifiers from being written to the output.

**From:** Beth (builder — your pass is the independent gate).
**Under review:** the UNCOMMITTED working tree on `133ed41` — new
`oracle/disposition/corpus_scrub.py`, CLI subcommands
`disposition corpus scrub|check` in `oracle/cli.py`, tests in
`tests/disposition/test_corpus_scrub.py`, spec in
`docs/slices/RDW_CORPUS_SCRUB_SLICE.md` (CS1-CS6). Suites at handoff:
**626 passed / 5 skipped** (617 + 9 new).

## What it does

`scrub RAW OUT --terms FILE [--map ...] [--apply]`: reads raw CSV/XLSX,
maps real-world headers to the corpus schema (synonyms + explicit
overrides), replaces operator-supplied terms (the terms file lives
outside the repo), scans every output cell against the D-3 identifier
patterns plus the terms, and writes only on a zero-hit scan with
`--apply` (fail closed; dry run by default). `check FILE`: loads any
corpus and reports tallies vs the engagement targets plus ALL per-row
coherence errors.

## The ask

Verify CS1-CS6 hold, then review the new code for defects. Areas I'd
scrutinize first:

1. **Fail-closed completeness.** Confirm there is no path that writes
   output with an unresolved hit — including partial writes on
   exceptions mid-write, and the CLI exit codes.
2. **Term replacement edge cases.** Overlapping terms (longest-first
   ordering), case variants, terms containing regex metacharacters
   (escaped?), replacement text that itself matches a pattern or term,
   Unicode in cells.
3. **Header mapping.** Ambiguous headers (two columns both mapping to
   one field — first wins, second silently dropped: is the report line
   enough?), the synonym table's fitness for the operator's real
   spreadsheet, `--map` parsing.
4. **XLSX intake reuse.** The raw reader reuses the corpus module's
   OOXML reader (named-sheet selection, shared strings) — same
   robustness expectations as before.
5. **check() semantics.** It reports all coherence errors rather than
   raising on the first; confirm `reconciled` can't read true on any
   non-conforming input.
6. **No identifier retention.** The tool must never write the terms
   file's contents anywhere (logs excepted — operator console only) and
   the repo must contain no engagement names. Sweep the new code and
   tests for accidental real-world identifiers (tests use synthetic
   "Acme"/"Widget" only).

Run the full suite independently and report your numbers. Same format
as before: verdicts, new findings ranked with file:line + reproduction,
suite result.

## Known and out of scope

A subsequent product review (Fran, 2026-07-31) already established that
the corpus FORMAT will evolve: an obligated_actor column, work-package
records, and a replay-based reconciliation are specced for the next
slice (`docs/slices/RDW_MODEL_SPLIT_SPEC.md`). Findings about the
format's completeness or the checker's tally-based semantics are
acknowledged as deferred — this review is about the intake/scrub
MECHANICS: mapping, term replacement, fail-closed scanning, and the
check report's correctness against the format as it exists today.

*Advisory-only per D-1. Gate-record docs are Beth-maintained.*
