# Requirements Disposition Workbench (RDW) — Product & Technical Specification

**Version:** 0.2.0 (reconciled draft — awaiting targeted ORACLE pass + domain approval)
**Status:** Product specification. Pairs with the engine contract:
`docs/ORACLE_DISPOSITION_SPEC.md` (v0.5.0, protected) — re-based onto this
spec's axis model via `docs/ERRATA_RFC_001_AXIS_MODEL.md` (pending approval).
**Classification:** BoundState Proprietary
**Provenance:** Derived from *Requirements_Disposition_Workbench_Spec_v0.1*
(2026-07-30), authored from the live NASA-STD-6030/6033 cold-spray
supplier-disposition engagement. Customer identifiers scrubbed per D-3; the
named original stays in engagement records outside this repo.
**Initial rule packs:** NASA-STD-6030 (115 AMRs, builtin) + NASA-STD-6033 (31 EFCRs).

> **Design position:** the system supports compliance judgment; it never
> becomes the approval authority. Every conclusion remains traceable to
> source text, project facts, evidence, assumptions, and a human decision.

**v0.2 reconciliation:** content marked *(v0.2)* was added when merging the
v0.1 product spec with the engine contract's invariants. Everything else is
v0.1 content, scrubbed. Two-layer architecture: **RDW (this document)** owns
the user-facing model — axes, interview, evidence, exports; the **engine
contract** owns the invariants — provenance rules, gates, regression
machinery, assurance posture. Where they overlap, this spec defers to the
engine contract's rule by explicit reference.

---

## 1. Executive summary

RDW converts standards and contractual requirements into a controlled,
one-requirement-at-a-time interview. It presents authoritative text,
identifies the obligated actor and triggering conditions, asks only for
missing facts, evaluates dependencies, proposes a disposition, and drafts
the matrix comment and closure action. The initial implementation is seeded
by the 6030/6033 cold-spray supplier-compliance exercise but accepts
additional standards and contract rule packs.

The product must prevent the recurring compliance failure in which
applicability, organizational responsibility, implementation status, and
approval state are collapsed into a single ambiguous value. RDW stores those
concepts separately, then maps them into whatever customer-facing matrix
format is required.

## 2. Problem statement

Compliance matrices often reduce a complex decision to Meet, Meets Intent,
or N/A. That is insufficient when a requirement applies to a program but is
performed by another organization; when implementation depends on missing
customer inputs; when an alternate method constitutes proposed tailoring; or
when a supplier can demonstrate only part of a multi-tier obligation.

- Requirement text is copied without preserving actor, trigger, rationale,
  or cross-reference context.
- Missing information is silently converted into N/A or an unsupported claim
  of compliance.
- A supplier matrix is mistaken for an approved control plan or tailoring
  authorization.
- Downstream requirements are closed even when prerequisite classifications
  or approvals remain unresolved.
- Evidence is requested late, inconsistently, or not at all.

> **Failure to prevent:** a polished compliance matrix that cannot survive
> technical, contractual, customer, or regulatory review.

*(v0.2)* The reference-run fixture documents these failures empirically: its
hardest cases are axis-collapse errors (case 1: applicability, actor, and
approval crushed into one code; case 12: part class conflated with fracture
classification). The axis model in §7 is the structural fix.

## 3. Objectives and non-objectives

### 3.1 Objectives

- Preserve exact, revision-controlled requirement text with page, section,
  and source traceability.
- Guide a user through requirements one at a time using the minimum
  unresolved factual question.
- Separate applicability, obligated actor, supplier responsibility,
  conformance, and approval state.
- Maintain a dependency graph across requirements and across standards.
- Generate defensible comments, evidence requests, assumptions, risks,
  actions, and owners.
- Export an Appendix-style matrix, supplier disposition matrix, evidence
  register, and open-action register.
- Support human review and approval of every disposition and every
  generated statement.

### 3.2 Non-objectives

- RDW will not approve tailoring, accept risk, assign design authority, or
  replace the cognizant engineering organization.
