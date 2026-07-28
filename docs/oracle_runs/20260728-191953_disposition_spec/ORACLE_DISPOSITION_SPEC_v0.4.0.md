<!-- Extracted from revised_spec_v0.4.0.docx (ORACLE run 20260728-191953).
     The docx is the authoritative run output; this markdown is a faithful
     extraction for diffing and review. -->

BoundState AI LLC
ORACLE_DISPOSITION_SPEC — Oracle Review
Oracle2 Multi-Oracle Review | 2 round(s) | NOT CONVERGED — blocked, needs human review


# Oracle Disposition Module: Functional Specification
Module: boundstate/core/oracle/ (final home + name: open question 6, §14 — collides with the ORACLE adversarial review engine in the oracle repo) Purpose: Disposition an uploaded supplier document against a levied standard, requirement by requirement, with traceable provenance Version: 0.4.0 (draft — Beth revision, blind-review round 2 incorporated, awaiting human review) Classification: BoundState Proprietary Compliance (TARGET — NOT YET SUBSTANTIATED): SWE-013, SWE-033, NASA-STD-8739.8B (target claims only; unsubstantiated until the §17 assurance case maps each applicable clause to implemented, verified controls and an authorized domain owner approves the posture) Safety Critical (UNCONFIRMED): claimed target True (posture unconfirmed pending the §17 assurance decision; a human/domain authority sign-off is owed before any safety-critical or compliance badge is asserted)
Derivation: This spec is reverse-engineered from a complete manual Oracle run performed 2026-07-28: NASA-STD-6030 (115 requirements) and NASA-STD-6033 (31 requirements) dispositioned against a cold spray additive manufacturing process for a Boeing supplier flowdown, with independent expert review by Fran. Every requirement below traces to an observed failure or an observed necessity in that run. The companion regression fixture is oracle_eval_cs6030.json.
Revision 0.4.0 (Beth): Section numbering remains frozen — the fixture's spec_rules pointers cite these numbers; changes add subsections, never renumber. Round-2 blind review resolved: a universal human-election release gate now applies to every code including CW/NA, backed by a workflow_state machine and a package release predicate (§1.2, §7, §9.1); parent roll-ups are now non-dispositional composition vectors with a complete render truth table (§1.1, §9.1, §16); the relevance horizon is now a compute bound only and can no longer silently drop a normative obligation (§11); cycle-detection is scoped to the accepted-exception propagation graph, not the naturally cyclic reference graph (§11.1); capability-model claims are now evidenced assertions with fail-closed defaults (§3.1, §6.1, §9.2); requirement extraction/unitization is now a first-class subsystem with human boundary confirmation and ID-stability rules (§7.3); content-rights control now spans the processing pipeline and distinguishes tenant-licensed display from redistribution (§7.1, §14.4, §17); numeric MVP kill-criteria are now required before build commitment (§16). Header compliance/safety-critical claims are marked TARGET/UNCONFIRMED; the posture decision is routed to human authority.

## 1. Scope and Non-Goals
### 1.1 What Oracle does
Given (a) a controlled standard at a specific levied revision, (b) an uploaded supplier document set, and (c) a declared scope, Oracle assigns exactly one disposition code to every disposition unit in the standard, with the requirement text, a locator, an evidence pointer, and a calibrated confidence.
The disposition unit is the requirement clause/subparagraph, not always the numbered requirement. A requirement is atomic if it has no separately-conditioned subparagraphs; otherwise each subparagraph is a disposition unit with its own immutable hierarchical ID (e.g., AMR-51, AMR-51(e)). This resolves the tension between one-code-per-requirement and per-subparagraph remaps (§5.1).
Rule (levy manifest): every run shall be pinned to an immutable levy manifest capturing, per levied and referenced document, the document ID, revision, effective date, source, and overlay precedence. Dispositions are computed against the levied revision only. A newer corpus issuance is a §14.2 drift finding requiring a new run, never an automatic substitution.
Rule (parent roll-up — non-dispositional): a parent requirement with child units is a non-dispositional roll-up row, not a disposition unit. It carries a composition vector (the count of children in each code) as its source of truth, is never assigned an independent disposition code, and is never a target of acceptance. Parent rows are excluded from all counts (§7.1) so children are never double-counted; a roll-up never satisfies a release gate on its own. Where a legacy compliance-matrix format requires a single display badge, it is derived by this total order over child states, and is a rendering artifact only:
any child OPEN → badge OPEN
else any child EX → badge EX (exception heading)
else any child MI → badge MI (exception heading)
else children mix CW and NA → badge MIXED (rendered "partially applicable", links to child rows)
else all children CW → badge CW
else all children NA → badge NA
A truth-table test (§16) asserts every child-code combination resolves to exactly one badge.
### 1.2 What Oracle does NOT do
Oracle provides bounded judgment support; it does not render final engineering judgment. It proposes; a qualified engineer disposes. Certain classes — MI, EX, authority-dependent, definitional remap, and NA-vs-zero-limit — are intrinsically judgment-bearing and shall carry a mandatory human disposition; Oracle proposes candidates and surfaces the reasoning, never an autonomous conclusion. In the reference run, 85 of 115 dispositions were machine-proposable, an expert reviewer found substantive errors in that proposal set, and the errors clustered exactly where the proposer's confidence was already flagged low. Oracle's product value is provenance, bookkeeping, consistency enforcement, and structured judgment support — not autonomous disposition authorship.
Prohibited autonomous conclusions: Oracle shall not finalize (release-mark) any MI, EX, NA, authority-dependent, remap, or zero-limit disposition without a recorded human election.
Rule (universal human election on release): no disposition unit — including `CW` and `NA` — is marked release-approved without a recorded, authorized human confirmation captured in the unit's workflow_state (§7). Evidence sufficiency is necessary but never sufficient for release: a machine-proposed CW with qualifying evidence remains human_confirmed-pending until an authorized reviewer elects it. A package is release-approved only when every included unit is release_approved and zero units are OPEN.
Design consequence: Oracle output is never released as a compliance package. It emits a working matrix that a human confirms row by row. Any UI or API affordance that permits bulk-accept of unconfirmed rows, or that marks a unit customer-releasable through an import path without the required human election and (for MI/EX) acceptance artifact, is a defect.

