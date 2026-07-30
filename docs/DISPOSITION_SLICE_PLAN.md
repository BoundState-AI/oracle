# Disposition v1 — Slice Build Plan

**Status:** CANONICAL — single-round ORACLE review incorporated (run
20260728-213016, 9 accepted defects; record in `docs/oracle_runs/`), all five
open decisions resolved by domain authority (Decision Record below).
**Cleared for S1.**
**Spec:** `docs/ORACLE_DISPOSITION_SPEC.md` v0.5.0 (build contract, protected)
**Method:** one slice = one `oracle_build.py` run (BUILD → CHECK → REVIEW →
GATE), committed on APPROVED, next slice builds on the committed state. Every
slice diff stays well under the 200K gate cap. Coverage floor 80 throughout.
Slice specs live in `docs/slices/` (generated per slice as reached).
**Author:** Dr. Joseph Wilde / Claude (Beth), 2026-07-28

## Decision Record (plan-level, authority: Dr. Joseph Wilde, 2026-07-28)

| ID | Decision | Resolution |
|---|---|---|
| P-1 | S4 authority-recall threshold | **Two-tier.** 100% recall on the enumerated seed corpus (6030's 18 named-authority AMRs + 6033's parallel chain — a closed, known list where a miss is disqualifying). ≥95% recall / ≥98% precision on the blind-locked expansion corpus. Residual-error waiver: every later-discovered miss becomes a mandatory labeled fixture case, and its pattern class routes to `pending_review` until the classifier is fixed. |
| P-2 | S6/S7 data governance | Approved LLM endpoint: Anthropic commercial API under no-training terms. Development/eval corpora: BoundState-authored documents + publicly released NASA standards **only**. No customer-supplied document through any LLM until counsel clears permitted-use per engagement. The deterministic linker is local/in-tenant and may index in-house content; the LLM boundary is where governance bites. |
| P-3 | Operational capacity bands | v1 ships the **instrumentation** (pending_review count, OPEN aging, reopen blast-radius in every gate report) and the **authority** (degraded-release waiver: Dr. Wilde only, time-boxed, logged). Numeric bands are set after the first production disposition package, from retro data. Multi-tenant bands are v2 backlog. |
| P-4 | Persistence placement | **Standalone S1a.** Append-only, hash-chained JSONL event log following the in-repo HEARTH evidence-store/audit pattern; atomic release-marking via write-temp-rename; v1 concurrency model is an honest single-writer file lock (one operator) with the optimistic version-check contract implemented now so multi-user needs no schema change. |
| P-5 | Interactive walkthrough | Added: S8 grows the `oracle disposition walk` CLI stepper (TTY-interactive; fails closed non-TTY, same posture as promote-pack). New **S9**: web walkthrough tab + per-unit grounded chat (chat_engine architecture, grader-enforced — the model explains and drafts, never elects). Five-election UI with humane phrasing over rigorous codes; skipping a unit = OPEN, never silence. Governed by P-2. |

## Sequencing logic

Deterministic spine first, judgment layers last: the assisted matrix must be
fully useful with **zero** LLM proposals (a human can enter every code by
hand and still get provenance, gates, and exports). LLM proposal quality then
becomes an additive layer whose failure modes are bounded by gates that
already exist — and the §16 kill-criteria are measured against working
machinery, not promises.

Two cross-cutting concerns sit under the spine rather than inside the
judgment layers:

- **Durable, concurrency-safe, auditable state (S1a)** — a compliance
  disposition cannot rely on in-memory pure functions.
- **A frozen, independently-adjudicated evaluation contract** (below) —
  the D-2 kill-criteria are release go/no-go decisions and must be
  reproducible.

## The slices