- RDW will not infer compliance solely from an organizational certification
  such as AS9100.
- RDW will not treat absence of evidence as evidence of non-applicability.
- RDW will not alter authoritative source text or present paraphrase as the
  governing requirement.
- The MVP will not autonomously issue contractual correspondence or modify
  controlled customer records.

## 4. Governing design principles

| Principle | Meaning |
|---|---|
| Source first | Show the exact clause before interpretation. Preserve standard, revision, section, page, and extraction provenance. |
| Actor aware | Parse the subject of each shall statement and distinguish program, CEO, producer, supplier, subtier, and test organization. |
| Condition aware | Represent triggers such as Class A, flight hardware, fracture control, or use of a specific process. |
| Evidence bounded | A claim may not exceed the evidence supplied. Certification scope, document revision, and approval status are explicit. |
| No false closure | Unknown inputs remain TBD. Missing controls remain Open/Not Met. Proposed alternatives are not silently labeled compliant. |
| Human approved | Machine-generated interpretations and comments remain proposed until accepted by an authorized reviewer. |
| Export compatible | Internal truth remains richer than customer templates; export mappings must never delete the underlying rationale. |

## 5. Users and roles

| Role | Responsibility |
|---|---|
| Disposition author | Works through requirements, supplies facts, proposes status, attaches evidence. |
| Technical reviewer | Validates interpretation, technical sufficiency, dependencies, generated comments. |
| Quality reviewer | Validates QMS implementation, document control, supplier controls, objective evidence. |
| Program/CEO reviewer | Confirms actor allocation, classification, tailoring, acceptance, retained responsibilities. |
| Administrator | Loads standards, manages rule-pack revisions, permissions, templates, controlled vocabularies. |
| Auditor/read-only | Reviews lineage from exported conclusion to requirement, facts, evidence, decisions, approvals. |

*(v0.2)* v1 operates single-operator: one human may hold several roles, but
every role-bearing action records which role was exercised, so the audit
trail is multi-role-ready (engine contract §17 authorization model).

## 6. End-to-end workflow

1. Import a standard, contract, customer specification, or prebuilt rule pack.
2. Extract and review each normative requirement, actor, trigger, rationale,
   cross-reference, and dependency.
3. Create a project context: organizations, assumed CEO, hardware, process,
   lifecycle state, subtiers, governing documents, known classifications.
4. Open the next unresolved requirement. Display exact source text and a
   clearly labeled plain-language explanation.
5. Apply known context and dependency states. Ask one targeted question for
   the highest-value missing fact.
6. Record the user answer as an asserted fact, attach evidence when
   available, preserve source/author/time.
7. Compute the allowed disposition states and explain why unsupported states
   are blocked.
8. Generate a proposed comment, evidence list, closure action, owner, due
   status.
9. Require human acceptance before the row is considered reviewed.
10. Propagate relevant changes through dependent requirements and flag
    conclusions requiring re-review.
11. Run consistency and completeness checks, then export the required matrix
    and supporting registers.

## 7. Core disposition model — independent axes

RDW shall not use a single status field as its system of record. The
internal model uses independent axes. Customer-facing labels are derived
views.

| Axis | Allowed values | Purpose |
|---|---|---|
| Applicability | Yes / No / TBD | Whether the requirement applies to the program, hardware, process, or activity. |
| Obligated actor | Program / CEO / producer / supplier / subtier / other | Who owns the normative action. |
| Organization responsibility | Owner / support / external / TBD | What the evaluated organization must perform. |
| Implementation | Meets as written / alternate proposed / partial / not met / TBD | Actual conformance to the requirement. |
| Approval | Not required / required / draft / submitted / approved / rejected / TBD | Whether external acceptance or tailoring approval exists. |
| Review | Not reviewed / proposed / reviewed / accepted / superseded | Human workflow state. |

