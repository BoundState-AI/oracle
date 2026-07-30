# ERRATA RFC 001 — Re-base the disposition model from single code to RDW axes

**Status:** OPEN — requires domain-authority approval + the targeted ORACLE
pass (§5) before any build consumes it.
**Channel:** graded errata channel per `docs/DISPOSITION_SLICE_PLAN.md`
(Standing constraints): behavioral contract change → version bump + explicit
slice-replay/migration rules. The engine spec is protected; this RFC is the
only legitimate path to changing it.
**Target:** `docs/ORACLE_DISPOSITION_SPEC.md` v0.5.0 → v0.6.0
**Driver:** `docs/RDW_SPEC.md` v0.2.0 (product spec, from the live
supplier-disposition engagement).
**Author:** Dr. Joseph Wilde / Claude (Beth), 2026-07-30

---

## 1. The change

The disposition unit's system of record changes from **one code
(CW/MI/EX/NA/OPEN) plus qualifying fields** to **six independent axes**
(RDW §7): applicability, obligated actor, organization responsibility,
implementation, approval, review. The five codes become a **derived export
view** under RDW §7.1's mapping, alongside customer-facing labels
(Meet/Meets Intent/N/A/TBD/Open-Not Met/Exception).

## 2. Why (evidence, not preference)

1. **The fixture's hardest cases are axis-collapse failures.** Case 1
   (AMR-1): applicability, actor, and approval state crushed into one code —
   the corrected disposition (EX) still conflates "applies to the program"
   with "the named approval chain is not exercised." On axes:
   applicability Yes / actor program+TA / responsibility external / approval
   required-not-exercised — no information loss, no forced choice. Case 12:
   class conflated with fracture classification — separate axes by
   construction. Case 26 (the run's highest-consequence finding): the
   approving authority's identity is an *actor-axis* question the code model
   could only bolt on as a boolean.
2. **`Open/Not Met` is inexpressible in five codes.** "Applies + mandatory
   control absent + no relief requested" is today mislabeled OPEN
   (suggesting undecided) or prematurely EX (fabricating a relief request).
   The live engagement hit this on AMR-14/EFCP.
3. **The single status field is the product's named enemy.** RDW §2 defines
   the recurring compliance failure as status compression; our five-code
   model is a better compression, but still a compression. The engine should
   store what the product stores.

## 3. What survives unchanged (the invariant layer)

The five-code semantics survive as the export mapping with guards (RDW §7.1:
no exception softening, voluntary-expansion classes, truth-table test).
Unchanged in force, re-referenced from RDW: OPEN/TBD fail-closed rules and
the closed reason vocabulary (§2.3, extended with
`classification_unresolved`); universal human election + release state
machine (§1.2/§7.1 — the Review axis IS workflow_state; S1's implementation
carries over); authority classification (§4) as actor-axis machinery;
capability model + NA-vs-zero-limit (§3/§6); provenance and rights rules
(§7); consistency gates and flags (§9, extended by RDW §10.3 axis-coherence
gates); voluntary-expansion guard (§10); reference typing + propagation
discipline (§11/§11.1); output contract (§12); evaluation contracts,
kill-criteria, reproducibility (§15/§16 + D-2); advisory posture (§17/D-1);
all seven D-decisions and all five P-decisions.

## 4. Migration rules (slice-replay)

1. **Fixture:** `spec_rules` pointers are untouched (numbering frozen). Each
   case's proposed/corrected codes translate through the §7.1 mapping to
   axis tuples; labels (`expert_corrected`, `must_not_propose`, …) and
   merge-block semantics are unchanged. A migration table is generated
   mechanically and reviewed by domain authority; any case whose translation
   is ambiguous becomes a new labeled case rather than a silent choice.
2. **S1 refactor slice (S1R):** models v2 — `DispositionUnit` carries the
   six axes; the five-code field becomes a computed property implementing
   §7.1 (with its truth-table test, engine §16 style). Survives as-is: codes
   enums (as export values), sub-reason vocabulary, state machine (Review
   axis), roll-up composition machinery (badges roll up over export labels),
   fixture harness, all S1 gate hardening (frozen models, no model_copy
   bypass, evidenced impossibility, acceptance gates).
3. **S1a stays parked** until S1R lands; its entry criteria gain one line:
   the event log stores axis transitions, not code transitions.
4. **Committed dispositions:** none exist yet in any production store —
   migration cost of recorded data is zero. This is the cheapest moment this
   change will ever be.
5. **Slice plan:** re-planned after this RFC + the §5 pass approve; expected
   shape S1R → S1a → Phase-0 curation slices → Phase-1 interview slices,
   with `feat/tailor-helper` harvested as prototype material for the
   interview layer, not merged as-is.

## 5. Targeted ORACLE pass (review seed — run this, not full re-convergence)

Single round, sequencing/coupling + contract lens, over `RDW_SPEC.md` + this
RFC together. Attack surfaces, in priority order:

1. **Axis-model completeness:** are six axes sufficient and independent?
   (Candidate missing axis: evidence sufficiency — currently derived. Prove
   or refute.)
2. **Export mapping totality:** RDW §7.1 + guards — does every reachable
   axis combination map to exactly one label or one named contradiction?
   Where does `partial` implementation map, and does it leak compliance?
3. **Axis-coherence gate table (RDW §10.3):** find the contradiction classes
   it misses (the reviewers found 7 missing gates on S1's single-code model;
   six axes have more surface).
4. **Fixture translation ambiguities:** which of the 26 cases do NOT
   translate cleanly through §7.1 (predicted: cases 1, 8, 17, 21 — verify).
5. **Interview-engine determinism seam:** question selection is
   model-assisted (RDW §10) — is the boundary between "model proposes
   question" and "deterministic engine controls allowed states" airtight, or
   can question *ordering* steer dispositions (automation-bias vector,
   Appendix C)?
6. **The two-document architecture itself:** does RDW-defers-to-engine ever
   invert silently (a §7.1 mapping rule contradicting engine §2.2, say)?

## 6. Approval

- [x] Domain authority (Dr. Wilde) — model change + migration rules approved
      2026-07-30 ("Let's build it"); recorded by Beth. Draft fixture
      translation table generated (`docs/FIXTURE_AXIS_MIGRATION.md`, 26
      cases, 7 flagged ambiguous) — the 7 ambiguous rows still need his
      per-case disposition.
- [ ] Targeted ORACLE pass run; accepted defects folded into RDW_SPEC v0.3 /
      this RFC; unresolved questions dispositioned
- [ ] On both: engine spec v0.6.0 stamped (the ONE sanctioned edit of the
      protected file), slice plan re-planned, S1R activated
      (`docs/slices/S1R_SPEC.md` is drafted and gated on this box)

Until all three boxes: v0.5.0 remains the binding engine contract; no build
consumes the axis model.
