# ORACLE Review Report

**Document:** /data/sessions/db51f2208b7d/ORACLE_DISPOSITION_SPEC.md
**Session:** 20260728-191953
**Rounds:** 2
**Converged:** No

**Consensus:** BLOCKED — stopped without consensus

**Convergence Reason:** This is round 2 of a 2-round hard cap, so the final-round policy forbids ONE_MORE_ROUND and requires LOCK or HUMAN_REVIEW. The structural defects are converging: round 2 surfaced real, non-duplicative issues (universal human-confirmation gate for CW/NA, incomplete roll-up truth table, horizon fail-open, over-broad cycle halt, capability-model input trust, extraction/unitization layer, pipeline rights), several of which are bugs the R1 fixes themselves introduced — and I have resolved all of these in spec text. LOCK is not appropriate because the remaining blockers are genuine domain/legal/product decisions the spec cannot self-resolve and must not proceed past: the safety-critical/compliance posture (still asserted, now marked TARGET/UNSUBSTANTIATED), the numeric MVP kill-criteria, and corpus/BYOL/fixture licensing. The spec is implementation-ready in structure but carries claims and feasibility gates that require human authority before build. Route the revised spec plus the enumerated open questions to a human owner.

**Reviewer pool:** 4 oracles across 3 vendors (Codex, Fran share openai)

## Metrics

- Accepted critical defects: 4
- Accepted high defects: 13
- Accepted medium defects: n/a (not measured in this workflow)
- Accepted low defects: n/a (not measured in this workflow)
- Total accepted defects: 25
- Total rejected claims: 1
- Preference-only findings: 1
- Unresolved questions: n/a (not measured in this workflow)
- Duplicate count: n/a (not measured in this workflow)
- Total issues raised: n/a (not measured in this workflow)
- Duplicate rate: n/a (not measured in this workflow)
- Rounds to stability: 2
- Converged: False

- Issue-ID continuity across rounds: 0%

## Data Integrity Warnings

> 7 coordinator decision(s) reference issue IDs with no matching normalized issue: BETH-R1-ISSUE-014, BETH-R1-ISSUE-015, BETH-R2-ISSUE-007, BETH-R2-ISSUE-009, BETH-R2-ISSUE-012, BETH-R2-ISSUE-013, BETH-R2-ISSUE-014. Severity counts above may be incomplete for these decisions.

## Reviewer Verdicts (final round)

- **Codex**: major_revision
- **Fran**: major_revision
- **Gemini**: major_revision
- **Grok**: major_revision

## Dissent Summary

> The findings below were raised by reviewer oracles and NOT accepted into the revised draft. The coordinator's reasoning is recorded in full. A rejection is the coordinator's judgment, not a consensus verdict — readers should weigh the reviewer's position themselves.

### [UNRESOLVED QUESTION] Compliance and safety-critical claims remain present-tense and unsubstantiated (BETH-R2-ISSUE-010, round 2)
**Severity (as raised):** critical — confidence (as reported): 0.95
**Raised by:** Fran, Codex, Grok
**Corroboration:** cross-vendor (2 independent providers)
**Coordinator reasoning (full):** Fran, Codex, and Grok all reiterate that the header asserts present-tense SWE-013/033, NASA-STD-8739.8B, and Safety Critical: True while §17 admits the assurance case is undecided. Strengthened header language to mark these as TARGET/UNSUBSTANTIATED pending the §17 decision (a truthfulness fix), but the posture decision itself — full assurance case vs advisory-only scoping — requires domain authority and is routed to HUMAN_REVIEW.

### [UNRESOLVED QUESTION] No numeric MVP kill-criteria for the load-bearing NLP subsystems (BETH-R2-ISSUE-011, round 2)
**Severity (as raised):** high — confidence (as reported): 0.82
**Raised by:** Grok
**Coordinator reasoning (full):** Grok wants published numeric MVP kill-criteria (max false-CW on process-sensitive classes, min authority recall, max false-link, max %OPEN on a golden package). The requirement to define and gate on such thresholds before build is spec-appropriate and was added to §16; the specific numbers are a product/domain calibration decision and are routed to HUMAN_REVIEW.

### [REJECTED BY COORDINATOR] BETH-R2-ISSUE-014 (BETH-R2-ISSUE-014, round 2)
**Coordinator reasoning (full):** Grok's regression/fixture-generalization finding restates R1 BETH-R1-ISSUE-015: the spec already requires cross-domain smoke cases and adversarial fixtures before merge-block trust, and fixture rights is already a BLOCKING open question. The residual ('resolve fixture legality before implementation') is a legal decision already routed to human authority; no new spec change is warranted.

