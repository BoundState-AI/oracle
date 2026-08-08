# RDW Build Spec — Contract/Readiness Model Split (Fran P0)

**Builder:** Beth. **Source:** Fran's product review 2026-07-31 (P0:
"one live session row cannot simultaneously be Contract: CW and
Readiness: Not Met with Plan — that combination exists all over our
engagement"). **Status:** DRAFT pending Dr. Wilde's ruling — this
changes the axis model that is the system of record.

## The defect being fixed

`implementation_state` currently serves two masters: the §7.1 contract
label derivation (CW needs `meets_as_written`) and the readiness
derivation (Not Met with Plan needs `not_met`/`partial`). AMR-106 —
commit to comply as written, EIDP system not yet built — is
inexpressible. The corpus "golden" papered over this by validating
supplied labels instead of engine-derived ones.

## M1 — Split the election (P0)

Two new axes replace `implementation_state`'s double duty:

- **`fulfillment_path`**: `as_written | alternative_intent | exception |
  not_applicable | tbd` — the CONTRACT election ("how will this be
  fulfilled?").
- **`execution_state`**: `not_started | partial | implemented |
  evidenced | verified | tbd` — the EXECUTION fact ("where is
  implementation today?").

Derivations:

- **Contract label** ← fulfillment_path only (+ existing gates):
  `as_written`→CW; `alternative_intent`→MI (fields+approval gates);
  `exception`→EX (basis+closure gates); `not_applicable`→NA (citation
  gate); `tbd`→TBD or Open/Not Met (Open when inputs are resolved but
  no commitment is elected; TBD while blocked on facts).
- **Readiness** ← execution_state + evidence + actions + flags:
  applicability no→Technical N/A; not_yet_due→Not Yet Due;
  `verified`/`evidenced` with registry-verified evidence→Met;
  `implemented` without verified evidence→TBD Verify;
  `not_started`/`partial` + plan-quality open action→Not Met with Plan
  (without a plan→TBD Verify); external responsibility→External Action
  (rendered "Program Action").

AMR-106 becomes: fulfillment=as_written (CW) + execution=not_started +
plan action (Not Met with Plan). Both true at once, one record.

**Migration (replay compat) — PROTOTYPE-VALIDATED 2026-07-31.**
Fulfillment and execution migrate independently. Execution:
`meets_as_written`→evidenced; `alternate_proposed`→partial;
`not_met`/`not_reached`→not_started; `partial`→partial; `tbd`→tbd.
Fulfillment: applicability=no→not_applicable;
`meets_as_written`→as_written; `alternate_proposed`→alternative_intent;
`not_met`+approval∈{required,draft,submitted,approved}→exception;
everything else→tbd (open: no commitment elected).

Exhaustive scratchpad harness (504 contract combos; 12,096 readiness
combos incl. evidence/actions/NYD/citation variants) vs the CURRENT
engine: **contract labels identical on all 504; readiness identical on
every session-reachable combo except ONE deliberate class** —
`alternate_proposed` + plan-quality action was legacy "TBD Verify" (a
fallthrough artifact) and becomes "Not Met with Plan" (an alternative
control with a live plan IS not-met-with-plan). That divergence is
documented here and pinned by a migration test. Combos that raise
AxisContradiction are unreachable via set_axes and exempt.
Anchors verified in prototype: AMR-106 = Meet(CW) + Not Met with Plan;
AMR-113 (actor=ceo, responsibility=support, plan) = External Action.

## M2 — Obligated actor ≠ our responsibility (P0)

The interview asks two questions: who is obligated (actor), then whose
job is execution for the evaluated org: `owner | support | external`.
Never auto-set. Actor program/ceo defaults the PROMPT to external but
the operator elects. AMR-113 anchor: obligated_actor=ceo,
organization_responsibility=support — readiness External/Program
Action, never supplier-owned.

## M3 — Evidence strictness (Fran P1)

Registry-verified evidence is required for readiness Met and contract
CW-with-`evidenced/verified` claims. A typed citation without a
registry entry keeps readiness at TBD Verify (today it qualifies with a
log warning).

## M4 — Release gating (Fran P1)

External products (Appendix A, supplier matrix) refuse rows whose
review_state is not `accepted` unless `--include-draft` is passed,
which watermarks every sheet/file DRAFT — NOT RELEASABLE.

## M5 — Interview/advisor ordering (Fran P1)

Advisor closure suggestions and comment drafting run AFTER the
operator's elections for the unit, with context including raw answers,
attached evidence, existing actions, and work-package controls.
`PROMPT_VERSION` becomes a content hash of the prompt text.

## M6 — Visible NYD (Fran P2)

`not_yet_due` appears in the displayed implementation/execution choices.

## M7 — CEO dependency coverage (Fran P1)

`ceo.identity` edges extend to every CEO-assigned requirement
(sweep the curated pack for CEO-obligated AMRs incl. AMR-113), so a CEO
identity change reopens them.

## Deferred to the corpus-replay slice (next)

WorkPackageRecord (owner/objective/dependencies/actions/deliverables/
evidence/exit/gate); corpus v2 format with obligated_actor + WP sheet +
enough per-row inputs to REPLAY a session through normal events and
compare engine-DERIVED labels to expected (anchors: AMR-2, 14, 29, 38,
51, 57, 97, 106, 110, 113, 115; AMR-106 = CW + NMWP; AMR-113 = CEO
obligation + support); guide covering all 115 AMRs + 16 WP chapters,
AMR-only, DOCX. The scrub tool (slice in Atlas review) is format-
agnostic column mapping and survives; it gains the new columns.

## Sequencing

1. Atlas clears the corpus-scrub slice → commit it (operator's word).
2. Build M1-M7 (this spec) → suites → Atlas gate → commit.
3. Corpus-replay slice (above) → Joe's scrubbed 115 rows land → the
   real behavioral golden goes live.

*Advisory-only per D-1. The protected disposition spec is untouched;
if adopted, the model change is recorded via the errata channel with
Dr. Wilde's ruling.*