### S1 — Data model + release state machine *(the spine)*
Unit schema (§7, Pydantic `extra="forbid"`), workflow_state machine (§7.1),
acceptance records, composition vectors + §1.1 roll-up badge derivation,
§2.3 sub-reason vocabulary as a closed enum, levy manifest model. Domain
models and functions are pure and side-effect-free; the only I/O in this
slice is the test harness's read-only loading of static fixtures, schemas,
and manifests. Includes the fixture harness: case-count and
spec_rules-pointer drift assertions (§15/§16) go live here.
- **Done when:** every §7 field typed and validated; illegal state
  transitions raise; the §1.1 truth-table test passes for every child-code
  combination; machine code paths can set only `proposed`; every disposition
  record carries `schema_version` and `rule_version` fields.
- **Stop if:** a behavioral contract change is required. Non-semantic
  ambiguity is handled by the graded errata channel (Standing constraints),
  not a hard stop.

### S1a — Persistence, concurrency, and audit contract *(the spine — standalone per P-4)*
The release state machine needs a durable home before any slice records
human elections or exports. Implements, following the HEARTH
evidence-store/audit pattern (HEARTH was removed from the tree 2026-07-29;
reference implementation via `git show 28b807a:hearth/db/evidence_store.py`
and `git show 28b807a:hearth/audit/artifact.py`):
- Versioned repository schema for units, matrix, elections, acceptance records.
- Append-only, hash-chained transition/event log (who, when, from→to,
  inputs, rule_version).
- Optimistic-concurrency version checks (contract now; single-writer file
  lock is the enforced v1 model per P-4).
- Atomic release-marking (all-or-nothing, write-temp-rename) and idempotent
  CLI operations under retry.
- Authenticated actor identity and a role/permission model for every state
  transition; machine paths remain restricted to `proposed`.
- Tamper-evident audit events and re-import conflict handling.
- **Done when:** an unauthorized transition is rejected and logged; a
  tampered import/export is rejected; two concurrent writers cannot both
  commit conflicting transitions; a crash mid-transition leaves a consistent
  recoverable state.

### S2 — Extraction & unit boundaries (§7.3)
**Precondition (before coding):** publish an explicit pack-compatibility
contract stating whether existing pack outputs must remain byte-identical or
only semantically equivalent (with equivalence tests), plus a golden
re-freeze procedure. If shared parse/normalize code cannot satisfy "never
touch existing pack outputs" as written, build a disposition-only extraction
facade so pack paths are untouched by construction.
Extend `shall_extractor` to emit disposition units: hierarchical IDs
(AMR-51 → AMR-51(e)), `applicability_clause` extraction, documented
ID-stability rule, boundary-confirmation workflow (`oracle disposition
confirm-units`), golden parse fixtures for 6030 + 6033. Define a versioned
unit-identity/migration rule (split, merge, withdrawal), an accountable
boundary adjudicator, and release behavior for units pending confirmation.
- **Done when:** 6030/6033 re-extract to stable unit sets across two
  extractor invocations and match an independently-reviewed expected-unit
  set; golden parses committed; disposition of an unconfirmed unit raises;
  unit records carry stable IDs plus source-version pinning.
- **Never touch:** existing pack outputs consumed by the review engine
  (enforced by the compatibility contract above).

### S3 — Intake: scope + capability model (§3)
Intake schema with typed scope declarations, capability model with
`basis_evidence`, evidenced-impossibility rule failing closed, NA scope
citations plumbed. Fixture case 18 representable; cases 4/5 groundwork.
- **Done when:** a `physical_impossibility` without evidence routes to human
  adjudication, never NA; intake refuses to start disposition when absent.

### S4 — Authority classification + report (§4)
Token scan → per-unit `authority_classification`, ambiguity fails closed to
`pending_review`, per-standard coverage across the levied set, authority
report rendering **before** the matrix. Annotated corpus governed by the
Evaluation contract.
- **Done when:** P-1 thresholds met — 100% recall on the seed corpus,
  ≥95% recall / ≥98% precision on the blind-locked expansion corpus, with
  precision/false-positive reported alongside; fixture cases 1, 16, 26
  assert; report ordering enforced.