## 2. Disposition Codes
Five codes. Four is not enough; this was the single most important structural finding of the reference run.

| Code | Meaning | Contract effect |
|---|---|---|
| CW | Complies as written | Literal requirement retained; cited evidence demonstrates implementation |
| MI | Intent met by alternative means | Literal wording or mechanism not used; equivalent control meets technical intent. A formal exception requiring customer acceptance, not a claim of compliance |
| EX | Exception requested | Requirement not met as written; customer must accept the stated alternative, limit, or contractual route before use |
| NA | Not applicable | Outside declared scope; the cited scope declaration must remain true |
| OPEN | Evidence or decision incomplete | Not an externally releasable disposition |

### 2.1 The OPEN requirement (BLOCKING)
A document-versus-standard run generates a large population of "the uploaded document is silent on this requirement." That is categorically distinct from "does not meet." Without OPEN, Oracle converts silence into compliance, which is the worst available failure mode for this product.
Rule: absence of evidence maps to OPEN (sub-reason evidence_absent), never to CW and never to NA.
Rule: a package containing any OPEN row cannot be marked release-ready. OPEN count is a gate, not a metric.
### 2.2 MI is an exception, not a compliance
MI rows must render in customer-facing output under the exception heading, never under the compliance heading. In the reference run an early draft summarized MI as "comply as tailored," which invited the reader to treat 38 formal exceptions as compliances.
Rule (acceptance): both MI and EX are proposals until a customer acceptance record (§7) exists. A proposed-but-unaccepted MI/EX is not contractually releasable and does not trigger §11.1 propagation.
### 2.3 OPEN sub-reasons are a closed vocabulary
Every OPEN unit shall carry exactly one sub-reason from this controlled list. An OPEN unit with a missing or unlisted sub-reason is a defect. The §12 gate report groups by sub-reason, and regression cases assert sub-reasons, so the vocabulary is part of the module's contract:

| Sub-reason | Source rule | Meaning |
|---|---|---|
| evidence_absent | §2.1 | Uploaded document set is silent on the requirement, or the evidence linker's confidence is below the §14.1 threshold |
| scope_decision_not_made | §8 | A customer/business decision the disposition depends on does not exist yet |
| authority_unidentified | §4.1 | The requirement names an approval role nobody has identified |
| approval_not_exercised | §4.1 | The authority is identified but the named approval has not occurred |
| referenced_artifact_missing | §7.2 | A cited attachment/register/annex does not resolve in the controlled document system |
| referenced_standard_unavailable | §11 | An outbound normative reference is not in the corpus |
| reference_semantics_unresolved | §11 | An outbound reference's incorporation type or applicability predicate could not be determined and needs human review, or a candidate normative reference was truncated by the §11 relevance horizon and its applicability has not been determined by a human |
| dependency_eliminated | §11.1 | A mechanism this disposition relied on was eliminated by an accepted exception elsewhere |

Extending this vocabulary is a spec revision, not an implementation convenience.

## 3. Intake: Scope Declarations (BLOCKING)
Oracle shall not begin disposition until a scope declaration set is captured. In the reference run, 17 of 115 requirements were not applicable, and 13 of those were polymer-section requirements against a metallic process. Without scope intake, Oracle will earnestly disposition polymer requirements against a metallic feedstock and produce confident nonsense.
### 3.1 Minimum intake fields
{
    "process_family": str,          # e.g. "cold_spray_solid_state"
    "material_families": List[str],
    "part_classes_pursued": List[str],

    # What the process CAN physically do — distinct from what policy says
    # it WILL do. Cases 4/5 vs 18 are undecidable without this.
    "capability_model": {
        "capabilities": [
            {
                "id": "CAP-1",
                "condition": str,       # e.g. "powder recovery and reuse"
                "physically_possible": bool,
                "basis": str,           # why: equipment, physics, configuration
                "basis_evidence": Optional[str]  # pointer to process spec / equipment
                                        # limit / prior run supporting the claim
            }
        ]
    },

    "scope_declarations": [
        {
            "id": "SD-1",
            "declaration": str,
            "type": str,            # "policy" | "physical_impossibility" | "derived"
            "capability_ref": str,  # REQUIRED when type == "physical_impossibility"
            "dependency": str,      # what breaks if this stops being true
            "source": str           # who declared it, when, in what document
        }
    ]
}
Rule (evidenced impossibility, input trust): a declaration of type physical_impossibility shall cite a capability-model entry with physically_possible: false and that entry shall carry a basis_evidence pointer to an independent artifact (process spec, equipment limit, physics basis, prior qualified run). A physical_impossibility resting only on supplier self-assertion, or a capability whose possibility is uncertain, fails closed: the dependent unit defaults to human adjudication, not NA. A declaration phrased as "we do not do X" where the capability model says the process can do X is type policy, and §6.1 governs its use.
Rule: declarations of type derived are minted during the run by §11.1 propagation (the SD-7 pattern in the reference run), carry the case or exception that produced them, and are otherwise first-class: dispositions cite them, and changes reopen dependents per §3.2.
### 3.2 Scope declarations are load-bearing and must be traceable
Every NA disposition shall cite the scope declaration ID that supports it. An NA with no scope citation is a defect, not a disposition.
Rule: if a scope declaration changes, Oracle shall reopen every disposition that cites it and downgrade those rows to OPEN via the §11.1 re-confirmation workflow. Scope change invalidates dependent dispositions silently otherwise. This is the dependency-graph requirement; see document-cartography.

