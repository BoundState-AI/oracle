# ORACLE Review Report

**Document:** /data/sessions/dfbb7a86d3a1/# Disposition v1 — Slice Build Plan.md
**Session:** 20260728-213016
**Rounds:** 1
**Converged:** No

**Consensus:** BLOCKED — stopped without consensus

**Convergence Reason:** This was a single-round pass (hard cap 1). The blind reviews surfaced four independently-corroborated material defects (evaluation-contract rigor, vacuous-gate reporting, durable/auditable state, and data governance) that I have revised the plan to address. However, several of the resolutions require judgment I should not exercise alone: the 100% recall threshold is a compliance safety choice, the supplier-document/LLM data-governance policy needs legal authority, the fail-closed capacity bands are product/operations direction, and whether persistence becomes a new slice affects sequencing and the gate budget. These are domain/product decisions, not polish, so the loop should hand off to a human rather than lock or spin another automated round.

**Reviewer pool:** 4 oracles across 3 vendors (Codex, Fran share openai)

## Metrics

- Accepted critical defects: 3
- Accepted high defects: 4
- Accepted medium defects: n/a (not measured in this workflow)
- Accepted low defects: n/a (not measured in this workflow)
- Total accepted defects: 9
- Total rejected claims: 0
- Preference-only findings: 0
- Unresolved questions: n/a (not measured in this workflow)
- Duplicate count: n/a (not measured in this workflow)
- Total issues raised: n/a (not measured in this workflow)
- Duplicate rate: n/a (not measured in this workflow)
- Rounds to stability: 1
- Converged: False

## Reviewer Verdicts (final round)

- **Codex**: major_revision
- **Fran**: major_revision
- **Gemini**: revise
- **Grok**: revise

## Dissent Summary

> The findings below were raised by reviewer oracles and NOT accepted into the revised draft. The coordinator's reasoning is recorded in full. A rejection is the coordinator's judgment, not a consensus verdict — readers should weigh the reviewer's position themselves.

### [UNRESOLVED QUESTION] 100% authority-recall hard-stop is brittle and gameable (BETH-R1-ISSUE-002, round 1)
**Severity (as raised):** high — confidence (as reported): 0.80
**Raised by:** Gemini, Fran, Codex, contrarian_reviewer
**Corroboration:** cross-vendor (3 independent providers)
**Coordinator reasoning (full):** The 100% recall gate's gameability is a real defect (accepted via dataset-contract fix). But whether to lower the numeric threshold to ~95% with a residual-error waiver is a compliance/product-safety decision I will not make unilaterally; the design already routes ambiguity to pending_review, so the number choice needs domain authority. Flagged for human review.

## Round 1

### [CRITICAL] Kill-criteria have no frozen, independently-adjudicated evaluation contract (BETH-R1-ISSUE-001)
**Confidence (as reported):** 0.95
**Sources:** Fran, Codex, Gemini, contrarian_reviewer
**Corroboration:** cross-vendor (3 independent providers)

### [CRITICAL] Vacuous v1.1 gates can be reported as passed controls (BETH-R1-ISSUE-003)
**Confidence (as reported):** 0.93
**Sources:** Codex, Fran, contrarian_reviewer
**Corroboration:** cross-vendor (2 independent providers)

### [CRITICAL] Release state has no durable, concurrency-safe, auditable implementation (BETH-R1-ISSUE-004)
**Confidence (as reported):** 0.90
**Sources:** Codex

### [HIGH] Human approval and countersign lack identity/audit contract (BETH-R1-ISSUE-005)
**Confidence (as reported):** 0.88
**Sources:** Codex

### [HIGH] Supplier-document and LLM processing has no compliance control plane (BETH-R1-ISSUE-006)
**Confidence (as reported):** 0.85
**Sources:** Fran

### [HIGH] Fail-closed design lacks a human-throughput / degraded-release ops model (BETH-R1-ISSUE-007)
**Confidence (as reported):** 0.82
**Sources:** contrarian_reviewer

