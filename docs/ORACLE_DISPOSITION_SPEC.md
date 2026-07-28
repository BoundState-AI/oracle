# Oracle Disposition Module: Functional Specification

> **SUPERSEDED by v0.4.0** — the ORACLE convergence run (session
> 20260728-191953, 2 rounds, consensus BLOCKED → human review, 25 accepted
> defects) produced a revised spec incorporating both review rounds. The
> authoritative post-run version and full run record live in
> `docs/oracle_runs/20260728-191953_disposition_spec/`. This 0.2.0 file is
> retained as revision history only.

**Module:** `boundstate/core/oracle/` *(final home + name: open question 6, §14 — collides with the ORACLE adversarial review engine in the oracle repo)*
**Purpose:** Disposition an uploaded supplier document against a levied standard, requirement by requirement, with traceable provenance
**Version:** 0.2.0 (draft — Beth revision, awaiting ORACLE convergence run)
**Classification:** BoundState Proprietary
**Compliance:** SWE-013, SWE-033, NASA-STD-8739.8B
**Safety Critical:** True

**Derivation:** This spec is reverse-engineered from a complete manual Oracle run performed 2026-07-28: NASA-STD-6030 (115 requirements) and NASA-STD-6033 (31 requirements) dispositioned against a cold spray additive manufacturing process for a Boeing supplier flowdown, with independent expert review by Fran. Every requirement below traces to an observed failure or an observed necessity in that run. The companion regression fixture is `oracle_eval_cs6030.json`.

**Revision 0.2.0 (Beth):** Section numbering of 0.1.0 is frozen — the fixture's `spec_rules` pointers cite these numbers. Changes: §15 case count corrected (was itself a typed-count violation) and merge-block extended to `expert_discovered`; §3.1 gains the process capability model §6 always depended on, plus typed scope declarations; §4.1 authority scan made explicitly per-standard across the levied set (case 16); §11 gains accepted-exception propagation and derived scope declarations (cases 17, 21); §2.3 closes the OPEN sub-reason vocabulary; §7 schema gains `open_sub_reason`, `control_class`, `applicability_clause`; §9 split into blocking gates and mandatory review flags with seven new checks; §14 gains placement and licensing-adjacent questions; §16 (new) wires the fixture into the build pipeline and the learning loop.

---

## 1. Scope and Non-Goals

### 1.1 What Oracle does

Given (a) a controlled standard, (b) an uploaded supplier document set, and (c) a declared scope, Oracle assigns exactly one disposition code to every requirement in the standard, with the requirement text, a locator, an evidence pointer, and a calibrated confidence.

### 1.2 What Oracle does NOT do

**Oracle does not render engineering judgment.** It proposes; a qualified engineer disposes. In the reference run, 85 of 115 dispositions were machine-proposable, an expert reviewer found substantive errors in that proposal set, and the errors clustered exactly where the proposer's confidence was already flagged low. Oracle's product value is provenance, bookkeeping, and consistency enforcement, not disposition authorship.

**Design consequence:** Oracle output is never released as a compliance package. It emits a working matrix that a human confirms row by row. Any UI or API affordance that permits bulk-accept of unconfirmed rows is a defect.

---

## 2. Disposition Codes

Five codes. Four is not enough; this was the single most important structural finding of the reference run.

| Code | Meaning | Contract effect |
|------|---------|-----------------|
| `CW` | Complies as written | Literal requirement retained; cited evidence demonstrates implementation |
| `MI` | Intent met by alternative means | Literal wording or mechanism not used; equivalent control meets technical intent. **A formal exception requiring customer acceptance, not a claim of compliance** |
| `EX` | Exception requested | Requirement not met as written; customer must accept the stated alternative, limit, or contractual route before use |
| `NA` | Not applicable | Outside declared scope; the cited scope declaration must remain true |
| `OPEN` | Evidence or decision incomplete | **Not an externally releasable disposition** |

### 2.1 The OPEN requirement (BLOCKING)

A document-versus-standard run generates a large population of "the uploaded document is silent on this requirement." That is categorically distinct from "does not meet." Without `OPEN`, Oracle converts silence into compliance, which is the worst available failure mode for this product.