## 4. Authority-Dependent Requirements (BLOCKING)
The highest-consequence finding of the reference run.
NASA-STD-6030 references the Cognizant Engineering Organization 109 times; 18 requirements name an approving authority inside the requirement text itself (AMR-2, 3, 4, 5, 13, 14, 21, 34, 35, 58, 60, 67, 97, 99, 110, 111, 112, 113). These requirements govern part classification, part acceptance, readiness review, and configuration control, the gates between qualification and delivery.
A requirement that names an approval authority can never be dispositioned `CW` from a document alone. No uploaded document can demonstrate that an unidentified organization approved something. In the reference run, this class was nearly shipped as CW, which would have asserted compliance with an approval chain that had never been exercised.
### 4.1 Required behavior
Authority detection is a two-stage control: an assistive scan plus a fail-closed completeness mechanism. A token scan alone cannot establish that all approval dependencies were found (passive voice, synonyms, and definitional expression evade it), so it is never the sole gate.
Oracle shall detect candidate authority-naming requirements by scanning requirement text for approval-role tokens (cognizant engineering organization, CEO, Technical Authority, M&P organization, fracture control board, program, project, customer-designated equivalents) and mark them authority_dependent = true.
Rule (completeness / fail-closed): authority classification shall be recorded as a per-standard, per-unit annotation that is either confirmed by the scan against known patterns or routed to mandatory human authority review. Any requirement whose approval semantics are ambiguous fails closed to human review; it shall not be auto-proposed CW. Recall of the authority classifier shall be measured against an annotated corpus (§16), not only against the known token set.
Rule (levied set, case 16): the authority classification shall run independently over every standard in the levied set, including standards pulled in by §11 reference walking. In the reference run the analysis was performed on the primary standard only; the secondary standard carried its own parallel approval chain, and its first requirement went undispositioned. A levied set with any unclassified member fails the §9.1 gate.
Rule (§14.3 interaction): the role-token list is a seed, not a definition. Customer overlays rename roles; the levy manifest shall capture customer-specific authority titles, and the classifier shall include them.
For each authority-dependent unit:
If the responsible authority is not identified in intake → OPEN, sub-reason authority_unidentified. Never CW.
If the authority is identified but the approval has not occurred → OPEN, sub-reason approval_not_exercised.
If the authority is identified and approval evidence is cited → CW with the approval record as the evidence pointer.
If the customer route deliberately bypasses the standard's named authority chain → EX, with the alternative authority basis stated.
### 4.2 The authority report
Oracle shall emit, as a first-class output, an authority dependency report answering: which requirements' dispositions depend on an authority nobody has identified? — broken out per standard in the levied set.
In the reference run this query was the single most valuable output produced, it was produced by hand, and it was produced last. Surfacing it at intake would have changed the entire package structure.
Rule: the authority report renders before the disposition matrix in all output orderings.

## 5. Definitional Remap Detection
This is the core technical IP and the primary generator of MI rows.
A standard written for one physical process, levied on a different process, contains requirements phrased in physics the target process does not have. In the reference run: melt pool geometry, focused thermal energy, energy source parameters, melt-based build area. These have no referent in solid-state deposition.
### 5.1 Required behavior
Oracle shall detect requirement text containing process-physics terms absent from the uploaded process definition, and propose an MI disposition with a remap candidate: the target-process variable that serves the same control function.
Rule: a remap proposal shall carry the intent statement of the source requirement, so the reviewer evaluates whether the substitute serves that intent rather than whether the words look similar.
Rule: remaps apply per disposition unit (subparagraph), never per parent requirement. In the reference run, one requirement's subparagraph (e) required melt-pool metrics while subparagraphs (a) through (d) applied unchanged. Remapping the whole requirement would have silently voided four applicable controls. This is why §1.1 makes the subparagraph the atomic disposition unit.
### 5.2 Anti-pattern: the false generalization
The reference run produced the claim "every enumerated process in the standard has a melt pool," used to argue the target process was out of scope. This was false; the standard's enumerated set included non-fusion polymer processes. The correct and stronger argument came from the standard's own definition of the process class in question.
Rule: exclusion arguments shall be built from the standard's own definitions section, never from an inductive generalization over the enumerated set. Oracle shall cite the definition and its locator.

## 6. The N/A Versus Zero-Limit Distinction
A subtle finding with direct audit consequence. Two requirements governed feedstock reuse. The process declared no reuse, so an initial pass coded them NA. Expert review reversed this to MI: the process is physically capable of powder recovery, so the requirement applies and is met by a controlled operating limit of zero. The NA version is the one that fails an audit.
### 6.1 Required behavior
Oracle shall distinguish:
`NA` by physical impossibility, the process cannot produce the condition the requirement governs. Cites a physical_impossibility scope declaration, which cites an evidenced capability-model entry (§3.1).
`MI` by controlled limit, the process can produce the condition, but a declared and evidenced control holds it at zero or within bounds.
Rule: when a scope declaration is phrased as a policy rather than a physical impossibility, Oracle shall propose MI with a zero-limit control and flag NA as the weaker alternative, with the audit exposure stated.
Rule (self-assertion flag): where an NA rests on a physical_impossibility declaration whose capability entry lacks basis_evidence (supplier self-assertion only), Oracle shall raise the §9.2 unverified-impossibility flag and shall not auto-propose NA.
This distinction is not detectable from the requirement text alone. It requires the capability model captured at intake (§3.1), which is why §3 is blocking.