*(v0.2)* **TBD reasons are a closed vocabulary**, inherited and extended
from the engine contract §2.3: `evidence_absent`, `customer_input_missing`
(née scope_decision_not_made), `authority_unidentified`,
`approval_not_exercised`, `referenced_artifact_missing`,
`referenced_standard_unavailable`, `reference_semantics_unresolved`,
`dependency_eliminated`, `classification_unresolved` *(new)*. Every TBD on
any axis carries exactly one reason. Extending the vocabulary is a spec
revision.

*(v0.2)* **The Review axis is the engine contract's workflow_state machine**
(§7.1: machine may set only proposed; human election required for every
non-proposed transition; release gates unchanged). S1's implementation
carries over.

### 7.1 Export mapping (derived views — never the system of record)

| Customer label | Axis condition |
|---|---|
| Meet | applicability Yes; implementation Meets as written; required approvals complete or not required |
| Meets Intent | applicability Yes; alternate implementation proposed; tailoring/exception approval action created when required |
| N/A | applicability No, supported by a positive scope or trigger rationale |
| TBD | one or more facts required to decide applicability or conformance are unresolved |
| Open/Not Met | the requirement applies and the required control or evidence is absent |
| Exception | relief from the as-written requirement is explicitly proposed; approval tracked separately |

*(v0.2)* **Mapping guards (engine-contract imports, mandatory):**

1. **No exception softening (fixture case 8):** a row whose axes encode
   requested relief (alternate proposed / approval required) shall never
   export under a compliance heading. Meets Intent renders under the
   exception heading, never the compliance heading (engine §2.2), and a
   mapping that would relabel an Exception as Meets Intent is a blocking
   defect.
2. **Voluntary-expansion guard (engine §10, case 9):** every control emitted
   in a comment or evidence plan is classed `integral` (supports the stated
   disposition; enters the contractual baseline) or `disclosed` (visibility
   only; renders with an explicit non-binding statement). A requirement
   whose applicability is No shall not simultaneously be "adopted
   voluntarily" in the export.
3. **Export truth table:** a deterministic test enumerates the axis
   combinations and asserts each maps to exactly one label or one named
   contradiction (§14 gate) — same discipline as the engine's roll-up badge
   truth table (§1.1/§16).
4. **The engine contract's five codes** (CW/MI/EX/NA/OPEN) are themselves a
   derived view under this mapping (CW≈Meet, MI≈Meets Intent, EX≈Exception,
   NA≈N/A, OPEN≈TBD, with Open/Not Met as the state the five-code model
   could not express). The regression fixture's per-case codes translate
   through this mapping; regression semantics are unchanged (see
   ERRATA_RFC_001).

## 8. Functional requirements

| ID | Capability | Requirement |
|---|---|---|
| FR-001 | Source ingestion | Import PDF, DOCX, XLSX, and structured rule packs without modifying source bytes. |
| FR-002 | Requirement extraction | Extract normative statements with identifier, exact text, section, page, actor, trigger, rationale, notes, cross-references. |
| FR-003 | Extraction review | Require human confirmation before extracted requirements become an approved rule-pack revision. |
| FR-004 | Project context | Capture organizations, CEO assumption, hardware scope, process, flight status, subtiers, governing plans, customer inputs. |
| FR-005 | Requirement interview | Present one requirement at a time and ask one prioritized unresolved question. |
| FR-006 | Fact ledger | Record asserted, inferred, and evidenced facts separately with author, time, source, confidence band, supersession history. |
| FR-007 | Actor allocation | Identify the shall-statement actor and the evaluated organization's owner/support/external relationship. |
| FR-008 | Dependency graph | Represent prerequisites and propagate changed facts or statuses to dependent requirements. |
| FR-009 | Disposition guardrails | Block Meet, Meets Intent, or N/A when mandatory facts, evidence, or approvals are absent. |
| FR-010 | Evidence management | Attach controlled files, references, certificate scope, revision, effective date, approval, expiration. |
| FR-011 | Comment generation | Generate concise matrix language from approved facts without exceeding the evidence. |
| FR-012 | Action management | Create closure actions with owner, requested artifact, due state, affected requirements. |
| FR-013 | Review workflow | Support proposed, reviewed, accepted, rejected, superseded decisions with comments and identity. |
| FR-014 | Consistency checks | Detect conflicts, circular assumptions, unsupported closure, stale evidence, dependency violations. |
| FR-015 | Exports | Produce Appendix-style matrix, supplier matrix, evidence register, assumptions log, open-action register in DOCX/XLSX. |
| FR-016 | Revision impact | Compare rule-pack revisions and identify requirement records requiring re-evaluation. |
| FR-017 | Audit view | Navigate from any exported row to the exact clause, facts, evidence, reasoning, approvals, history. |
| FR-018 | Template mapping | Map internal axes to customer-specific columns without discarding system-of-record data. |