## Round 1

### [CRITICAL] MI/EX customer-acceptance lifecycle is not representable or gated (BETH-R1-ISSUE-001)
**Confidence (as reported):** 0.97
**Sources:** Codex, Fran
**Corroboration:** same-vendor — all corroborating reviewers share provider 'openai'; same-model agreement is weaker evidence than cross-vendor agreement

### [CRITICAL] Disposition granularity is internally contradictory (BETH-R1-ISSUE-002)
**Confidence (as reported):** 0.98
**Sources:** Fran, Codex
**Corroboration:** same-vendor — all corroborating reviewers share provider 'openai'; same-model agreement is weaker evidence than cross-vendor agreement

### [HIGH] Fixpoint propagation is unbounded, cycle-unsafe, and non-deterministic (BETH-R1-ISSUE-003)
**Confidence (as reported):** 0.90
**Sources:** Gemini, Grok, Codex
**Corroboration:** cross-vendor (3 independent providers)

### [HIGH] Authority detection cannot meet its completeness guarantee (BETH-R1-ISSUE-004)
**Confidence (as reported):** 0.88
**Sources:** Gemini, Codex, Fran, Grok
**Corroboration:** cross-vendor (3 independent providers)

### [HIGH] Mandatory verbatim reproduction with unresolved redistribution rights (BETH-R1-ISSUE-005)
**Confidence (as reported):** 0.85
**Sources:** Codex, Fran, Grok
**Corroboration:** cross-vendor (2 independent providers)

### [HIGH] Cross-standard traversal can manufacture false obligations or explode scope (BETH-R1-ISSUE-006)
**Confidence (as reported):** 0.87
**Sources:** Fran, Gemini, Grok
**Corroboration:** cross-vendor (3 independent providers)

### [HIGH] Safety-critical / compliance claims unsupported by the design (BETH-R1-ISSUE-007)
**Confidence (as reported):** 0.85
**Sources:** Fran, Grok
**Corroboration:** cross-vendor (2 independent providers)

### [HIGH] Regression gate is not reproducible (BETH-R1-ISSUE-008)
**Confidence (as reported):** 0.90
**Sources:** Codex, Grok
**Corroboration:** cross-vendor (2 independent providers)

### [HIGH] Load-bearing evidence matching is unsolved but release-gated (BETH-R1-ISSUE-009)
**Confidence (as reported):** 0.85
**Sources:** Grok, Codex
**Corroboration:** cross-vendor (2 independent providers)

### [HIGH] Levied revision can drift into the wrong compliance obligation (BETH-R1-ISSUE-010)
**Confidence (as reported):** 0.90
**Sources:** Codex

### [MEDIUM] Flat verbatim string cannot carry tables/formulas or errata (BETH-R1-ISSUE-011)
**Confidence (as reported):** 0.78
**Sources:** Gemini

### [MEDIUM] OPEN-as-universal-gate lacks a campaign lifecycle (BETH-R1-ISSUE-012)
**Confidence (as reported):** 0.78
**Sources:** Grok

### [MEDIUM] Frame contradiction: 'no engineering judgment' vs remap IP (BETH-R1-ISSUE-013)
**Confidence (as reported):** 0.75
**Sources:** Grok