## 7. Provenance Requirements (SWE-013 / SWE-033)
Every disposition unit shall carry:
{
    "unit_id": str,                 # e.g. "AMR-51(e)" — immutable hierarchical ID
    "parent_id": Optional[str],     # the parent requirement, if this is a subparagraph
    "is_rollup": bool,              # True for parent rows; carries composition vector,
                                    # not an independent code (§1.1)
    "composition_vector": Optional[dict],  # REQUIRED when is_rollup; counts by child code
    "requirement_text": str,        # VERBATIM from the levied revision, OR a locator+hash
                                    # reference when rights are not cleared (§7.1)
    "requirement_payload": Optional[dict],  # structured content (table/formula/block refs)
                                    # when the requirement is not a flat string
    "unit_boundary_confirmed_by": Optional[str],  # human who confirmed extraction
                                    # boundaries (§7.3); REQUIRED before disposition
    "applicability_clause": Optional[str],  # VERBATIM extraction of the unit's own stated
                                    # applicability (case 12)
    "locator": {
        "standard": str,
        "revision": str,            # the LEVIED revision from the levy manifest
        "section": str,
        "page": int
    },
    "code": str,                    # CW | MI | EX | NA | OPEN (omitted for is_rollup rows)
    "workflow_state": str,          # "proposed" | "human_confirmed" | "rejected"
                                    # | "release_approved" — set by an authorized human
                                    # per §1.2 / §17; machine may set only "proposed"
    "open_sub_reason": Optional[str],   # REQUIRED when code == OPEN; §2.3 vocabulary
    "scope_citation": Optional[str],# REQUIRED when code == NA; also carried by
                                    # MI zero-limit rows citing the policy declaration
    "authority_dependent": bool,
    "authority_classification": str,# "scan_confirmed" | "human_reviewed" | "pending_review"
    "intent_statement": Optional[str],  # REQUIRED when code in (MI, EX)
    "alternative_control": Optional[str],# REQUIRED when code in (MI, EX)
    "control_class": Optional[str], # "integral" | "disclosed" per §10.1; REQUIRED
                                    # whenever alternative_control is present
    "evidence": [                   # REQUIRED when code in (CW, MI)
        {
            "doc_id": str,
            "revision": str,
            "locator": str,
            "link_confidence": float   # evidence-linker confidence, §14.1
        }
    ],
    "acceptance": Optional[{        # REQUIRED before an MI/EX row is release-eligible
        "status": str,              # "proposed" | "accepted" | "rejected" | "expired"
        "customer_authority": str,  # the accepting party
        "approval_artifact": str,   # signed/controlled decision record ID
        "approved_scope": {         # structured, machine-checkable acceptance scope
            "configurations": [str],
            "part_classes": [str],
            "valid_from": str,
            "valid_to": Optional[str]
        },
        "supersedes": Optional[str],# prior acceptance record this replaces
        "immutable": True           # acceptance records are append-only
    }],
    "confidence": float,            # 0.0-1.0, calibrated per §8
    "proposer": str,                # model or human identity
    "confirmed_by": Optional[str],  # internal human confirmation; NOT customer acceptance
    "confirmed_date": Optional[str]
}
### 7.1 Hard rules
Rule (release-state machine): workflow_state transitions are proposed → human_confirmed → release_approved, with proposed|human_confirmed → rejected permitted. Only an identified, authorized human (§17) may set any state other than proposed. No unit is release_approved without human_confirmed first. This applies to every code, including CW and NA.
Rule: no CW or MI unit is release-eligible without at least one evidence identifier with a revision and a link confidence at or above the §14.1 threshold. A description of an intended control is not evidence. Evidence sufficiency does not by itself make a unit release_approved; the human election is still required.
Rule (acceptance gate): no MI or EX unit is contractually release-eligible unless it carries an acceptance record with status == "accepted", a valid valid_from within the current date, and an approved_scope whose configurations/partclasses cover the disposition. A superseded or expired acceptance does not satisfy the gate. `confirmedby` is internal confirmation only and shall not be treated as customer acceptance.
Rule (no import bypass): any path that imports externally-recorded confirmations or decisions shall not set workflow_state == "release_approved" or acceptance.status == "accepted" without the corresponding controlled artifact (human election record and, for MI/EX, an acceptance artifact). Bulk import of "confirmed" rows without artifacts is a defect.
Rule (rights gate, storage/render): verbatim requirement_text is stored and rendered only for corpora whose redistribution rights are cleared in the levy manifest (§14.4). Where redistribution rights are not cleared, the unit stores an access-controlled locator plus a content hash instead of verbatim text, and any redistributed customer-facing artifact substitutes the locator. Emitting uncleared verbatim controlled text into a redistributed customer-facing artifact is a blocking defect.
Rule (tenant-licensed display): verbatim display to an authorized user within the customer's own isolated tenant, under that customer's own license (the §14.4 BYOL mode) is distinct from redistribution and is permitted where the levy manifest records that mode, so the side-by-side review workflow is preserved without redistributing controlled text.
Rule (pipeline rights): the rights classification of a corpus shall be enforced at every processing operation that touches its content — OCR, indexing, logging, caching, model inference/transfer, evaluation, and fixture creation — not only at storage and render (§17).
Rule: requirement text/payload is extracted from the levied revision, never paraphrased or recalled. The reference run propagated an incorrect handbook title through four document revisions because it was inherited from a prior summary. Every assertion Oracle emits about a standard shall be extractable and locatable. The same rule covers the applicability_clause field.
Rule: every count in every generated narrative shall be computed from the matrix at render time, over disposition units with parent roll-ups excluded. Never typed, never carried forward. (This rule applies to this spec's own companion documents: see §15.)
### 7.2 The referenced-artifact check
Rule: Oracle shall not emit a reference to an attachment, register, or annex that does not exist as a controlled artifact in the system. Reference emission is gated on artifact resolution. Unresolvable reference → OPEN with sub-reason referenced_artifact_missing.
### 7.3 Requirement extraction and unit-boundary confirmation
Every downstream gate is only as sound as the extraction of requirement units from the source standard. NASA-style standards mix shall statements, tables, notes, applicability predicates, and multi-level enumerations; wrong unit boundaries invalidate remap granularity, roll-ups, and fixture IDs.
Rule (first-class subsystem): requirement extraction/OCR/unitization is a first-class subsystem, not an implicit step. It emits candidate disposition units with proposed boundaries and hierarchical IDs; it does not itself disposition.
Rule (human boundary confirmation): for each standard in the levied set, unit boundaries shall be confirmed by an authorized human (unit_boundary_confirmed_by) before any disposition is proposed against that standard. Disposition of a unit whose boundaries are unconfirmed is a defect.
Rule (ID stability): hierarchical unit IDs shall be assigned by a documented rule that is stable across extractor versions for unchanged source text, so fixture spec_rules and unit IDs do not churn when extraction improves. Golden parse fixtures per standard family (§15) assert extraction stability.

## 8. Confidence Calibration
Per recommendation-policy, confidence is derived, never asserted. Proposal confidence bands:

| Band | Basis | Reviewer action |
|---|---|---|
| HIGH | Requirement text is unambiguous, scope citation is direct, no authority dependency, no remap, evidence link above threshold | Skim |
| MEDIUM | Disposition depends on a referenced table or subparagraph set not yet examined, or on a routing decision consistent with another open entry | Verify against source |
| LOW | Disposition depends on a scope decision the customer has not made, on process capability not established at intake, or on evidence below the §14.1 link threshold | Human decision required; Oracle proposes nothing |

Rule: LOW-confidence units render as questions to the reviewer, not as proposed codes with a caveat. The unit's code is OPEN with the applicable §2.3 sub-reason.
Rule (case 19): where a scope question governs paired requirements across standards, the question is asked once and its answer shall be applied to every paired unit. Divergent answers are a §9.1 consistency failure.
Rule: confidence is reported per unit and never aggregated into a package-level score.

## 9. Consistency Enforcement
The reference run's expert review found four internal contradictions in a document that read as authoritative, and the fixture adds several more mechanically detectable classes. §9.1 gates block release; §9.2 flags force explicit reviewer election and block only until each flag is dispositioned by a human.
### 9.1 Blocking gates

| Check | Rule | Observed failure |
|---|---|---|
| Single code per unit | Exactly one code per disposition unit; parent rows carry a composition vector, not a code | One requirement was coded NA while also appearing inside an exception entry |
| Parent roll-up resolution | Every parent's composition vector resolves to exactly one render badge per §1.1; no parent carries a code or acceptance | Mixed CW+NA parent previously had no defined result |
| Human election on release | Every release_approved unit — including CW/NA — carries an authorized human workflow_state transition | Machine CW could look releasable on evidence alone |
| Code/narrative agreement | A unit whose narrative states "no relief is requested" shall be CW, not MI | Requirement coded MI with a narrative asserting full compliance |
| Exception membership | A unit coded CW or NA shall not appear in an exception entry | An exception entry was constructed around a requirement to which no exception was taken |
| Count reconciliation | Narrative counts shall equal matrix counts at render time | Narrative reported a split that no matrix produced |
| Unresolved markers | Zero placeholder tokens in release-marked output | Placeholder markers survived into a release-candidate draft |
| Authority coherence | A disposition asserting customer approval authority shall not coexist with a request asking the customer to confirm it holds that authority | The same document declared and questioned the approval authority |
| Levied-set authority scan | Every standard in the levied set has a completed §4.1 classification with no pending_review units | Secondary standard's approval chain missed entirely (case 16) |
| NA basis typing | Every NA cites a scope declaration; citing a policy-typed declaration is a gate failure | Policy scope coded as physical impossibility (cases 4, 5) |
| Boundary confirmation | Every dispositioned unit has unit_boundary_confirmed_by set (§7.3) | Extraction/unitization previously implicit |
| Paired dispositions | Units paired on one scope question carry the same answer | Divergence risk across primary/secondary standards (case 19) |
| Sub-reason validity | Every OPEN unit carries exactly one §2.3 sub-reason | Vocabulary previously uncontrolled |
| Acceptance gate | Every release-marked MI/EX unit carries an accepted, in-scope, unexpired, non-superseded acceptance record (§7.1) | Unaccepted deviations could appear releasable |
| Cycle-free propagation | The §11.1 accepted-exception propagation graph snapshot contains no unresolved cycle | Cyclic override paths could hang propagation |

### 9.2 Mandatory review flags (block until a human dispositions the flag)

| Flag | Detection | Observed failure |
|---|---|---|
| Universal negative in exception rationale | "no ... exists", "there is no", "cannot be demonstrated by anyone" patterns in EX/MI narrative | "No representative demonstration exists" asserted about the world (case 13) |
| Waiver language on a compliance row | decline/waive/foreclose phrasing in a CW narrative | A chosen means of compliance framed as declined relief (cases 6, 10) |
| Relief path foreclosed | Disposition forecloses an exception clause, "unless" condition, or alternative route the requirement grants (§10.1) | Relief volunteered away without reviewer election (case 6) |
| Unverified impossibility | An NA rests on a physical_impossibility declaration whose capability entry lacks basis_evidence (§6.1) | Supplier self-asserted impossibility could launder audit exposure |
| Remap granularity | An MI remap spanning a whole parent whose subparagraphs are not uniformly affected | Whole-requirement remap would have voided four controls (case 3) |
| Unit of analysis | Quantified nouns in requirement text and citing scope declaration disagree | Machine count misstated by a factor of the family size (case 14) |
| Borrowed terminology | Narrative terms absent from both the standard's definitions and the process definition | "Wetted components" imported into a dry powder process (case 15) |
| Reference semantics | An outbound reference's incorporation type or applicability predicate is undetermined, or a normative candidate was horizon-truncated | Over-levying risk / silent omission from references (§11) |

Rule: these checks run as a release gate and block, not as warnings. A 9.2 flag is cleared only by a recorded human election, which becomes part of the unit's provenance.

## 10. Voluntary Expansion Guard
A supplier compliance document that volunteers controls beyond the standard converts prudent internal practice into permanent contractual obligation, and may waive relief the standard already offers.
### 10.1 Required behavior
Oracle shall classify every control it emits as:
`integral`, required to support a stated MI or EX disposition. Enters the contractual baseline.
`disclosed`, internal practice, shown for visibility. Shall render with an explicit non-binding statement and shall not appear in any compliance obligation list.
Rule: Oracle shall not emit a disposition that waives an exception path the standard grants, unless the reviewer explicitly elects that waiver. Detect by scanning requirement text for the standard's own relief provisions and flag any disposition that forecloses one (§9.2).
Rule (case 9): a requirement dispositioned NA shall not simultaneously be "adopted voluntarily" inside the compliance package. The underlying engineering practice, if kept, is recorded as a disclosed control in internal process documents and never in the contractual baseline.

## 11. Cross-Standard Dependency Walking
Requirements reference other standards, which may impose their own requirements. In the reference run a chain of five documents had to be walked before the disposition was defensible. But not every outbound reference creates an applicable obligation, and standards graphs are self-referential — unbounded walking over-levies requirements and floods the matrix with irrelevant OPEN rows.
Rule (typed references): every outbound reference shall be modeled with: reference type (normative_incorporation | informative | conditional_method), the cited clause, the applicability predicate, the revision rule, and a traversal stop condition. Only normative_incorporation references whose applicability predicate holds for the current unit create dependent obligations.
Rule (relevance horizon is a compute bound, not an applicability decision): dependency walking is bounded by a configurable depth and by the levy manifest's declared in-scope reference set. The horizon limits how far Oracle walks in one pass; it never decides whether an obligation applies. Informative and out-of-predicate references beyond the horizon are recorded without expansion and generate no OPEN rows. However, a candidate `normative_incorporation` reference whose applicability cannot be excluded but which is truncated or unresolved at the horizon shall set the originating unit to `OPEN`, sub-reason `reference_semantics_unresolved`, pending an authorized human applicability determination. A normative dependency is never silently dropped because it lay beyond a configured depth.
Rule: where a normative_incorporation reference resolves to a standard not in the corpus, the dependent disposition is OPEN, sub-reason referenced_standard_unavailable, never assumed satisfied. Where a reference's incorporation type or applicability predicate cannot be determined, the unit is OPEN, sub-reason reference_semantics_unresolved, routed to human review — never auto-expanded.
Rule: referenced standards shall be cited at their levied issuance with revision, verified against the corpus, not recalled.
### 11.1 Accepted-exception propagation (cases 17 and 21)
An accepted EX (or MI) can eliminate a mechanism or artifact that other units' dispositions silently rely on. In the reference run the alternative contractual route eliminated an agreement mechanism, invalidating a CW in the secondary standard (case 17) and removing the lot-provisional allowables bridge for the middle part class (case 21).
Rule (committed trigger): propagation triggers only from an immutable accepted-decision event (§7 acceptance record with status == "accepted"). Proposed or confirmed-but-unaccepted MI/EX rows do not propagate.
Rule (which graph is checked for cycles): the acyclicity requirement applies to the accepted-exception propagation graph — the directed graph of "unit whose basis references a mechanism/artifact that an accepted decision eliminates." The static normative reference graph of the standards themselves is expected to contain benign citation cycles; a cycle in the reference graph is not a halt condition and shall not force arbitration. Only a cycle in the active override/propagation paths halts.
Rule (bounded, cycle-safe, deterministic): propagation runs over an immutable per-run snapshot of the propagation graph. Before propagation, Oracle shall validate that this override graph is acyclic; a detected cycle in the override paths halts propagation, is flagged to the reviewer, and requires manual arbitration to break — Oracle shall not run to an unconstrained fixpoint on a cyclic override graph. Propagation is bounded by the §11 relevance horizon depth. Given identical committed inputs and graph snapshot, propagation output shall be deterministic.
Rule (re-confirmation, not silent thrash): when an accepted disposition eliminates a mechanism, artifact, or route, Oracle shall identify every unit whose basis references the eliminated element and revert those units to OPEN, sub-reason dependency_eliminated, citing the eliminating disposition. Where a reverted unit was previously human-confirmed, Oracle shall present a re-confirmation task with a diff, not silently discard the prior confirmation. Propagation is executed as a batched re-validation job against the frozen snapshot, not as live per-keystroke thrash.
Rule: where the elimination narrows what the supplier can do (the SD-7 pattern), Oracle shall mint a derived scope declaration (§3.1) recording the consequence, so it binds future dispositions and renders in the §12 scope record.

## 12. Output Contract
Oracle emits, in this order:
Authority dependency report (§4.2), per standard in the levied set
Scope declaration record (§3), including derived declarations, with every dependent disposition indexed
Disposition matrix, one row per disposition unit, schema per §7, in the standard's own compliance-matrix format where the standard provides one; parent rows render as roll-ups (§1.1)
Exception detail, one entry per MI and EX unit: requirement, intent, alternative control, limit of requested acceptance, acceptance status, closure evidence
Gate report, OPEN count by §2.3 sub-reason, missing evidence IDs, unaccepted MI/EX units, un-elected release-pending units, failed §9.1 gates, undispositioned §9.2 flags, unresolved references, detected override cycles
Narrative summary, generated from 1 through 5, never hand-authored, all counts computed
Rule (external countersign export): Oracle shall provide a first-class "export working matrix for external countersign" path that carries units in their current workflow_state, preserves non-releasable status, and cannot be re-imported as release_approved/accepted without the required artifacts (§7.1). This gives teams a way to gather external decisions without bypassing the gates or authoring a narrative outside the matrix.
Rule (rights): customer-facing redistributed outputs render verbatim controlled text only where §14.4 redistribution rights are cleared; otherwise they render access-controlled locators. In-tenant licensed display follows the §7.1 BYOL rule.
Rule: the narrative is a view of the matrix. The matrix is the artifact. Any workflow in which the narrative is authored first and the matrix back-filled reproduces the reference run's entire error class.

## 13. Performance Targets
Per boundstate-architecture. The disposition proposal pass runs as an asynchronous, queue-based background job; the numeric targets below are per-unit/per-pass compute budgets and total-latency goals under normal load, not synchronous request SLAs. The architecture is expected to apply rate-limit mitigation (token-bucket throttling, batching, retained intermediate embeddings) for external LLM endpoints.
Standard ingestion and requirement extraction: < 60 s for a 200-page standard
Full disposition proposal pass, 150 disposition units: target < 5 min end-to-end as an async job
Authority dependency report: < 5 s
Consistency gate: < 2 s
Matrix render: < 10 s
§11.1 propagation pass (acyclic override snapshot, within relevance horizon): < 5 s per accepted exception; cyclic override graphs halt to human arbitration and are not bounded by this target

## 14. Open Design Questions
Evidence matching (first-class subsystem). Mapping uploaded supplier documents to the requirements they satisfy is the load-bearing subsystem, not a side concern. Semantic retrieval proposes candidates; the reviewer confirms. Precision matters far more than recall. The linker shall carry acceptance metrics — precision@k and false-link rate on a held-out corpus — and a confidence threshold below which CW/MI proposal is withheld and the unit falls to OPEN (evidence_absent). Whether the achievable precision supports the MVP is a product decision (see §16 kill-criteria).
Standard revision drift. When a standard is revised, dispositions are diffed against the new text as a drift finding requiring a new run; the levied revision in the levy manifest is never silently replaced. Requires requirement-level versioning in the corpus.
Customer-specific overlays. Primes levy standards with their own tailoring. Oracle needs a layer for customer-modified requirement text that supersedes the base standard — including customer-renamed authority roles (§4.1) — captured in the levy manifest.
Corpus licensing and tenant display (BLOCKING GATE). Rights classification is a mandatory per-operation ingestion/processing/export gate (§7.1), not an open question at build time. Redistributed verbatim customer-facing text is permitted only for corpora with cleared redistribution rights; otherwise store locators+hashes. A Bring-Your-Own-License (BYOL) tenant-isolated mode may permit verbatim display to authorized users within the customer's own tenant under the customer's own license, without redistribution. (NASA technical standards in the reference run are publicly released; prime-contractor overlays and commercial standards are not.) The rights decision — including whether the BYOL model is legally sufficient per corpus — is a legal sign-off owed before ingestion.
Work-product rights. Where a run is performed under a customer purchase order, confirm data-rights and IP clauses before reusing the methodology or output as product material.
Placement and naming. boundstate/core/oracle/ collides with the multi-oracle adversarial review engine. Recommendation: build in MIRA under a distinct module name (e.g., disposition/), keep "Oracle" as the product-facing name only, and decide before the build pipeline targets a repo.
Fixture rights and confidentiality (BLOCKING). The fixture encodes corrected dispositions from a customer flowdown. It is quarantined until confirmed it can live in the product repo as regression data, or scrubbed of identifying scope declarations first.
External-system integration contracts. Real aerospace acceptance decisions, authority registries, and overlay corpora often live in customer portals, CR/EA systems, and ITAR-controlled shares. Define adapter contracts (including a pointer-only / not-ingested mode) for acceptance records, authority identity, and overlay corpora so "release-ready" does not require re-platforming the customer's process. Design owed before the release/propagation machinery is built.
v1 scope phasing. Whether v1 ships the full defensible engine (deep reference walking, derived-SD minting, propagation fixpoints) or an assisted matrix + deterministic gates first, deferring the graph machinery until package lifecycle states and amendment diffs are specified, is a product-direction decision.

## 15. Regression Fixture
oracle_eval_cs6030.json — 26 labeled cases from the reference run: 19 expert_corrected, 3 correct_positive, 2 must_not_propose, 2 expert_discovered. Each case carries the requirement, the initially proposed disposition, the corrected disposition, the failure mode, and the rule from this spec that the case exercises.
Rule: a change to disposition logic that regresses any case labeled expert_corrected or `expert_discovered` blocks merge.
Rule: must_not_propose cases assert that Oracle emits OPEN and a reviewer question. Emitting any code on these cases is a failure regardless of which code.
Rule: fixture counts and label breakdowns cited anywhere (including this section) are computed from the fixture file at test time. The test suite shall contain an assertion that this spec's stated case count matches the fixture, so the two cannot drift.
Rule (extraction golden parses): golden parse fixtures per standard family assert that extraction/unitization (§7.3) produces stable unit boundaries and IDs for known source text across extractor versions.
Rule (domain coverage, round-1 finding): the reference fixture is one process and two standards — necessary, never sufficient. Before merge-block coverage is trusted for a new supplier domain, the suite shall add cross-domain smoke cases and adversarial fixtures (authority aliasing, circular references, license-restricted corpora). Golden-correctness cases and heuristic-detector evaluation are tracked separately, and coverage is reported by failure mode and standard family, not only case count.

## 16. Build and Learning-Loop Integration
Deterministic CHECK vs probabilistic evaluation are separated. §15's golden cases and all §9.1 gate assertions run as deterministic pytest in the target repo; these enforce the merge-block mechanically. A parent roll-up truth-table test (§1.1) is part of this deterministic set. Model-derived proposal quality (remap, evidence linking, authority recall, calibration) is measured separately as a probabilistic evaluation against a versioned held-out corpus with defined metrics — it does not masquerade as a deterministic gate.
MVP kill-criteria (build-commitment gate). Before build commitment, numeric thresholds shall be defined and published for: maximum false-CW rate on process-sensitive classes (authority, reuse, NDE-chain, remap), minimum authority-classifier recall, maximum evidence-linker false-link rate, and maximum acceptable fraction of a golden package left OPEN. If measured performance misses these thresholds, v1 ships as an assisted matrix + gates only, and remap/authority are not asserted as solved IP. The specific threshold values are a product/domain calibration decision (§14 open question, HUMAN_REVIEW).
Reproducibility contract. Every evaluation run shall version and retain the model identity/weights, prompts, retrieval index, extraction/OCR output, and the immutable per-run confidence/link thresholds, so a benchmark result is reproducible and cannot be silently passed by hard-coded case behavior. Where full determinism is infeasible, results are reported as distributions with adjudication rules.
Threshold versioning. Confidence and evidence-link thresholds are versioned immutably per run; a later run cannot retroactively re-classify a prior run's units by lowering a threshold.
The fixture grows by retro. Every future expert correction from a production run becomes a new labeled case within one release cycle of the correction.
Spec-versus-fixture drift is a test. spec_rules pointers in the fixture reference this spec's section numbers; numbering is frozen (extensions add subsections, never renumber), and a test asserts every spec_rules pointer resolves to an existing section. Run builds with a diff-coverage floor (≥80).

## 17. Assurance and Record Controls (Compliance Basis)
The header marks SWE-013, SWE-033, and NASA-STD-8739.8B and Safety Critical as TARGET / UNCONFIRMED claims. A provenance matrix is not by itself a controlled compliance record; these claims require the following controls, and the assurance posture (commit to the full assurance case vs. scope the Safety-Critical claim to advisory outputs) is a human/domain decision owed before build. Until that decision and its evidence exist, no safety-critical or compliance badge is asserted.
Record integrity. Disposition units, acceptance records, human elections, and workflow_state transitions are append-only with an immutable audit history; edits create new versions, never overwrite.
Authorization and role qualification. Every non-proposed workflow_state transition, human confirmation, and customer acceptance requires an identified, authorized, qualified role; the authorization model is recorded per action.
Signature controls. Acceptance records (§7) carry electronic approval controls sufficient for the levied contract's requirements.
Retention, residency, and pipeline rights. Retention, tenant/data residency, and deletion policies are defined for controlled content, customer work product, logs, caches, retrieval indexes, model-inference transfers, and fixtures. Rights classification (§7.1) is enforced at each such operation, including approved-model boundaries and tenant isolation.
Change control. Models, prompts, rule sets, thresholds, extractors, and fixtures are version-controlled; a change that affects disposition logic is gated by §15 and §16.
Evaluator independence. The probabilistic evaluation corpus (§16) is held out from any tuning loop; evaluator and proposer inputs are separated, and the evaluation environment honors the same pipeline-rights controls.
Hazard and criticality decomposition. A hazard list identifies which outputs are advisory versus process-sensitive (authority, reuse, NDE-chain, remap), and the verification effort is weighted to the process-sensitive classes. A false CW/MI on these classes is treated as the top hazard and is bound to the §16 kill-criteria.
Rule: until §17 controls are specified, implemented, verified, and traced to the claimed clauses, either the compliance/Safety-Critical claim is scoped down (advisory-only, explicitly labeled) or these controls are release-blocking prerequisites. This decision requires domain authority and is routed to human review.



This communication and its attachments are privileged and confidential. Generated by ORACLE — BoundState AI LLC.