## 9. Information model

### 9.1 Requirement record

| Group | Fields |
|---|---|
| Identity | requirement_id, rule_pack_id, standard, revision, section, page, source_hash |
| Authority | exact_text, normative_verb, actor, object, conditions, exceptions |
| Context | rationale, notes, definitions, examples, cross_references |
| Logic | dependencies, mutually_exclusive_states, required_evidence_types, approval_rules |
| Provenance | extraction_method, extracted_by, reviewed_by, review_time, source_coordinates |

*(v0.2)* Requirement records are pinned to an immutable **levy manifest**
(engine §1.1): dispositions are computed against the levied revision only; a
newer issuance is a drift finding requiring a new run, never a silent
substitution. Extraction/unitization follows engine §7.3 (human boundary
confirmation, stable hierarchical IDs, golden parses).

### 9.2 Project context

| Group | Fields |
|---|---|
| Organizations | customer, program/project, assumed CEO, producer, suppliers, subtiers |
| Hardware | part/subassembly, function, interfaces, material, process, lifecycle, flight status |
| Classification | primary class, secondary class, fracture-control status, hazard/mission criticality |
| Plans | AMCP, EFCP, QMP, PPP, qualification plans, inspection/NDE plans |
| Supply chain | powder, testing, heat treatment/HIP, machining, NDT/NDE, special processes |
| Assumptions | statement, owner, basis, confidence band, confirmation needed, affected requirements |

*(v0.2)* The engine contract's capability model (§3.1) is a mandatory
sub-record of project context: physical-impossibility claims require
evidenced capability entries and fail closed to human adjudication (§6.1) —
the NA-vs-zero-limit distinction operates on the Applicability axis.

### 9.3 Disposition record

| Group | Fields |
|---|---|
| Decision axes | applicability, obligated_actor, organization_responsibility, implementation_state, approval_state |
| Basis | approved facts, assumptions, interpretations, dependency states, evidence references |
| Outputs | plain-language explanation, proposed comment, evidence needed, action, owner |
| Workflow | author, reviewer, approver, timestamps, current state, superseded version |
| Confidence | high / medium / low band plus explicit reason; confidence never substitutes for evidence |

## 10. Decision and dependency engine

The decision engine combines deterministic rules with language-model
assistance. Deterministic logic controls allowed states, prerequisites,
status propagation, and approval requirements. The language model extracts
candidate structure, explains clauses, selects questions, interprets
answers, and drafts comments. **It may propose but may not silently override
a deterministic block.**

*(v0.2)* The language service is the deterministic grounded-retrieval (BSMS)
architecture per engine §14.1 and decision D-7: evidence bundles with roles,
explainable match basis, grader pass on every draft, no vector store.

### 10.1 Minimum decision rules

- N/A requires a positive rationale tied to scope, trigger, actor
  allocation, or an approved exclusion.
- TBD is required when a decision depends on an unresolved customer/program
  input.
- Open/Not Met is required when applicability is established and a mandatory
  control is absent.
- Meets Intent or alternate proposed must create an approval check whenever
  the alternative changes an as-written requirement.
- A supplier certification cannot close requirements imposed on every
  relevant subtier.
- External responsibility does not make a program requirement inapplicable;
  those states are stored separately.
- A change to a prerequisite fact marks dependent accepted dispositions for
  re-review.
