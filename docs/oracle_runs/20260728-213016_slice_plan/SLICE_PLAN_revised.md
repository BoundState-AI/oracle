
# Disposition v1 — Slice Build Plan
Status: Draft revised after a single-round ORACLE pass (sequencing/coupling lens). Material governance, evaluation, and persistence gaps addressed below; four items remain flagged for human/domain decision before slice 1 starts. Spec: docs/ORACLE_DISPOSITION_SPEC.md v0.5.0 (build contract, protected) Method: one slice = one oracle_build.py run (BUILD → CHECK → REVIEW → GATE), committed on APPROVED, next slice builds on the committed state. Every slice diff stays well under the 200K gate cap. Coverage floor 80 throughout. Author: Dr. Joseph Wilde / Claude (Beth), 2026-07-28
## Sequencing logic
Deterministic spine first, judgment layers last: the assisted matrix must be fully useful with zero LLM proposals (a human can enter every code by hand and still get provenance, gates, and exports). LLM proposal quality then becomes an additive layer whose failure modes are bounded by gates that already exist — and the §16 kill-criteria are measured against working machinery, not promises.
Two cross-cutting concerns now sit under the spine rather than inside the judgment layers:
Durable, concurrency-safe, auditable state (see S1a) — because a compliance disposition cannot rely on in-memory pure functions.
A frozen, independently-adjudicated evaluation contract (see below) — because the D-2 kill-criteria are release go/no-go decisions and must be reproducible.
## The slices
### S1 — Data model + release state machine (the spine)
Unit schema (§7, Pydantic extra="forbid"), workflowstate machine (§7.1), acceptance records, composition vectors + §1.1 roll-up badge derivation, §2.3 sub-reason vocabulary as a closed enum, levy manifest model. Domain **models and functions are pure and side-effect-free**; the only I/O in this slice is the test harness's read-only loading of static fixtures, schemas, and manifests. Includes the fixture harness: case-count and specrules-pointer drift assertions (§15/§16) go live here.
Done when: every §7 field typed and validated; illegal state transitions raise; the §1.1 truth-table test passes for every child-code combination; machine code paths can set only proposed; every disposition record carries schema_version and rule_version fields.
Stop if: a behavioral contract change is required. Non-semantic ambiguity is handled by the graded errata channel (see Standing constraints), not a hard stop.
### S1a — Persistence, concurrency, and audit contract (the spine, new)
The release state machine needs a durable home before any slice records human elections or exports. This slice defines and implements:
Versioned repository schema for units, matrix, elections, and acceptance records.
Append-only transition/event log (who, when, from→to, inputs, rule_version).
Optimistic-concurrency version checks so concurrent reviewers cannot silently overwrite each other.
Atomic release-marking (all-or-nothing) and idempotent CLI operations under retry.
Authenticated actor identity and a role/permission model for every state transition; machine paths remain restricted to proposed.
Tamper-evident audit events and re-import conflict handling.
Done when: an unauthorized transition is rejected and logged; a tampered import/export is rejected; two concurrent writers cannot both commit conflicting transitions; a crash mid-transition leaves a consistent recoverable state.
(If sizing shows S1a exceeds the per-slice gate budget, its contracts may be distributed across S1/S5/S8 — see open decision below. The contracts themselves are non-negotiable.)
### S2 — Extraction & unit boundaries (§7.3)
Precondition (before coding): publish an explicit pack-compatibility contract stating whether existing pack outputs must remain byte-identical or only semantically equivalent (with equivalence tests), plus a golden re-freeze procedure. If shared parse/normalize code cannot satisfy "Never touch existing pack outputs" as written, build a disposition-only extraction facade so pack paths are untouched by construction. Resolve this before extending shall_extractor.
Extend shall_extractor to emit disposition units: hierarchical IDs (AMR-51 → AMR-51(e)), applicability_clause extraction, documented ID-stability rule, boundary-confirmation workflow (oracle disposition confirm-units), golden parse fixtures for 6030 + 6033 generated from the existing builtin-pack sources. Define a versioned unit-identity/migration rule covering split, merge, and withdrawal, an accountable boundary adjudicator, and the release behavior for units with pending confirmation.
Done when: 6030/6033 re-extract to stable unit sets across two extractor invocations and match an independently-reviewed expected-unit set; golden parses committed; disposition of an unconfirmed unit raises; unit records carry stable IDs plus source-version pinning.
Never touch: existing pack outputs consumed by the review engine (enforced by the compatibility contract above).
### S3 — Intake: scope + capability model (§3)
Intake schema with typed scope declarations, capability model with basis_evidence, evidenced-impossibility rule failing closed, NA scope citations plumbed. Fixture case 18 (genuine NA) representable; cases 4/5 groundwork (decided in S6).
Done when: a physical_impossibility without evidence routes to human adjudication, never NA; intake refuses to start disposition when absent.
### S4 — Authority classification + report (§4)
Token scan → per-unit authority_classification, ambiguity fails closed to pending_review, per-standard coverage across the levied set, authority report rendering before the matrix. Start the annotated corpus (6030's 18 named-authority AMRs + 6033's parallel chain) for recall measurement, governed by the Evaluation contract below.
Done when: recall meets the D-2 authority target on the frozen, blind-adjudicated corpus (target threshold is an open compliance decision — see below), measured with the false-positive/precision figure reported alongside; fixture cases 1, 16, 26 assert; report ordering enforced.
### S5 — Matrix + §9 gates/flags + scope-change reopening
Matrix assembly from S1–S4; all 15 §9.1 blocking gates and 8 §9.2 flags as deterministic checks with recorded, authenticated human elections; gate report (§12 #5); §3.2 reopening (scope-declaration change downgrades citing units to OPEN).
Controls whose machinery is deferred to v1.1 (cycle-free-propagation gate, reserved sub-reasons) are emitted with an explicit `NOT_IMPLEMENTED` / `OUT_OF_SCOPE` status that is distinct from PASS and is release-visible. They are never rolled up as "passed."
Done when: every implemented gate and flag has a test reproducing its observed-failure column; every deferred control emits NOT_IMPLEMENTED; fixture consistency cases (2, 6, 7, 11) assert; the gate report renders deferred controls distinctly.
### S6 — Deterministic proposal layer + assisted evidence linking
Precondition (data governance): documents lacking ownership/permitted-use clearance are excluded from indexing, retrieval, and any model processing by default. The linker and any downstream LLM layer may only use approved endpoints under no-training terms, with retention, provenance, and audit logging. (Concrete policy terms are an open legal/product decision — see below.)
NA-vs-zero-limit logic over the capability model (cases 4, 5 vs 18), paired scope questions asked once (case 19 asserts OPEN — must_not_propose goes live), §8 banding with LOW → OPEN-as-question, BSMS linker in assisted mode: bundle retrieval (roles per §14.1) over cleared packs + supplier documents, explainable match basis, derived link_confidence, grader pass, threshold → evidence_absent. Links below threshold are flagged for human verification, not silently dropped.
Done when: linker precision@1 and false-link rate meet the D-2 targets on the frozen held-out set defined by the Evaluation contract; all na_vs_zero_limit cases green; non-cleared documents are provably unavailable to the linker.
### S7 — LLM proposal layer + calibration eval
Build as a thin vertical spike behind a feature flag, gated by a cheap proposability probe first so full proposal-type machinery is only built once the probe clears. Remap proposer (§5, per-unit granularity — case 3), intent statements, voluntary-expansion detection feeding §9.2 (cases 6, 9, 10), definitional exclusion arguments (case 25), narrative checks (cases 12–15). Probabilistic eval harness per §16 (held-out, versioned, distribution-reported), separate from the deterministic CHECK and governed by the Evaluation contract.
Done when: zero false-CW on process-sensitive classes of the golden package (with the false-CW denominator defined by the Evaluation contract); ≥ 60% proposability floor measured (D-2 build-commitment decision point: below floor → v1 ships assisted-only and this slice's proposals stay dark).
### S8 — Outputs + CLI closure
Countersign export (state-preserving, re-import gated, signer identity verified), exception detail, narrative computed from the matrix (case 22), referenced-artifact gating (case 23), advisory labeling on every artifact (D-1), a per-output capability/version declaration (spec version, rule version, and which gates are NOT_IMPLEMENTED), oracle disposition CLI verb finalized, docs.
Done when: full §12 output contract emits in order on the reference corpus; a package with any OPEN/unelected unit refuses release-marking; no summary collapses NOT_IMPLEMENTED gates into an "all gates passed" claim; countersign export re-imports only with a verified signer and consistent stored state.
## Evaluation contract (D-2 preconditions)
Before the slice that consumes a metric runs, its dataset is frozen and cannot be tuned against:
Immutable, versioned train/dev/test manifests with provenance and content hashes.
Independent, blind annotation/adjudication authority (not the implementer); documented inclusion/exclusion rules and class stratification.
Leakage checks (golden parses derived from builtin-pack sources must not overlap held-out evaluation items).
Minimum sample sizes and reported confidence intervals; a metric is not "met" if the interval straddles the threshold.
Every metric reports its complement: recall reports precision/false positives; precision@1 reports false-link; false-CW reports its exact denominator.
Model, retriever, and prompt versions are recorded for each evaluation run.
| Gate | Slice | Frozen set | Reported metrics |
|---|---|---|---|
| Authority recall | S4 | Blind-adjudicated named-authority corpus | recall + precision/false-positive |
| Linker quality | S6 | Held-out link set | precision@1 + false-link |
| Proposal safety | S7 | Golden package (process-sensitive) | false-CW + proposability floor |
## Fixture activation map
| Slice | Cases that become executable assertions |
|---|---|
| S1 | truth-table, count/pointer drift |
| S2 | 3 (unit granularity groundwork), 24 (citation-vs-corpus) |
| S3 | 18 |
| S4 | 1, 16, 26 |
| S5 | 2, 6, 7, 11, 17, 21 (*consistency aspects only; propagation itself is v1.1) |
| S6 | 4, 5, 19, 20 |
| S7 | 3, 8–10, 12–15, 25 |
| S8 | 22, 23 |
By S8, all 26 cases have at least one active assertion; coverage is reported per obligation (fully tested / partial / deferred) so "26/26 active" is never read as "every obligation tested." expert_corrected/expert_discovered regressions merge-block from the slice that activates them.
## Kill-criteria measurement milestones (D-2)
After S4: authority recall/precision on the frozen corpus (threshold pending human decision — see open questions).
After S6: linker precision / false-link on the frozen held-out set.
After S7: false-CW on process-sensitive classes; proposability floor — the build-commitment decision point: below floor, S7's proposals ship dark and v1 is assisted-only, per §16.
Each milestone has a predefined decision owner and a maximum number of retune cycles before it escalates to human adjudication.
## Standing constraints (every slice)
--coverage-floor 80; full suite green; protected paths untouched (spec, run records, fixture — enforced by CHECK, not trust).
Every disposition and export carries schema_version and rule_version.
Graded errata channel (replaces the flat "no slice edits the spec" rule):
Non-semantic fixture/test-harness fixes (typos, pointer drift, comment) are allowed under dual review with a logged rationale.
A spec ambiguity or defect is raised as an errata RFC with a version bump and explicit slice-replay/migration rules; committed dispositions affected by a rule change are recomputed or invalidated per the migration procedure.
Behavioral contract changes hard-stop the slice and route back through review.
Forward-migration and old-export compatibility tests accompany any contract revision.
Commit on APPROVED only; one slice per branch; PIPELINEREPORT.md retained per slice in `oraclebuilds/`.
## Coherence notes from slicing (for the plan review to weigh)
§9.1's cycle-free-propagation gate and the two reserved sub-reasons are unbuilt until v1.1. They are emitted as NOT_IMPLEMENTED / OUT_OF_SCOPE (never trivial PASS) so the gate table stays complete without misrepresenting a control as performed.
Cases 17 and 21 are only partially assertable in v1 (consistency surface, not propagation); the fixture activation map and per-obligation coverage report make this explicit.
Fail-closed behavior (pendingreview, OPEN, §3.2 reopening) requires an operational contract — expected pendingreview rate bands, max OPEN aging, reopen blast-radius scoping, bulk-election UX, and an auditable time-boxed degraded-release waiver — before production use. Specific bands are an open product/operations decision.
## Open decisions requiring human authority (before slice 1)
S4 authority-recall threshold: 100% on the blind-locked corpus, or a stratified target (e.g., ≥95% recall / ≥98% precision) with a residual-error waiver routing overflow to pending_review?
Data-governance policy specifics for S6/S7: approved LLM endpoints, no-training/retention terms, and supplier-document permitted-use rules.
Operational capacity bands: acceptable pending_review rates, OPEN aging limits, and degraded-release waiver authority.
Whether persistence/audit is a standalone slice (S1a) or distributed across S1/S5/S8, given the 200K per-slice gate budget.



This communication and its attachments are privileged and confidential. Generated by ORACLE — BoundState AI LLC.