### Coordinator Decisions
- **BETH-R1-ISSUE-001**: accepted_defect — Codex and Fran independently found the same critical gap: §2.2/§2 require customer acceptance for MI/EX and §11.1 propagates on 'accepted' EX/MI, but §7 has no acceptance-state, accepting authority, d
- **BETH-R1-ISSUE-002**: accepted_defect — Fran and Codex found a genuine internal contradiction: §1.1/§9.1 mandate exactly one code per requirement while §5.1 requires remaps per subparagraph and §7 examples use subparagraph IDs. Defined the 
- **BETH-R1-ISSUE-003**: accepted_defect — Gemini, Grok, and Codex converged on the §11.1 fixpoint hazard: no cycle detection, no depth bound, no determinism guarantee, and silent OPEN thrash of previously human-confirmed rows. Standards graph
- **BETH-R1-ISSUE-004**: accepted_defect — All four reviewers flagged token-scan authority detection as unable to guarantee completeness in the named highest-consequence failure mode. Added a fail-closed rule (ambiguous approval language force
- **BETH-R1-ISSUE-005**: accepted_defect — Codex, Fran, and Grok all identified that §7 mandates verbatim controlled-standard text and §12 emits it while §14.4/§14.7 leave rights as open questions. Promoted rights classification to a blocking 
- **BETH-R1-ISSUE-006**: accepted_defect — Fran, Gemini, and Grok found that §11 assumes every outbound reference creates an applicable obligation, with no normative-vs-informative distinction, applicability predicate, or recursion bound — pro
- **BETH-R1-ISSUE-007**: accepted_defect — Fran and Grok found the Safety-Critical/SWE-013/033/NASA-STD-8739.8B claims unsupported by any specified control mechanism (no immutable audit, role authorization, signature control, retention, change
- **BETH-R1-ISSUE-008**: accepted_defect — Codex and Grok correctly noted §16 calls CHECK deterministic pytest while §5/§8/§14.1 require model-derived proposals, so identical inputs may yield different dispositions and the merge gate is not re
- **BETH-R1-ISSUE-009**: accepted_defect — Grok (and Codex on testability) correctly identified that evidence matching is the load-bearing subsystem yet §14.1 leaves it unsolved while CW/MI release-gate on trustworthy evidence. Made evidence l
- **BETH-R1-ISSUE-010**: accepted_defect — Codex found a real correctness defect: §1 treats input as a controlled standard while §11 requires citing referenced standards at 'current issuance,' conflating the contractually levied revision with 
- **BETH-R1-ISSUE-011**: accepted_defect — Gemini's point that requirement_text as a flat str cannot represent tables/formulas and misses errata/change notices is valid and partially overlaps the levy-manifest fix. Allowed structured requireme
- **BETH-R1-ISSUE-012**: accepted_defect — Grok's workflow point is a real product-fit gap: OPEN-heavy first passes with no staged package lifecycle will drive teams to bypass the tool or pressure for bulk-accept (an explicit defect). Added pa
- **BETH-R1-ISSUE-013**: accepted_defect — Grok's frame-contradiction (§1.2 'no engineering judgment' vs §5 remap as core IP) has real validation-scoping consequence. Reworded §1.2 to 'bounded judgment support with mandatory human disposition'
- **BETH-R1-ISSUE-014**: preference_only — Gemini's proposed fix to replace token scanning with LLM-based extraction is reasonable but is one implementation among several; the accepted defect (BETH-R1-ISSUE-004) is the missing completeness/fai
- **BETH-R1-ISSUE-015**: accepted_defect — Grok's regression-overfit concern (26 cases, one process, two standards elevated to merge-block) is a legitimate testability risk. Added a requirement for cross-domain smoke cases and adversarial fixt

## Round 2

### [CRITICAL] Release controls do not enforce human disposition for CW/NA (BETH-R2-ISSUE-001)
**Confidence (as reported):** 0.96
**Sources:** Fran, Codex
**Corroboration:** same-vendor — all corroborating reviewers share provider 'openai'; same-model agreement is weaker evidence than cross-vendor agreement

### [HIGH] Parent roll-up cannot produce a valid code for mixed children (BETH-R2-ISSUE-002)
**Confidence (as reported):** 0.95
**Sources:** Codex, Grok
**Corroboration:** cross-vendor (2 independent providers)

### [CRITICAL] Relevance horizon silently omits applicable normative obligations (BETH-R2-ISSUE-003)
**Confidence (as reported):** 0.93
**Sources:** Fran

### [HIGH] Cycle-halt over-blocks on naturally cyclic reference graphs (BETH-R2-ISSUE-004)
**Confidence (as reported):** 0.90
**Sources:** Gemini

### [HIGH] Capability-model intake is input-trust-weak (NA laundering) (BETH-R2-ISSUE-005)
**Confidence (as reported):** 0.86
**Sources:** Grok

### [HIGH] Requirement extraction/unitization is an unspecified foundational layer (BETH-R2-ISSUE-006)
**Confidence (as reported):** 0.85
**Sources:** Grok

### [HIGH] Content-rights control does not cover the processing pipeline (BETH-R2-ISSUE-008)
**Confidence (as reported):** 0.84
**Sources:** Fran, Gemini
**Corroboration:** cross-vendor (2 independent providers)

### [CRITICAL] Compliance and safety-critical claims remain present-tense and unsubstantiated (BETH-R2-ISSUE-010)
**Confidence (as reported):** 0.95
**Sources:** Fran, Codex, Grok
**Corroboration:** cross-vendor (2 independent providers)

### [HIGH] No numeric MVP kill-criteria for the load-bearing NLP subsystems (BETH-R2-ISSUE-011)
**Confidence (as reported):** 0.82
**Sources:** Grok

### Coordinator Decisions
- **BETH-R2-ISSUE-001**: accepted_defect — Fran and Codex independently found that the R1 acceptance fix covered MI/EX only. §7.1 still lets a machine-proposed CW (and NA) become release-eligible on evidence alone, with no unit/package release
- **BETH-R2-ISSUE-002**: accepted_defect — Codex (high) and Grok (medium) correctly identified a bug introduced by the R1 roll-up rule: mixed CW+NA children have no defined parent result, and 'renders as an exception' is not one of the five co
- **BETH-R2-ISSUE-003**: accepted_defect — Fran found a hole in the R1 horizon fix: §11 said references beyond the configured horizon 'do not generate OPEN rows,' which lets a normative incorporation be silently dropped by a resource limit. Co
- **BETH-R2-ISSUE-004**: accepted_defect — Gemini correctly noted the R1 cycle fix over-blocks: standards citation graphs are naturally cyclic, so halting on any reference-graph cycle destroys automation value. Clarified §11.1 that the acyclic
- **BETH-R2-ISSUE-005**: accepted_defect — Grok identified a genuine unaddressed input-trust gap: the NA-vs-zero-limit control depends on capability_model.physically_possible flags a supplier can mis-mark to launder audit exposure — the exact 
- **BETH-R2-ISSUE-006**: accepted_defect — Grok correctly flagged that the entire disposition edifice rests on an unspecified extraction/unitization/OCR layer; wrong unit boundaries make every gate theater and frozen hierarchical IDs churn whe
- **BETH-R2-ISSUE-007**: accepted_defect — Gemini's BYOL point has real product-fit merit: locator-only fallback for uncleared standards breaks side-by-side review. Clarified the rights model to distinguish redistribution (still gated) from ve
- **BETH-R2-ISSUE-008**: accepted_defect — Fran correctly extended the R1 rights fix, which covered storage/render only. Controlled content still flows through OCR, indexes, logs, caches, model-provider inference, evaluation, and fixture creat
- **BETH-R2-ISSUE-009**: accepted_defect — The concrete, cheap parts of Grok's automation-bias finding are real anti-bypass controls consistent with the spec's own bulk-accept prohibition: link/confidence thresholds versioned immutably per run
- **BETH-R2-ISSUE-010**: unresolved_question — Fran, Codex, and Grok all reiterate that the header asserts present-tense SWE-013/033, NASA-STD-8739.8B, and Safety Critical: True while §17 admits the assurance case is undecided. Strengthened header
- **BETH-R2-ISSUE-011**: unresolved_question — Grok wants published numeric MVP kill-criteria (max false-CW on process-sensitive classes, min authority recall, max false-link, max %OPEN on a golden package). The requirement to define and gate on s
- **BETH-R2-ISSUE-012**: accepted_defect — Gemini's latency concern is partly valid: §13's synchronous framing invites rate-limit failures. Reframed the proposal pass as an asynchronous background job and stated the numeric targets are per-uni
- **BETH-R2-ISSUE-013**: accepted_defect — Grok's concrete additions are worthwhile: added a first-class 'export working matrix for external countersign' path that preserves non-releasable status (§12), aligning with the existing non-release p
- **BETH-R2-ISSUE-014**: rejected_claim — Grok's regression/fixture-generalization finding restates R1 BETH-R1-ISSUE-015: the spec already requires cross-domain smoke cases and adversarial fixtures before merge-block trust, and fixture rights

## Open Questions

- Safety-critical assurance posture: commit to the full §17 assurance case or scope the header claim to advisory software? Domain authority required.
- Numeric MVP kill-criteria (max false-CW on process-sensitive classes, min authority recall, max false-link rate, max %OPEN on a golden package): product/domain calibration required before build commitment.
- Corpus/prime-overlay licensing, the BYOL tenant-display model, and fixture confidentiality: legal sign-off required before ingestion or CI publication.
- External-system integration/adapter contracts (customer acceptance registries, authority registries, overlay corpora, pointer-only mode): design owed before propagation/release machinery is built.
- v1 scope phasing (defer deep reference walking, derived-SD minting, propagation fixpoints vs ship assisted matrix + gates first): product direction.
- Final module placement and name (MIRA vs oracle-repo collision): resolve before the build pipeline targets a repo.