- An approved plan or tailoring record must carry identity, revision,
  approver, approval date, and scope before it can satisfy an approval gate.

### 10.2 Dependency propagation *(v0.2: engine-grade rigor imported)*

Example: while primary classification remains TBD, class-specific
requirements remain conditional. A Class A assignment activates quantitative
NDE and special-NDE requirements. A later change from Class B to Class A
invalidates previously accepted N/A determinations for Class A controls and
returns them to review.

Propagation inherits the engine contract §11.1 discipline verbatim:
committed-trigger only (accepted facts/decisions propagate; proposals do
not), immutable per-run graph snapshot, cycle detection scoped to the active
override paths (benign citation cycles never halt), bounded and
deterministic execution, and **re-confirmation over silent thrash** — a
previously accepted row reopened by propagation presents a diff for human
re-election; it is never silently discarded. Eliminations that narrow
supplier options mint derived context facts (the SD-7 pattern, engine §3.1).

### 10.3 Axis-consistency gates *(v0.2 — new)*

Six independent axes can contradict each other; contradictions are
mechanical checks that block export, in the engine §9.1 style:

| Gate | Rule |
|---|---|
| Applicability coherence | applicability No + implementation Meets/partial/not-met is a contradiction (nothing to implement) |
| Approval coherence | approval approved requires an approval record with identity/revision/approver/date/scope (§10.1); approval not-required + an open tailoring action is a contradiction |
| Review coherence | review accepted requires every axis non-TBD or an explicit accepted-with-TBD election naming the TBD reason and owner |
| Actor coherence | organization_responsibility owner + obligated_actor exclusively external is a contradiction; external responsibility never forces applicability No |
| Export coherence | exported label must equal the §7.1 mapping of current axes; stale exports are flagged on any axis change |
| TBD validity | every TBD carries exactly one closed-vocabulary reason (§7) |

Plus the engine's §9.2 mandatory review flags, applied to comments:
universal negatives in rationale, waiver/decline language on compliant rows,
foreclosed relief paths, unit-of-analysis mismatches, borrowed terminology.

## 11. Interview behavior

- Show exact authoritative text first; place explanation beneath it, labeled
  as interpretation.
- Ask a single question unless several facts form one indivisible checklist.
- Reuse known context; never ask the same question again unless the fact was
  superseded or disputed.
- Prefer closed factual questions; allow narrative answers and document
  attachment.
- Explain the consequence of each answer without steering the user toward a
  desired status.
- When the answer is unknown, record TBD and identify the proper owner
  instead of guessing.
- Allow the user to correct a prior fact and show every affected requirement
  before propagating the change.

*(v0.2)* Paired questions (engine §8, fixture case 19): where one scope
question governs multiple requirements across standards, it is asked once
and its answer applied to every paired row; divergence is a §10.3 gate
failure.

## 12. Evidence management

Evidence is a controlled object, not a link pasted into a comment. Each item
carries document identity, revision, scope, issuing organization,
effective/approval date, expiration where applicable, confidentiality, and
source location.

Examples: AS9100 certificate, procedure, traveler, purchase-order clause,
approved supplier record, test report, AMCP, EFCP, QMP, PPP, NDE plan,
MUA/MIUL, approval memorandum.

- Evidence may support one or many requirements; withdrawal or expiration
  reopens affected conclusions (via §10.2 propagation).
- Assertions without evidence remain clearly labeled and cannot satisfy a
  mandatory evidence gate.
- The system preserves the exact evidence version reviewed, even if a newer
  revision later becomes available.

*(v0.2)* Rights classification is enforced at every processing operation
touching controlled content (engine §7.1 pipeline-rights rule; P-2 data
governance for any model call).

## 13. Comment generation

Generated comments shall be concise, factual, actor-aware, and bounded by
the evidence. They must state unresolved dependencies and must not imply
approval, authority, or implementation beyond what has been demonstrated.

### 13.1 Comment pattern