### S5 — Matrix + §9 gates/flags + scope-change reopening
Matrix assembly from S1–S4; all 15 §9.1 blocking gates and 8 §9.2 flags as
deterministic checks with recorded, authenticated human elections (S1a);
gate report (§12 #5) including P-3 instrumentation (pending_review count,
OPEN aging, reopen blast-radius); §3.2 reopening.
Controls whose machinery is deferred to v1.1 (cycle-free-propagation gate,
reserved sub-reasons) are emitted with an explicit **NOT_IMPLEMENTED /
OUT_OF_SCOPE** status — distinct from PASS, release-visible, never rolled up
as "passed."
- **Done when:** every implemented gate and flag has a test reproducing its
  observed-failure column; every deferred control emits NOT_IMPLEMENTED;
  fixture consistency cases (2, 6, 7, 11) assert; the gate report renders
  deferred controls distinctly.

### S6 — Deterministic proposal layer + assisted evidence linking
**Precondition (data governance, P-2):** documents lacking
ownership/permitted-use clearance are excluded from indexing, retrieval, and
any model processing by default; only P-2-approved corpora flow.
NA-vs-zero-limit logic over the capability model (cases 4, 5 vs 18), paired
scope questions asked once (case 19 — `must_not_propose` goes live), §8
banding with LOW → OPEN-as-question, BSMS linker in assisted mode: bundle
retrieval (roles per §14.1) over cleared packs + documents, explainable
match basis, derived `link_confidence`, grader pass, threshold →
`evidence_absent`. Links below threshold are flagged for human verification,
not silently dropped.
- **Done when:** linker precision@1 and false-link meet D-2 targets on the
  frozen held-out set; all `na_vs_zero_limit` cases green; non-cleared
  documents are provably unavailable to the linker.

### S7 — LLM proposal layer + calibration eval
Built as a thin vertical spike behind a feature flag, gated by a cheap
proposability probe first, under P-2 governance. Remap proposer (§5,
per-unit — case 3), intent statements, voluntary-expansion detection (cases
6, 9, 10), definitional exclusion arguments (case 25), narrative checks
(cases 12–15). Probabilistic eval harness per §16, separate from the
deterministic CHECK, governed by the Evaluation contract.
- **Done when:** zero false-CW on process-sensitive classes of the golden
  package (denominator per the Evaluation contract); ≥ 60% proposability
  floor measured — **the build-commitment decision point**: below floor,
  proposals ship dark and v1 is assisted-only, per §16.

### S8 — Outputs + CLI closure (incl. `walk` stepper, P-5)
Countersign export (state-preserving, re-import gated, signer identity
verified), exception detail, narrative computed from the matrix (case 22),
referenced-artifact gating (case 23), advisory labeling on every artifact
(D-1), per-output capability/version declaration (spec version, rule
version, NOT_IMPLEMENTED gates listed), `oracle disposition` CLI verb
finalized incl. **`oracle disposition walk`** — the TTY-interactive unit
stepper (fails closed non-TTY): intake wizard and authority-unidentified
units front-loaded, then unit-by-unit five-way election (CW / MI / NA / EX /
OPEN with humane phrasing), evidence and intent fields mandatory at election
per §7.1, paired questions asked once, navigation-away = OPEN.
- **Done when:** full §12 output contract emits in order on the reference
  corpus; a package with any OPEN/unelected unit refuses release-marking; no
  summary collapses NOT_IMPLEMENTED into "all gates passed"; countersign
  re-imports only with verified signer and consistent stored state; the walk
  stepper cannot exit a unit into silence.

### S9 — Web walkthrough + per-unit grounded chat (P-5)
Workspace tab in `server.py` + frontend: the S8 stepper's flow in the
browser, backed by the same S1a store and §9 gates; per-unit 2-way chat on
the grounded-module-chat architecture (`chat_engine` pattern): context =
current unit + its evidence bundle (rationale, applicability, exceptions,
definitions) + intake scope + prior elections; the grader strips prohibited
decision language — the model explains, retrieves, and drafts narrative
candidates; **only the human elects**. P-2 governance on every model call.
- **Done when:** a full standard can be walked browser-side with elections
  persisted and audited via S1a; no bulk-accept affordance exists (asserted
  by test — spec §1.2 names it a defect); skip/close = OPEN; chat responses
  carry evidence envelopes and never a disposition code.

