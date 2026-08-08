# Fixture Axis Migration — DRAFT translation table (ERRATA RFC 001 §4.1)

**Status:** DRAFT — mechanical translation of each fixture case's corrected
disposition into RDW §7 axes, for (a) domain-authority review and (b) the
targeted ORACLE pass (RFC §5, attack surface 4). Ambiguous rows become new
labeled cases, never silent choices. Counts below are computed from the
fixture at generation time (case count: 26; ambiguous: 7).

Axis shorthand: applicability | obligated actor | org responsibility |
implementation | approval. "—" = not reached given applicability No.
Package/comment-check cases are axis-neutral and carry over unchanged.

| Case | Requirement | Label | Corrected (v0.5 code) | Axis translation (draft) | Status | Review note |
|---|---|---|---|---|---|---|
| 1 | AMR-1 | expert_corrected | EX | Yes | program/M&P/TA | external | alternate (contractual route) | required→not exercised | ⚠ AMBIG | route semantics live on the approval axis; verify vs engine §4.1 rule 4 (deliberate bypass → relief) |
| 2 | AMR-52 | expert_corrected | NA | No (scope: metallic process) | — | — | — | — | clean | polymer-counterpart NA; pure applicability axis |
| 3 | AMR-51(e) | correct_positive | MI | Yes | producer | owner | alternate proposed (subpara (e) only) | required | clean | remap granularity untouched; per-unit axes |
| 4 | AMR-39 | expert_corrected | MI | Yes | producer | owner | AMBIG: meets-as-written (zero limit) vs alternate | required? | ⚠ AMBIG | zero-limit protocol: Meet-with-parameter or Meets-Intent? audit-exposure argument wants it visible as alternate |
| 5 | AMR-66 | expert_corrected | MI | Yes | producer | owner | same as case 4 | same | ⚠ AMBIG | paired with case 4 — must translate identically |
| 6 | AMR-45 | expert_corrected | CW | Yes | producer | owner | meets as written | not required (relief paths preserved) | clean | §7.1 guard: no waiver language, no exception entry |
| 7 | AMR-46 | expert_corrected | CW | Yes | producer | owner | meets as written | not required | clean | code/narrative agreement now = axis/narrative agreement |
| 8 | AMR-63 | expert_corrected | EX | Yes | CEO/agency | external | not met as written | required→declined-to-submit (relief requested) | ⚠ AMBIG | Exception vs Open/Not-Met boundary: relief IS requested → Exception label; verify the mapping expresses 'declines to submit' |
| 9 | AMR-84 | expert_corrected | NA | No (polymer section) | — | — | — | — ; voluntary adoption barred | clean | disclosed-class guard carries the intent note |
| 10 | AMR-69 | expert_corrected | CW | Yes | producer | owner | meets as written (data path per requirement) | not required | clean | framing rule becomes a §13.2 comment check |
| 11 | AMR-17 | correct_positive | EX | Yes | producer | owner | not met (detection capability) | required (relief) — separate from AMR-18 | clean | context note: RDW seed has classification TBD; this run's context had Class A established |
| 12 | AMR-17 | expert_corrected | — | (applicability-clause extraction) class + fracture = separate context facts | clean | becomes the canonical applicability-axis regression |
| 13 | AMR-18 | expert_corrected | — | (comment check — universal negative) | clean | axis-neutral; §13.2 |
| 14 | EFCR-5 | expert_corrected | MI | Yes | producer | owner | alternate proposed | required — unit = material not family | clean | unit-of-analysis flag unchanged |
| 15 | EFCR-5 | expert_corrected | — | (comment check — borrowed terminology) | clean | axis-neutral; §13.2 |
| 16 | EFCR-1 | expert_corrected | EX | EFCR-1: same family as case 1 | ⚠ AMBIG | translate identically to case 1 or the authority scan loses its cross-standard lesson |
| 17 | EFCR-2 | expert_corrected | MI | Yes | producer | owner | partial (plan kept, link eliminated) | n/a — dependency_eliminated | ⚠ AMBIG | MI-by-alternative vs partial: the eliminated artifact interacts with the approval axis |
| 18 | EFCR-7 | correct_positive | NA | No (physical impossibility: wire vs powder) | — | — | — | — | clean | capability-model citation unchanged |
| 19 | AMR-21 | must_not_propose | OPEN | TBD(customer_input_missing) on applicability-of-crediting | must_not_propose | clean | TBD is the axis-model native answer |
| 20 | AMR-82 | must_not_propose | OPEN | TBD(customer_input_missing) — joining in scope? | must_not_propose | clean |  |
| 21 | AMR-65 | expert_discovered | CW | Yes | producer | owner | meets as written | not required + derived context fact (SD-7) | ⚠ AMBIG | verify derived-fact minting represents the lot-provisional-bridge loss on axes/context, not as a code |
| 22 | package | expert_corrected | counts | (package rule — counts computed from matrix) | clean | unchanged; axis counts now per-axis AND per-export-label |
| 23 | package | expert_corrected | — | (package rule — referenced artifacts resolve) | clean | unchanged |
| 24 | external_reference | expert_corrected | — | (external citation verification) | clean | unchanged |
| 25 | NASA-STD-6030 | expert_corrected | — | (exclusion argument from definitions) | clean | unchanged; feeds applicability-axis rationale |
| 26 | NASA-STD-6030 | expert_discovered | — | actor axis: approving-role identity unestablished → actor TBD across 18 AMRs | clean | becomes THE actor-axis regression case |

## Ambiguity summary (7 cases for domain review)

Cases 1/16 (authority-route semantics on the approval axis), 4/5 (zero-limit:
Meet-with-parameter vs Meets-Intent — must resolve identically), 8 (Exception
vs Open/Not-Met when relief is requested by declining to submit), 17
(dependency-eliminated interaction with partial implementation), 21 (derived
context-fact representation). Every other case translates cleanly, and every
package-level rule (22–25) is axis-neutral.