**Rule:** absence of evidence maps to `OPEN` (sub-reason `evidence_absent`), never to `CW` and never to `NA`.

**Rule:** a package containing any `OPEN` row cannot be marked release-ready. `OPEN` count is a gate, not a metric.

### 2.2 MI is an exception, not a compliance

`MI` rows must render in customer-facing output under the exception heading, never under the compliance heading. In the reference run an early draft summarized `MI` as "comply as tailored," which invited the reader to treat 38 formal exceptions as compliances.

### 2.3 OPEN sub-reasons are a closed vocabulary *(new in 0.2.0)*

Every `OPEN` row **shall** carry exactly one sub-reason from this controlled list. An `OPEN` row with a missing or unlisted sub-reason is a defect. The §12 gate report groups by sub-reason, and regression cases assert sub-reasons, so the vocabulary is part of the module's contract:

| Sub-reason | Source rule | Meaning |
|---|---|---|
| `evidence_absent` | §2.1 | Uploaded document set is silent on the requirement |
| `scope_decision_not_made` | §8 | A customer/business decision the disposition depends on does not exist yet |
| `authority_unidentified` | §4.1 | The requirement names an approval role nobody has identified |
| `approval_not_exercised` | §4.1 | The authority is identified but the named approval has not occurred |
| `referenced_artifact_missing` | §7.2 | A cited attachment/register/annex does not resolve in the controlled document system |
| `referenced_standard_unavailable` | §11 | An outbound standard reference is not in the corpus |
| `dependency_eliminated` | §11 | A mechanism this disposition relied on was eliminated by an accepted exception elsewhere |

Extending this vocabulary is a spec revision, not an implementation convenience.

---

## 3. Intake: Scope Declarations (BLOCKING)

Oracle **shall not** begin disposition until a scope declaration set is captured. In the reference run, 17 of 115 requirements were not applicable, and 13 of those were polymer-section requirements against a metallic process. Without scope intake, Oracle will earnestly disposition polymer requirements against a metallic feedstock and produce confident nonsense.

### 3.1 Minimum intake fields

*(0.2.0: adds the process capability model that §6 has always depended on, and types every scope declaration. In 0.1.0, §6.1 required "the process capability model from intake" while this schema captured none — the NA-versus-zero-limit distinction was undecidable from the declared fields.)*

```python
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
                "basis": str            # why: equipment, physics, configuration
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
```

**Rule:** a declaration of type `physical_impossibility` **shall** cite a capability-model entry with `physically_possible: false`. A declaration phrased as "we do not do X" where the capability model says the process can do X is type `policy`, and §6.1 governs its use.

**Rule:** declarations of type `derived` are minted during the run by §11 propagation (the SD-7 pattern in the reference run), carry the case or exception that produced them, and are otherwise first-class: dispositions cite them, and changes reopen dependents per §3.2.

### 3.2 Scope declarations are load-bearing and must be traceable

Every `NA` disposition **shall** cite the scope declaration ID that supports it. An `NA` with no scope citation is a defect, not a disposition.

**Rule:** if a scope declaration changes, Oracle **shall** reopen every disposition that cites it and downgrade those rows to `OPEN`. Scope change invalidates dependent dispositions silently otherwise. This is the dependency-graph requirement; see `document-cartography`.

---

## 4. Authority-Dependent Requirements (BLOCKING)

**The highest-consequence finding of the reference run.**

NASA-STD-6030 references the Cognizant Engineering Organization 109 times; 18 requirements name an approving authority inside the requirement text itself (AMR-2, 3, 4, 5, 13, 14, 21, 34, 35, 58, 60, 67, 97, 99, 110, 111, 112, 113). These requirements govern part classification, part acceptance, readiness review, and configuration control, the gates between qualification and delivery.

**A requirement that names an approval authority can never be dispositioned `CW` from a document alone.** No uploaded document can demonstrate that an unidentified organization approved something. In the reference run, this class was nearly shipped as `CW`, which would have asserted compliance with an approval chain that had never been exercised.