## Evaluation contract (D-2 preconditions)

Before the slice that consumes a metric runs, its dataset is frozen and
cannot be tuned against:

- Immutable, versioned train/dev/test manifests with provenance and content hashes.
- Independent, blind annotation/adjudication authority (not the implementer);
  documented inclusion/exclusion rules and class stratification.
- Leakage checks (golden parses derived from builtin-pack sources must not
  overlap held-out evaluation items).
- Minimum sample sizes and reported confidence intervals; a metric is not
  "met" if the interval straddles the threshold.
- Every metric reports its complement: recall reports precision/false
  positives; precision@1 reports false-link; false-CW reports its exact
  denominator.
- Model, retriever, and prompt versions are recorded per evaluation run.

| Gate | Slice | Frozen set | Reported metrics |
|---|---|---|---|
| Authority recall | S4 | Seed corpus + blind-adjudicated expansion corpus (P-1) | recall + precision/false-positive |
| Linker quality | S6 | Held-out link set | precision@1 + false-link |
| Proposal safety | S7 | Golden package (process-sensitive) | false-CW + proposability floor |

## Fixture activation map

| Slice | Cases that become executable assertions |
|---|---|
| S1 | truth-table, count/pointer drift |
| S2 | 3 (unit granularity groundwork), 24 (citation-vs-corpus) |
| S3 | 18 |
| S4 | 1, 16, 26 |
| S5 | 2, 6, 7, 11, 17*, 21* (*consistency aspects only; propagation is v1.1) |
| S6 | 4, 5, 19, 20 |
| S7 | 3, 8–10, 12–15, 25 |
| S8 | 22, 23 |

By S8, all 26 cases have at least one active assertion; coverage is reported
per obligation (fully tested / partial / deferred) so "26/26 active" is never
read as "every obligation tested." `expert_corrected`/`expert_discovered`
regressions merge-block from the slice that activates them.

## Kill-criteria measurement milestones (D-2)

- After S4: authority recall/precision on the frozen corpora, per P-1.
- After S6: linker precision / false-link on the frozen held-out set.
- After S7: false-CW on process-sensitive classes; proposability floor —
  the build-commitment decision point.
- Each milestone has a predefined decision owner (Dr. Wilde) and a maximum
  number of retune cycles before it escalates to human adjudication.

## Standing constraints (every slice)

- `--coverage-floor 80`; full suite green; protected paths untouched (spec,
  run records, fixture — enforced by CHECK, not trust).
- Every disposition and export carries `schema_version` and `rule_version`.
- **Graded errata channel** (replaces the flat "no slice edits the spec" rule):
  - Non-semantic fixture/test-harness fixes (typos, pointer drift, comments)
    are allowed under dual review with a logged rationale.
  - A spec ambiguity or defect is raised as an errata RFC with a version bump
    and explicit slice-replay/migration rules; committed dispositions
    affected by a rule change are recomputed or invalidated per the migration
    procedure.
  - Behavioral contract changes hard-stop the slice and route back through
    review.
  - Forward-migration and old-export compatibility tests accompany any
    contract revision.
- Commit on APPROVED only; one slice per branch; PIPELINE_REPORT.md retained
  per slice in `oracle_builds/`.

## Coherence notes

1. §9.1's cycle-free-propagation gate and the two reserved sub-reasons are
   unbuilt until v1.1 — emitted as NOT_IMPLEMENTED / OUT_OF_SCOPE (never
   trivial PASS) so the gate table stays complete without misrepresenting a
   control as performed.
2. Cases 17 and 21 are only partially assertable in v1 (consistency surface,
   not propagation); the activation map and per-obligation coverage report
   make this explicit.
3. Fail-closed operations run on P-3's instrumentation-first model until
   production data exists to set numeric bands.