1. State the evaluated organization's implementation or responsibility.
2. Identify the controlling process, document, or evidence when known.
3. State any external responsibility, missing input, or pending approval.
4. State the closure condition when the row is not fully closed.

### 13.2 Prohibited language

- Approved, accepted, qualified, compliant, or complete unless the
  approval/evidence record exists.
- Not applicable merely because the evaluated supplier is not the normative
  actor.
- Meets intent when the implementation is absent or when the phrase would
  conceal a requested exception.
- "No MUA necessary" (or equivalent) unless the governing requirement and
  approval basis explicitly support that conclusion.
- *(v0.2)* Universal negatives asserted about the world rather than the
  supplier's own evidence (fixture case 13): "no demonstration exists" →
  "the supplier has not demonstrated…".
- *(v0.2)* Decline/waive/foreclose phrasing on a compliant row (cases 6/10):
  a chosen means of compliance is never framed as declined relief.

## 14. User experience

### 14.1 Requirement workspace

| Pane | Contents |
|---|---|
| Source | Exact requirement, section/page, rationale, definitions, linked clauses |
| Decision | Plain-language explanation, actor, trigger, dependencies, current allowed states |
| Interview | One active question, prior answer history, evidence attachment |
| Output | Live axes, proposed comment, evidence gaps, actions |

### 14.2 Navigation and controls

- Progress by rule pack, section, organization, status, owner, evidence
  completeness.
- Filters: TBD, Open/Not Met, proposed tailoring, external action, stale
  evidence, blocked dependencies.
- A visible **"Why can't this be Meet?"** explanation generated from
  deterministic blockers.
- Review queue showing machine proposals, changed prerequisites, externally
  returned comments.
- Side-by-side source, current disposition, export preview.

## 15. Logical architecture

| Layer | Responsibility | Notes |
|---|---|---|
| Rule-pack service | Versioned requirements, exact text, logic, dependencies, provenance | Immutable approved revisions; separate draft extraction workspace. Extends the existing pack library + `shall_extractor` (engine §7.3). |
| Project-context service | Facts, assumptions, organizations, hardware, plans, supply-chain scope | Event history and supersession, never destructive overwrite. |
| Decision service | Applicability, actor allocation, state guards, propagation, blockers | Deterministic policy engine with explainable rule results. |
| Language service | Extraction assistance, explanations, questions, answer interpretation, comment drafts | BSMS grounded retrieval + grader (D-7); structured outputs; grounded only in approved sources and project records. |
| Evidence service | Controlled artifacts, metadata, relationships, expiration, access | Content-addressed versions; authorization + audit records. |
| Workflow service | Assignments, review, approval, actions, notifications, identity | Role-based transitions; no silent auto-approval. Backed by the S1a persistence contract (append-only, hash-chained event log). |
| Export service | Customer matrices, registers, DOCX/XLSX, audit packages | Template mapping from internal axes; provenance retained. |

## 16. Security, governance, auditability

- Role-based access by project, organization, rule pack, evidence class,
  action.
- Immutable event log for source ingestion, fact changes, evidence changes,
  decisions, reviews, exports (S1a contract).
- Separation between draft model output and accepted human decisions.
- Encryption in transit and at rest; controlled download/export permissions.
- No use of customer-controlled content for model training; no customer
  content through any model without P-2 clearance.
- Retention consistent with contractual, QMS, export-control, and records
  requirements.
- Every export receives a snapshot identifier tying it to exact source,
  context, evidence, and disposition revisions.
- *(v0.2)* Advisory posture per engine D-1/§17: every output carries the
  advisory-software statement; no compliance or safety-critical badge until
  the assurance case is approved by domain authority.

## 17. Integrations and exports

- PDF/DOCX standards and specifications; existing XLSX matrices and
  controlled evidence registers.
- Document-management/QMS systems as read-only evidence references (MVP).
- Optional issue/task systems for closure actions (post-MVP).
- DOCX/XLSX exports matching customer or internal templates; structured JSON
  export for analytics, APIs, rule-pack portability.