### 4.1 Required behavior

Oracle **shall** detect authority-naming requirements by scanning requirement text for approval-role tokens (cognizant engineering organization, CEO, Technical Authority, M&P organization, fracture control board, program, project, customer-designated equivalents) and classify them as `authority_dependent = true`.

**Rule (0.2.0, case 16):** the authority scan **shall** run independently over *every standard in the levied set*, including standards pulled in by §11 reference walking. In the reference run the analysis was performed on the primary standard only; the secondary standard carried its own parallel approval chain, and its first requirement went undispositioned. A levied set with any unscanned member fails the §9 gate.

**Rule (0.2.0, §14.3 interaction):** the role-token list is a seed, not a definition. Customer overlays rename roles; the intake record **shall** capture customer-specific authority titles, and the scan **shall** include them.

For each such requirement:

1. If the responsible authority is **not identified** in intake → disposition is `OPEN`, sub-reason `authority_unidentified`. Never `CW`.
2. If the authority **is identified** but the approval has not occurred → `OPEN`, sub-reason `approval_not_exercised`.
3. If the authority is identified and approval evidence is cited → `CW` with the approval record as the evidence pointer.
4. If the customer route deliberately bypasses the standard's named authority chain → `EX`, with the alternative authority basis stated.

### 4.2 The authority report

Oracle **shall** emit, as a first-class output, an authority dependency report answering: *which requirements' dispositions depend on an authority nobody has identified?* — broken out per standard in the levied set.

In the reference run this query was the single most valuable output produced, it was produced by hand, and it was produced last, after a full document had been drafted on top of an unexamined assumption about who held the approval role. Surfacing it at intake would have changed the entire package structure.

**Rule:** the authority report renders before the disposition matrix in all output orderings.

---

## 5. Definitional Remap Detection

This is the core technical IP and the primary generator of `MI` rows.

A standard written for one physical process, levied on a different process, contains requirements phrased in physics the target process does not have. In the reference run: melt pool geometry, focused thermal energy, energy source parameters, melt-based build area. These have no referent in solid-state deposition.

### 5.1 Required behavior

Oracle **shall** detect requirement text containing process-physics terms absent from the uploaded process definition, and propose an `MI` disposition with a remap candidate: the target-process variable that serves the same control function.

**Rule:** a remap proposal **shall** carry the intent statement of the source requirement, so the reviewer evaluates whether the substitute serves that intent rather than whether the words look similar.

**Rule:** remaps apply per subparagraph, never per requirement. In the reference run, one requirement's subparagraph (e) required melt-pool metrics while subparagraphs (a) through (d) applied unchanged. Remapping the whole requirement would have silently voided four applicable controls.

### 5.2 Anti-pattern: the false generalization

The reference run produced the claim "every enumerated process in the standard has a melt pool," used to argue the target process was out of scope. This was **false**, the standard's enumerated set included non-fusion polymer processes. The correct and stronger argument came from the standard's own definition of the process class in question (focused thermal energy fusing material by melting), which the target process plainly does not match.

**Rule:** exclusion arguments **shall** be built from the standard's own definitions section, never from an inductive generalization over the enumerated set. Oracle **shall** cite the definition and its locator.

---

## 6. The N/A Versus Zero-Limit Distinction

A subtle finding with direct audit consequence.

Two requirements governed feedstock reuse. The process declared no reuse, so an initial pass coded them `NA`. Expert review reversed this to `MI`: the process is **physically capable** of powder recovery, so the requirement applies and is met by a controlled operating limit of zero, with quarantine, scrap, and material-balance records as evidence. The `NA` version is the one that fails an audit, an auditor who observes recovered powder anywhere in the facility will pull that thread.

### 6.1 Required behavior

Oracle **shall** distinguish:

- **`NA` by physical impossibility**, the process cannot produce the condition the requirement governs (a wire-feedstock requirement against a powder-fed process). Cites a `physical_impossibility` scope declaration, which cites the capability model (§3.1).
- **`MI` by controlled limit**, the process can produce the condition, but a declared and evidenced control holds it at zero or within bounds.

