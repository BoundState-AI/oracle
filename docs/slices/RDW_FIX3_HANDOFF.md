# RDW Fix Round 3 — Grok Handoff (Fran's product review)

**Base:** `983ff9d` on `build/rdw-mvp-grok` (pushed).
**Authority:** Fran's product review of 2026-07-30 + Beth's verification
(bundle doc, § "Fran's product review"). Every finding below is
probe-confirmed. Ordering follows Fran's recommendation list. The goal of
this round: make the interview able to *finish every disposition* and make
the assistant layer honest — so that when the operator's real 115-AMR
corpus arrives, it can load and pass end to end.

## FR1 — CEO intake (critical)

The intake must establish CEO identity, not just toggle a flag:

- "Confirm customer is assumed CEO?" →
  - **y**: record `ceo.identity` as an ASSUMED fact ("<customer name>,
    assumed CEO") with owner; org stays `assumed_ceo=True, confirmed=False`.
  - **n**: ask **"Who is the CEO (cognizant engineering organization)?"**;
    record `ceo.identity` as a confirmed fact with the given name; update
    the org tuple (replace/add the CEO org with `confirmed=True`).
  - skip/unknown: `ceo.identity` assumed-unknown, TBD posture; intake may
    complete but the fact ledger shows the gap.
- Never set `confirmed=True` on the customer org without an identity.
- AMR-2 / AMR-4 / authority-dependent decision paths read `ceo.identity`
  (graph fact edge), so an unresolved CEO surfaces as a blocker, not
  silence.

## FR2 — AF3: advisor LOW scoping (carried from Beth's review)

LOW must be decided from **unit-relevant** facts: a fact influences a unit
iff the dependency graph links them (fact edge or prerequisite chain) or
the fact key is named by the unit's decision rules. The seeded
classification assumption must stop LOW-ing unrelated units; the AMR-14
Open/Not Met proposal path must be reachable in a seeded session (test
this exact scenario).

## FR3 — Disposition-specific interview paths (critical)

Every label the gates can demand must be completable through the walk.
After the axis answer, gather what the C1/Stage-A gates require BEFORE
electing, with re-prompt on refusal:

- **N/A**: prompt for the scope citation (free text, nonblank) →
  `scope_citation`.
- **Meet**: prompt to cite evidence — doc id + revision (+ optional date/
  note) → `attach_evidence`; offer registry registration when an
  EvidenceStore exists.
- **Meets Intent**: prompt for intent statement + alternative control +
  integral/disclosed class (store on the unit; add the fields to
  `UnitAxesState` if absent — mirror the DispositionUnit fields).
- **Exception**: prompt for exception basis, then closure path — either
  pick/create an ActionRecord (mini-form: id, title, owner, deliverable,
  exit criteria) or a permanent-relief basis.
- **Not Met**: offer the plan mini-form (ActionRecord) so the row can be
  Not Met **with Plan**; without it the readiness view stays TBD Verify —
  say so on screen.
- **Not Yet Due**: prompt for the trigger/justification.

The scripted-walk tests must complete one of EACH disposition end to end.

## FR4 — Real live advisor + hash integrity

1. `LiveAdvisor.propose` and `suggest_closure` become real model calls
   returning STRUCTURED output (JSON per a schema; parse-validate;
   fallback to DeterministicAdvisor on parse failure, recorded as such).
   The deterministic gates still rule: any proposed label that
   `evaluate_unit` blocks is stripped with the refusal recorded; §13.2 +
   grader run on all text fields.
2. **INTEG-1 fix:** `output_hash` must be computed over the FINAL stored
   object — never mutate any field after hashing (construct once, hash
   last; add a round-trip test: recompute(stored with hash cleared) ==
   stored hash for every advisor path incl. LiveAdvisor fallbacks).
3. AF4: default model id — current generation (`claude-sonnet-5`-class),
   env override unchanged.

## FR5 — Library integrity + real reuse

1. **INTEG-2 fix:** the D-3 blocklist scans EVERY exported string —
   fact statements, comments, paired answers, disposition fields, action
   fields. One refusal message naming the offending field.
2. Import gains dispositions + action patterns as **suggestions**: when
   the operator reaches a requirement with a library disposition, the
   walk offers it as a pre-filled proposal (band MEDIUM, provenance
   shown) requiring normal attestation — never auto-applied. Same for
   action patterns on closure prompts.
3. AF5: imported paired answers either apply to the paired units through
   the normal machinery on import, or surface as a suggestion when the
   paired question would fire — not silent suppression.

## FR6 — Product-grade exports

1. **Appendix-A as a real XLSX worksheet** (stdlib OOXML writer already
   exists): full requirement text (NO truncation — kill the `[:120]`),
   Section / Description / Requirement / Applicable / Comments, one row
   per AMR in standard order.
2. **MRL implementation guide** (the working guide, DOCX or MD→DOCX):
   per-AMR sections with — what it requires / why it exists / process
   interpretation (from facts, e.g. cold spray) / matrix comment /
   current evidence / controlled destination / objective evidence /
   done-when test / related AMRs (graph) / gate-hold point. Fields come
   from the record + advisor drafts; empty fields render as explicit
   gaps, never invented content.

## FR7 — Fail closed on missing curated pack

`load_rdw_default_packs` REFUSES to run when the curated 6030 pack is
absent (clear error naming the curation path). Explicit
`allow_builtin=True` / `--allow-builtin` is the only escape, and it logs
that the builtin is known-corrupt.

## FR8 — Corpus golden (wire now, data blocked)

Define the corpus input format so the operator can deliver it:
one row per AMR — requirement id, operator answers (raw), final axes,
contract label, readiness outcome, matrix comment, action(s) + work
package, evidence refs; plus a work-package table (16 expected). Accept
CSV or XLSX. Loader + reconciliation harness assert EXACT counts:
contract **85 CW / 6 MI / 7 EX / 17 NA**, readiness **2 Met / 39 Not Met
with Plan / 34 TBD / 18 program actions / 21 Technical N/A / 1 Not Yet
Due**. Marked skip-with-reason until the scrubbed corpus file exists at a
path named by the operator.

## Never touch / stop-if

As prior rounds (protected files, builtin packs, gate-record docs;
oracle/disposition + tests + minimal CLI wiring only). Stop if any FR3
field cannot be stored without breaking replay compatibility — report the
event-schema change needed instead of guessing.

## Done when

Scripted walks complete all six disposition types; AMR-14 proposal fires
in a seeded session; advisor hashes round-trip; library refuses "Boeing"
in any field and re-offers dispositions as suggestions; Appendix-A XLSX
carries full texts; the guide renders with explicit gaps; missing curated
pack fails closed; suites green; corpus harness ready and skipping with
reason.

*Advisory-only per D-1.*