- *(v0.2)* External decisions arrive via the countersign-export path (engine
  §12): state-preserving, re-import gated on artifacts, never a back door to
  release/accepted states (P-4/pointer-only per decision D-4).

## 18. MVP definition

> **MVP boundary:** one project, NASA-STD-6030/6033, one-requirement-at-a-
> time interview, dependency-aware dispositions, evidence attachment, human
> review, Word/Excel export. Do not begin with a universal autonomous parser.

### 18.1 Included

- Curated 6030 + 6033 rule packs seeded from the builtin packs and normative
  text (Phase 0 curation extends the existing 115-AMR pack).
- Project-context form supporting an assumed-CEO customer, cold spray,
  subassembly scope, relevant subtiers.
- Requirement workspace and sequential interview.
- All six axes; export mapping with guards (§7.1).
- Dependency rules for classification, fracture control, NDE, AMCP, EFCP,
  QMP, PPP.
- Evidence attachments and evidence-needed records.
- Generated comments and closure actions requiring human acceptance.
- XLSX supplier matrix, Appendix-style matrix, assumptions log, evidence
  register, open-action register.
- Golden-test replay of the live supplier disposition session (engagement
  records; enters product CI only scrubbed + counsel-cleared per D-3).

### 18.2 Deferred

- Fully automated ingestion of arbitrary standards without curator review.
- Automatic contractual approval or risk acceptance.
- Bidirectional writeback to customer QMS/PLM systems.
- Multi-tenant customer portals and external reviewer workflows.
- Model training on customer content (never without explicit authorization).
- Autonomous document revision or purchase-order flowdown changes.

## 19. Acceptance criteria

1. The system displays exact AMR text with standard revision, section, page.
2. A user can record the customer as *assumed* CEO without converting the
   assumption into a confirmed fact.
3. The system separately records AMR-1 as program-applicable while assigning
   formal approval responsibility externally to the evaluated organization.
4. The system prevents AMR-2 from being represented as satisfied by a
   supplier matrix when no approved AMCP is present.
5. AMR-5, -6, -8, -10, -12, -15, -17 render TBD (`classification_unresolved`)
   while classification inputs are absent.
6. AMR-14 records Open/Not Met when no EFCP or mapped 6033 control set
   exists.
7. A proposed Meets Intent automatically identifies whether formal
   tailoring/exception approval is required — and can never render under a
   compliance heading (§7.1 guard 1).
8. Changing primary classification returns all affected downstream records
   to review, each with a diff (§10.2).
9. Exported comments claim nothing beyond accepted evidence (§13.2 checks
   pass).
10. A reviewer can traverse every exported row to source text, facts,
    evidence, assumptions, decision history.
11. Generated DOCX/XLSX contain no unresolved internal identifiers or
    model-only annotations (fixture case 23 class).
12. *(v0.2)* The 26-case regression fixture passes with assertions remapped
    through the §7.1 view (ERRATA_RFC_001 migration).

## 20. Verification strategy

### 20.1 Golden-test corpus

The live 6030/6033 working session becomes the first golden test: per AMR —
authoritative text, known context, question asked, user answer, accepted
disposition (axes), generated comment, evidence gap, owner, dependency
behavior. *(v0.2)* This is the same artifact as the engine's S7 golden
package (D-2 kill-criteria measurement set); one corpus, both uses; frozen
under the Evaluation contract (slice plan) before any metric consumes it.

### 20.2 Test classes

- Unit tests: rule evaluation, status guards, export mapping (truth table),
  dependency propagation.
- Extraction tests: exact text + metadata vs curated records (golden parses,
  engine §7.3/§15).
- Conversation tests: minimal questions, context reuse, "I don't know"
  handling (must yield TBD, never a guess — `must_not_propose` class).
- Adversarial tests: unsupported N/A, unsupported Meet, hidden tailoring,
  conflicting evidence, stale approvals.
- Regression: prompt/model changes never alter accepted deterministic
  outcomes (engine §16 reproducibility + threshold versioning).
- Human review tests with reviewers unfamiliar with the build team.

## 21. Implementation roadmap