**Rule:** when a scope declaration is phrased as a *policy* ("we do not do X") rather than a *physical impossibility* ("this process cannot do X"), Oracle **shall** propose `MI` with a zero-limit control and flag `NA` as the weaker alternative, with the audit exposure stated.

This distinction is not detectable from the requirement text alone. It requires the capability model captured at intake (§3.1), which is why §3 is blocking.

---

## 7. Provenance Requirements (SWE-013 / SWE-033)

Every disposition row **shall** carry:

```python
{
    "requirement_id": str,          # e.g. "AMR-51(e)"
    "requirement_text": str,        # VERBATIM from the controlled standard
    "applicability_clause": Optional[str],  # VERBATIM extraction of the requirement's
                                    # own stated applicability (0.2.0, case 12: class
                                    # was conflated with fracture classification when
                                    # applicability was recalled instead of extracted)
    "locator": {                    # page and section, for reviewer verification
        "standard": str,
        "revision": str,
        "section": str,
        "page": int
    },
    "code": str,                    # CW | MI | EX | NA | OPEN
    "open_sub_reason": Optional[str],   # REQUIRED when code == OPEN; §2.3 vocabulary
    "scope_citation": Optional[str],# REQUIRED when code == NA; also carried by
                                    # MI zero-limit rows citing the policy declaration
    "authority_dependent": bool,
    "intent_statement": Optional[str],  # REQUIRED when code in (MI, EX)
    "alternative_control": Optional[str],# REQUIRED when code in (MI, EX)
    "control_class": Optional[str], # "integral" | "disclosed" per §10.1; REQUIRED
                                    # whenever alternative_control is present
    "evidence": [                   # REQUIRED when code in (CW, MI)
        {
            "doc_id": str,
            "revision": str,
            "locator": str
        }
    ],
    "confidence": float,            # 0.0-1.0, calibrated per §8
    "proposer": str,                # model or human identity
    "confirmed_by": Optional[str],  # human confirmation, null until confirmed
    "confirmed_date": Optional[str]
}
```

### 7.1 Hard rules

**Rule:** no `CW` or `MI` row is release-eligible without at least one evidence identifier with a revision. A description of an intended control is not evidence.

**Rule:** requirement text is extracted from the controlled standard, never paraphrased or recalled. The reference run propagated an incorrect handbook title through four document revisions because it was inherited from a prior summary and never checked against the source. Every assertion Oracle emits about a standard **shall** be extractable and locatable. The same rule covers the `applicability_clause` field.