### [HIGH] S2 extractor extension vs. frozen pack outputs is an unresolved coupling bet (BETH-R1-ISSUE-008)
**Confidence (as reported):** 0.80
**Sources:** contrarian_reviewer

### [HIGH] 100% authority-recall hard-stop is brittle and gameable (BETH-R1-ISSUE-002)
**Confidence (as reported):** 0.80
**Sources:** Gemini, Fran, Codex, contrarian_reviewer
**Corroboration:** cross-vendor (3 independent providers)

### [MEDIUM] Protected-contract policy lacks an evolution/migration and clarification path (BETH-R1-ISSUE-009)
**Confidence (as reported):** 0.82
**Sources:** Codex, contrarian_reviewer
**Corroboration:** cross-vendor (2 independent providers)

### [MEDIUM] S1 'no I/O' contradicts fixture-harness activation (BETH-R1-ISSUE-010)
**Confidence (as reported):** 0.85
**Sources:** Gemini

### Coordinator Decisions
- **BETH-R1-ISSUE-001**: accepted_defect — All four reviewers independently flagged that D-2 kill-criteria are used as go/no-go decisions but lack dataset contracts (freeze-before-implementation, annotation authority, leakage controls, sample 
- **BETH-R1-ISSUE-002**: unresolved_question — The 100% recall gate's gameability is a real defect (accepted via dataset-contract fix). But whether to lower the numeric threshold to ~95% with a residual-error waiver is a compliance/product-safety 
- **BETH-R1-ISSUE-003**: accepted_defect — Three reviewers (Codex critical, Fran high, Grok medium) converged: trivially-passing v1.1 gates are indistinguishable from real controls in the release record. In a compliance/release system this is 
- **BETH-R1-ISSUE-004**: accepted_defect — Codex correctly identified that the plan defines a release state machine as pure functions but assigns durable storage, atomicity, concurrency, and recovery to no slice. A compliance disposition canno
- **BETH-R1-ISSUE-005**: accepted_defect — Human elections and countersign are the most audit-sensitive surface yet had no actor-identity, permission, or immutable-audit contract. Added authenticated actor identity, transition permissions, and
- **BETH-R1-ISSUE-006**: accepted_defect — Fran is right that supplier-document retrieval and LLM processing have no compliance control plane; advisory labels do not address data-processing obligations. Added a data-governance precondition. Th
- **BETH-R1-ISSUE-007**: accepted_defect — Grok's fail-closed-without-capacity observation is a legitimate operational risk (queue explosion, reopen storms, deadlocked-but-correct releases). Added a requirement to define an ops/throughput cont
- **BETH-R1-ISSUE-008**: accepted_defect — Grok's coupling concern is plausible and material: extending shall_extractor while forbidding any pack-output change likely forces hidden dual codepaths or deadlocks the protected-fixture rule on the 
- **BETH-R1-ISSUE-009**: accepted_defect — Codex and Grok both noted the protected-contract policy has no evolution/migration path and treats typos identically to behavioral defects, guaranteeing multi-day stalls or route-arounds. Added schema
- **BETH-R1-ISSUE-010**: accepted_defect — Gemini's 'no I/O' vs. fixture-harness contradiction is a minor but real clarity defect. Clarified that domain logic stays pure/side-effect-free and only the harness performs read-only fixture loading.

## Open Questions

- Should the S4 authority-recall gate stay at 100% on a blind-locked corpus, or drop to a stratified target (e.g., ≥95% recall / ≥98% precision) with a documented residual-error waiver? (compliance decision)
- What are the approved LLM endpoints, no-training/retention terms, and supplier-document permitted-use rules for S6/S7? (legal/product)
- What are the acceptable pending_review rate bands, max OPEN aging, and degraded-release waiver authority? (operations/product)
- Is durable persistence a standalone slice (S1a) or distributed across S1/S5/S8, and does it fit the 200K per-slice gate budget?