| Phase | Outcome | Exit condition |
|---|---|---|
| 0 — Curate | Approved 6030/6033 rule-pack records + dependency graph | All AMRs/EFCRs reviewed against source, uniquely identified |
| 1 — Interview MVP | Project context, sequential workflow, facts, axes, comments | Golden session replays without manual spreadsheet editing |
| 2 — Evidence & export | Attachments, evidence gates, DOCX/XLSX matrices, action register | Outputs reproduce accepted session decisions and lineage |
| 3 — Review controls | Assignments, approval workflow, change impact, audit view | Independent reviewer can validate and approve a package |
| 4 — Generalize | Rule-pack authoring + additional standards/contracts | New curated pack deployable without code changes |
| 5 — Integrate | QMS/PLM/task connectors, external review | Controlled integrations pass security/data-governance review |

*(v0.2)* Phasing maps onto the slice plan after ERRATA_RFC_001 is approved:
S1 refactor (axis model) → S1a persistence (parked spec, entry criteria
already cut) → curation slices (Phase 0) → interview slices (Phase 1) —
re-planned in detail once the errata and the targeted ORACLE pass land.

## Appendix A — Worked example (AMR-17, quantitative NDE)

| Element | Content |
|---|---|
| Source requirement | Class A parts require quantitative NDE with full surface/volume coverage, critical-flaw detection where applicable, PPP documentation of coverage limitations |
| Trigger | Primary classification = Class A |
| Dependencies | Primary classification; fracture-control status; critical initial flaw size; qualified NDE approach; approved PPP |
| Known facts | Customer assumed CEO; classification not provided; critical flaw size not provided; PPP not observed |
| System question | Has the customer provided the part classification and approved NDE/PPP requirements? |
| User answer | Unknown |
| Disposition (axes) | Applicability TBD (`classification_unresolved`); implementation TBD; customer input required |
| Generated comment | "Applicability is TBD pending the customer's part classification, fracture-control inputs, critical flaw-size requirements, and approved NDE/PPP requirements. The evaluated organization will perform or procure NDE to approved requirements but does not independently establish system-level coverage or flaw-detection criteria." |
| Guardrail | Block Meet and N/A until classification and applicable NDE inputs are resolved |

## Appendix B — Initial project-context seed (scrubbed)

| Context item | Current value | State |
|---|---|---|
| CEO | Customer (prime) | Assumed; confirmation not provided |
| Evaluated organization | Supplier (cold-spray producer) | Confirmed |
| AM process | Cold spray | Confirmed |
| Hardware level | Functional subassembly | Confirmed |
| Governing AMCP | Not observed | TBD / customer input |
| EFCP / 6033 matrix | Not present per current knowledge | Open/Not Met |
| Primary/secondary class | Not provided | TBD |
| Fracture-control status | Not provided | TBD |
| Subtiers | Powder, testing, heat treatment/HIP, NDT | Confirmed |
| Supplier QMS | AS9100 certified | Confirmed; certificate evidence required |
| Subtier QMS/accreditations | Not verified | TBD |

## Appendix C — Product risks

| Risk | Failure mode | Primary control |
|---|---|---|
| Authoritative-text error | Incorrect extraction changes the rule | Curator approval, source hashing, coordinates, exact-text regression tests |
| LLM overreach | Generated prose exceeds evidence or implies authority | Structured prompts, deterministic blockers, prohibited-language checks, human acceptance |
| Status compression | Customer template hides TBD/Open/external states | Preserve internal axes; export companion assumptions/action register |
| Stale evidence | Expired/superseded evidence supports Meet | Effective/expiration dates, version binding, automatic affected-record review |
| Dependency drift | Upstream fact changes leave downstream rows closed | Graph propagation + mandatory re-review |
| Rule-pack revision | Revised standard silently invalidates prior decisions | Revision comparison, impact analysis, immutable snapshots |
| Automation bias | Reviewer accepts model wording without examining source | Source-first UI, blocker explanations, explicit attestation, audit sampling |