**Rule:** every count in every generated narrative **shall** be computed from the matrix at render time. Never typed, never carried forward. The reference run summarized a disposition split (61/38/16) that summarized nothing, the matrix it described did not exist, and that fabricated split survived three document revisions and a leadership briefing before anyone checked. *(This rule applies to this spec's own companion documents: see §15.)*

### 7.2 The referenced-artifact check

**Rule:** Oracle **shall not** emit a reference to an attachment, register, or annex that does not exist as a controlled artifact in the system. In the reference run, the source memo cited three attachments by name and revision date, described their contents, and asserted a complete disposition of all 115 requirements. None of the three existed. Downstream drafts inherited the citations and repeated the claim.

Implementation: reference emission is gated on artifact resolution. Unresolvable reference → `OPEN` with sub-reason `referenced_artifact_missing`.

---

## 8. Confidence Calibration

Per `recommendation-policy`, confidence is derived, never asserted. Proposal confidence bands:

| Band | Basis | Reviewer action |
|------|-------|-----------------|
| HIGH | Requirement text is unambiguous, scope citation is direct, no authority dependency, no remap | Skim |
| MEDIUM | Disposition depends on a referenced table or subparagraph set not yet examined, or on a routing decision consistent with another open entry | Verify against source |
| LOW | Disposition depends on a scope decision the customer has not made, or on process capability not established at intake | **Human decision required; Oracle proposes nothing** |

**Rule:** LOW-confidence rows render as questions to the reviewer, not as proposed codes with a caveat. The row's code is `OPEN` with the applicable §2.3 sub-reason (`scope_decision_not_made` for undecided scope questions). In the reference run, two rows (in-situ monitoring credited for part acceptance; joining operations in scope) were genuine scope decisions with large downstream consequence. Presenting a proposed code on those rows invites confirmation of a guess.

**Rule (0.2.0, case 19):** where a scope question governs paired requirements across standards (e.g., in-situ monitoring in both the primary and secondary standard), the question is asked once and its answer **shall** be applied to every paired row. Divergent answers to one question is a §9 consistency failure.

**Rule:** confidence is reported per row and never aggregated into a package-level score. A package-level confidence number invites bulk acceptance.

---

## 9. Consistency Enforcement

The reference run's expert review found four internal contradictions in a document that read as authoritative, and the fixture adds several more mechanically detectable classes. *(0.2.0 splits the checks: 9.1 gates block release; 9.2 flags force explicit reviewer election and block only until each flag is dispositioned by a human.)*

### 9.1 Blocking gates

| Check | Rule | Observed failure |
|-------|------|------------------|
| Single code | Exactly one code per requirement | One requirement was coded `NA` while also appearing inside an exception entry |
| Code/narrative agreement | A row whose narrative states "no relief is requested" **shall** be `CW`, not `MI` | Requirement coded `MI` with a narrative asserting full compliance |
| Exception membership | A requirement coded `CW` or `NA` **shall not** appear in an exception entry | An exception entry was constructed around a requirement to which no exception was taken |
| Count reconciliation | Narrative counts **shall** equal matrix counts at render time | Narrative reported a split that no matrix produced |
| Unresolved markers | Zero placeholder tokens in release-marked output | Placeholder markers and internal action notes survived into a release-candidate draft |
| Authority coherence | A disposition asserting customer approval authority **shall not** coexist with a request asking the customer to confirm it holds that authority | The same document declared the customer to be the approval authority and asked whether it was |
| Levied-set authority scan | Every standard in the levied set has a completed §4.1 scan | Secondary standard's approval chain missed entirely (case 16) |
| NA basis typing | Every `NA` cites a scope declaration; citing a `policy`-typed declaration is a gate failure — §6.1 requires the `MI` zero-limit form or an explicit reviewer override | Policy scope coded as physical impossibility (cases 4, 5) |
| Paired dispositions | Rows paired on one scope question carry the same answer | Divergence risk across primary/secondary standards (case 19) |
| Sub-reason validity | Every `OPEN` row carries exactly one §2.3 sub-reason | Vocabulary previously uncontrolled |

### 9.2 Mandatory review flags (block until a human dispositions the flag)

| Flag | Detection | Observed failure |
|------|-----------|------------------|
| Universal negative in exception rationale | "no ... exists", "there is no", "cannot be demonstrated by anyone" patterns in `EX`/`MI` narrative | "No representative demonstration exists" asserted about the world instead of the supplier's own evidence (case 13) |
| Waiver language on a compliance row | decline/waive/foreclose phrasing in a `CW` narrative | A chosen means of compliance framed as declined relief (cases 6, 10) |
| Relief path foreclosed | Disposition narrative forecloses an exception clause, "unless" condition, or alternative route the requirement's own text grants (§10.1) | Relief volunteered away without reviewer election (case 6) |
| Remap granularity | An `MI` remap spanning a whole requirement whose subparagraphs are not uniformly affected | Whole-requirement remap would have voided four applicable controls (case 3) |
| Unit of analysis | Quantified nouns in the requirement text and the citing scope declaration disagree (material vs material family) | Machine count misstated by a factor of the family size (case 14) |
| Borrowed terminology | Narrative terms absent from both the standard's definitions and the process definition | "Wetted components" imported into a dry powder process (case 15) |

**Rule:** these checks run as a release gate and block, not as warnings. A 9.2 flag is cleared only by a recorded human election, which becomes part of the row's provenance.

---

## 10. Voluntary Expansion Guard

A supplier compliance document that volunteers controls beyond the standard converts prudent internal practice into permanent contractual obligation, and may waive relief the standard already offers.

In the reference run, an early draft made voluntary supplemental controls part of the contractual baseline and explicitly declined an exception path the standard itself provided. Expert review flagged this as self-binding. A separate draft voluntarily adopted a polymer-section requirement for metallic use and extended it beyond the class the requirement targets (case 9).

### 10.1 Required behavior

Oracle **shall** classify every control it emits as:

- **`integral`**, required to support a stated `MI` or `EX` disposition. Enters the contractual baseline.
- **`disclosed`**, internal practice, shown for visibility. **Shall** render with an explicit non-binding statement and **shall not** appear in any compliance obligation list.

**Rule:** Oracle **shall not** emit a disposition that waives an exception path the standard grants, unless the reviewer explicitly elects that waiver. Detect by scanning requirement text for the standard's own relief provisions (exception clauses, "unless" conditions, alternative approval routes) and flag any disposition that forecloses one (§9.2).

**Rule (0.2.0, case 9):** a requirement dispositioned `NA` **shall not** simultaneously be "adopted voluntarily" inside the compliance package. The underlying engineering practice, if kept, is recorded as a `disclosed` control in internal process documents and never in the contractual baseline.

---

## 11. Cross-Standard Dependency Walking

Requirements reference other standards, which impose their own requirements. In the reference run: a requirement in the primary standard invoked a second standard's agreement mechanism, which invoked a fracture control standard, which invoked an NDE standard with its own detection-capability requirement, which was ultimately governed by a handbook's applicability conditions. The disposition was only defensible once the whole chain was walked.

**Rule:** Oracle **shall** resolve outbound references from requirement text and surface the dependent obligations. Where a referenced standard is not in the corpus, the dependent disposition is `OPEN`, sub-reason `referenced_standard_unavailable`, never assumed satisfied. See `document-cartography` for the graph schema.

**Rule:** referenced standards **shall** be cited at their current issuance with revision, verified against the corpus, not recalled.

### 11.1 Accepted-exception propagation *(new in 0.2.0 — cases 17 and 21, the fixture's highest-value findings)*

An accepted `EX` (or `MI`) can eliminate a mechanism or artifact that other requirements' dispositions silently rely on. In the reference run: the alternative contractual route eliminated an agreement mechanism, which (a) invalidated a `CW` in the secondary standard that presupposed the eliminated control plan (case 17), and (b) removed the lot-provisional allowables bridge for the middle part class — a consequence visible in no single requirement's text, discovered only by expert graph reasoning, and carrying real schedule cost (case 21).

**Rule:** when a disposition is accepted that eliminates a mechanism, artifact, or route, Oracle **shall** walk the dependency graph and reopen every disposition whose basis references the eliminated element: those rows revert to `OPEN`, sub-reason `dependency_eliminated`, citing the eliminating disposition.

**Rule:** where the elimination narrows what the supplier can do (the SD-7 pattern), Oracle **shall** mint a `derived` scope declaration (§3.1) recording the consequence, so it binds future dispositions and renders in the §12 scope record.

**Rule:** propagation runs to fixpoint — a reopened row whose re-disposition eliminates further mechanisms triggers another pass.

---

## 12. Output Contract

Oracle emits, in this order:

1. **Authority dependency report** (§4.2), what cannot be dispositioned until an approval role is identified — per standard in the levied set
2. **Scope declaration record** (§3), including `derived` declarations, with every dependent disposition indexed
3. **Disposition matrix**, one row per requirement, schema per §7, in the standard's own compliance-matrix format where the standard provides one
4. **Exception detail**, one entry per `MI` and `EX` row: requirement, intent, alternative control, limit of requested acceptance, closure evidence
5. **Gate report**, `OPEN` count broken out by §2.3 sub-reason, missing evidence IDs, failed §9.1 gates, undispositioned §9.2 flags, unresolved references
6. **Narrative summary**, generated from 1 through 5, never hand-authored, all counts computed

**Rule:** the narrative is a view of the matrix. The matrix is the artifact. Any workflow in which the narrative is authored first and the matrix back-filled reproduces the reference run's entire error class.

---

## 13. Performance Targets

Per `boundstate-architecture`:

- Standard ingestion and requirement extraction: < 60 s for a 200-page standard
- Full disposition proposal pass, 150 requirements: < 5 min
- Authority dependency report: < 5 s
- Consistency gate: < 2 s
- Matrix render: < 10 s
- §11.1 propagation pass: < 5 s per accepted exception

---

## 14. Open Design Questions

1. **Evidence matching.** Mapping uploaded supplier documents to the requirements they satisfy is unsolved here. Semantic retrieval proposes candidates; the reviewer confirms. Precision matters far more than recall: a wrong evidence pointer on a `CW` row is worse than an `OPEN`.
2. **Standard revision drift.** When a standard is revised, dispositions must be diffed against the new text, not carried forward. Requires requirement-level versioning in the corpus.
3. **Customer-specific overlays.** Primes levy standards with their own tailoring. Oracle needs a layer for customer-modified requirement text that supersedes the base standard — including customer-renamed authority roles (§4.1).
4. **Corpus licensing.** Verify redistribution rights before embedding verbatim requirement text in customer-facing output. (NASA technical standards in the reference run are publicly released; prime-contractor overlays are not.)
5. **Work-product rights.** Where a disposition run is performed under a customer purchase order, confirm data-rights and IP clauses before reusing the methodology or output as product material.
6. **Placement and naming** *(new in 0.2.0)*. `boundstate/core/oracle/` plus the skill references (`document-cartography`, `recommendation-policy`, `boundstate-architecture`) put this module in the MIRA codebase — but "Oracle" already names the multi-oracle adversarial review engine, and that repo carries a different `ORACLE_SPEC.md`. Recommendation: build in MIRA under a distinct module name (e.g., `disposition/`), keep "Oracle" as the product-facing name only, and decide before the build pipeline targets a repo.
7. **Fixture rights and confidentiality** *(new in 0.2.0)*. The fixture encodes corrected dispositions from a customer flowdown. Confirm it can live in the product repo as regression data, or scrub identifying scope declarations first.

---

## 15. Regression Fixture

`oracle_eval_cs6030.json` — 26 labeled cases from the reference run *(0.1.0 said 24: a typed count that violated §7.1's own rule; the label breakdown below is computed from the fixture and must be re-computed, not edited, when cases are added)*: 19 `expert_corrected`, 3 `correct_positive`, 2 `must_not_propose`, 2 `expert_discovered`. Each case carries the requirement, the initially proposed disposition, the corrected disposition, the failure mode, and the rule from this spec that the case exercises.

**Rule:** a change to disposition logic that regresses any case labeled `expert_corrected` **or `expert_discovered`** blocks merge *(0.2.0: extended to match the fixture's own regression policy; 0.1.0 named only `expert_corrected`, which would have let the two highest-value graph-reasoning cases regress silently)*.

**Rule:** `must_not_propose` cases assert that Oracle emits `OPEN` and a reviewer question. Emitting any code on these cases is a failure regardless of which code.

**Rule:** fixture counts and label breakdowns cited anywhere (including this section) are computed from the fixture file at test time. The test suite **shall** contain an assertion that this spec's stated case count matches the fixture, so the two cannot drift.

---

## 16. Build and Learning-Loop Integration *(new in 0.2.0)*

1. **The fixture is the CHECK stage's seed corpus.** When this module is built through the oracle build pipeline, `oracle_eval_cs6030.json` cases run as pytest assertions in the target repo: the pipeline's deterministic CHECK enforces §15's merge-block mechanically, before any reviewer tokens are spent. Run builds with a diff-coverage floor (≥80).
2. **The fixture grows by retro.** Every future expert correction from a production disposition run becomes a new labeled case, added with the same schema, within one release cycle of the correction. The fixture's own coverage note is the operating assumption: passing it is necessary, never sufficient — 26 cases from one run, two standards, one process domain.
3. **Spec-versus-fixture drift is a test.** `spec_rules` pointers in the fixture reference this spec's section numbers; section numbering is therefore frozen (extensions add subsections, never renumber), and a test asserts every `spec_rules` pointer resolves to an existing section.
