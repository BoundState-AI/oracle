"""Schema and required-field tests per §7 for DispositionUnit. BoundState AI 2026.

Lightweight header per repo convention for test modules.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oracle.disposition.codes import DispositionCode, OPENSubReason
from oracle.disposition.models import (
    AcceptanceRecord,
    ApprovedScope,
    CapabilityModelEntry,
    DispositionUnit,
    EvidenceEntry,
    LevyManifest,
    LevyManifestEntry,
    Locator,
    SCHEMA_VERSION,
    RULE_VERSION,
    ScopeDeclaration,
    transition_unit,
    validate_locator_covered_by_manifest,
    validate_physical_impossibility_declaration,
)
from oracle.disposition.rollup import rollup_badge
from oracle.disposition.state import Actor  # keep for any remaining boundary/transition tests that need it


def _base_unit(**overrides) -> dict:
    base = {
        "unit_id": "AMR-99",
        "is_rollup": False,
        "requirement_text": "The supplier shall ...",
        "locator": {
            "standard": "NASA-STD-6030",
            "revision": "Baseline",
            "section": "4.2",
            "page": 17,
            "schema_version": SCHEMA_VERSION,
            "rule_version": RULE_VERSION,
        },
        "code": "CW",
        "workflow_state": "proposed",
        "authority_dependent": False,
        "authority_classification": "pending_review",
        "evidence": (),  # model is now frozen + tuple for evidence
        "confidence": 0.8,
        "proposer": "oracle/proposal-v1",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        # High #3 / §7.3: non-rollup units carrying a code require confirmed boundary at construction
        "unit_boundary_confirmed_by": "extractor-human-1",
    }
    base.update(overrides)
    return base


def test_unknown_fields_rejected():
    """extra='forbid' everywhere."""
    data = _base_unit()
    data["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        DispositionUnit(**data)


def test_open_requires_exactly_one_subreason():
    data = _base_unit(code="OPEN", open_sub_reason="evidence_absent")
    u = DispositionUnit(**data)
    assert u.code == DispositionCode.OPEN
    assert u.open_sub_reason == OPENSubReason.EVIDENCE_ABSENT

    # Missing sub-reason
    bad = _base_unit(code="OPEN")
    with pytest.raises(ValidationError):
        DispositionUnit(**bad)

    # Unknown sub-reason
    bad2 = _base_unit(code="OPEN", open_sub_reason="not_in_vocab")
    with pytest.raises(ValidationError):
        DispositionUnit(**bad2)


def test_na_requires_scope_citation():
    data = _base_unit(code="NA", scope_citation="SD-3")
    u = DispositionUnit(**data)
    assert u.scope_citation == "SD-3"

    bad = _base_unit(code="NA")
    with pytest.raises(ValidationError):
        DispositionUnit(**bad)


def test_mi_and_ex_require_intent_alt_control_class():
    for code in ("MI", "EX"):
        data = _base_unit(
            code=code,
            intent_statement="Maintain traceability of feedstock lots",
            alternative_control="Serial-numbered lot tags + material balance log",
            control_class="integral",
        )
        u = DispositionUnit(**data)
        assert str(u.code) == code

        # Missing one required field
        bad = _base_unit(code=code, intent_statement="x", alternative_control="y")
        with pytest.raises(ValidationError):
            DispositionUnit(**bad)


def test_rollup_must_not_carry_code_and_must_have_vector():
    data = _base_unit(
        unit_id="AMR-50",
        is_rollup=True,
        code=None,
        composition_vector={"CW": 3, "NA": 1},
    )
    # code should be omitted or None; model normalizes via validator
    u = DispositionUnit(**data)
    assert u.is_rollup is True
    assert u.code is None
    assert u.composition_vector == {"CW": 3, "NA": 1}

    # Rollup with a code is illegal
    bad = _base_unit(is_rollup=True, code="CW", composition_vector={"CW": 2})
    with pytest.raises(ValidationError):
        DispositionUnit(**bad)

    # Rollup without vector is illegal
    bad2 = _base_unit(is_rollup=True, code=None, composition_vector=None)
    with pytest.raises(ValidationError):
        DispositionUnit(**bad2)


def test_rollup_parent_rejects_acceptance_and_evidence_medium4():
    """Medium #4 (Atlas R3 #4): roll-up parents must never carry disposition-only fields.

    Per §1.1 a parent is never a disposition target. Acceptance and evidence
    are disposition-only; constructing an accepted roll-up parent must fail.
    """
    from oracle.disposition.models import AcceptanceRecord, ApprovedScope, EvidenceEntry

    acc = AcceptanceRecord(
        id="ACC-P",
        status="accepted",
        customer_authority="Acme QA",
        approval_artifact="ART-P",
        approved_scope=ApprovedScope(
            configurations=("c1",),
            part_classes=("P1",),
            valid_from="2026-01-01",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        ),
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    ev = EvidenceEntry(
        doc_id="D-P",
        revision="R1",
        locator="s:1",
        link_confidence=0.9,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # Accepted roll-up parent with acceptance
    bad_acc = _base_unit(
        unit_id="AMR-50P",
        is_rollup=True,
        code=None,
        composition_vector={"CW": 1},
        acceptance=acc,
    )
    with pytest.raises(ValidationError, match="must not carry an acceptance record"):
        DispositionUnit(**bad_acc)

    # Roll-up with evidence is also rejected
    bad_ev = _base_unit(
        unit_id="AMR-50P2",
        is_rollup=True,
        code=None,
        composition_vector={"CW": 1},
        evidence=(ev,),
    )
    with pytest.raises(ValidationError, match="must not carry evidence entries"):
        DispositionUnit(**bad_ev)


def test_parent_id_optional_and_hierarchical_ids_allowed():
    data = _base_unit(unit_id="AMR-51(e)", parent_id="AMR-51")
    u = DispositionUnit(**data)
    assert u.parent_id == "AMR-51"


def test_rollup_validator_returns_self_explicitly():
    """Cover the explicit return self for valid rollup (models.py:254)."""
    data = _base_unit(
        unit_id="AMR-50",
        is_rollup=True,
        code=None,
        composition_vector={"CW": 2, "NA": 1},
    )
    u = DispositionUnit(**data)
    assert u.is_rollup is True
    assert u.code is None


def test_open_with_extraneous_fields_logs_but_succeeds():
    """OPEN path that hits the extraneous-field debug log (models.py:263)."""
    import logging

    logger = logging.getLogger("oracle.disposition.models")
    prev = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        data = _base_unit(
            code="OPEN",
            open_sub_reason="evidence_absent",
            scope_citation="SD-9",  # extraneous for OPEN
        )
        u = DispositionUnit(**data)
        assert u.code == DispositionCode.OPEN
        assert u.open_sub_reason == OPENSubReason.EVIDENCE_ABSENT
        # scope_citation may be present; the model allows it but logs at debug
        assert u.scope_citation == "SD-9"
    finally:
        logger.setLevel(prev)


def test_non_rollup_without_code_raises_specific_error():
    """Hits the explicit 'Non-rollup disposition units require a code' raise (models.py:254)."""
    data = _base_unit()
    data.pop("code", None)  # ensure absent
    # is_rollup defaults False
    with pytest.raises(ValidationError) as exc:
        DispositionUnit(**data)
    assert "Non-rollup disposition units require a code" in str(exc.value)


# ----------------------------------------------------------------------------
# transition_unit basic behavior (post R4: thin wrapper, full revalidation)
# ----------------------------------------------------------------------------

def test_transition_unit_delegates_and_revalidates():
    """transition_unit returns a fully revalidated successor.

    - Delegates to apply_transition for legality/actor rules.
    - Rebuilds via normal constructor (unknown fields still rejected).
    - Per-code invariants still enforced on successor.
    """
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    u = DispositionUnit(
        unit_id="AMR-RV1",
        requirement_text="shall X",
        locator=loc,
        code=DispositionCode.CW,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )
    human = Actor(name="rev")
    succ = transition_unit(u, "human_confirmed", human)
    assert succ.workflow_state == "human_confirmed"
    assert succ is not u  # new object

    # Full revalidation: unknown fields still rejected on successor path
    data = u.model_dump()
    data["workflow_state"] = "human_confirmed"
    data["unexpected"] = "nope"
    with pytest.raises(ValidationError):
        # simulate what transition_unit does internally
        DispositionUnit.model_validate(data)

    # Per-code invariant still enforced: OPEN requires sub-reason
    u_open = DispositionUnit(
        unit_id="AMR-OP",
        requirement_text="shall Y",
        locator=loc,
        code=DispositionCode.OPEN,
        open_sub_reason="evidence_absent",
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )
    succ_open = transition_unit(u_open, "rejected", human)
    assert succ_open.workflow_state == "rejected"


# ----------------------------------------------------------------------------
# (R4 scope correction) Critical/High model_copy bypass tests removed.
# The privileged model_copy / _ALLOW / ReleaseContext surface is gone.
# transition_unit is now a thin wrapper; bypass prevention is by construction.
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# Medium #4 + #5: physical_impossibility + alternative_control invariants
# ----------------------------------------------------------------------------

def test_scope_physical_impossibility_requires_capability_ref():
    """physical_impossibility without capability_ref is rejected at model construction."""
    bad = {
        "id": "SD-PI-1",
        "declaration": "cannot do X",
        "type": "physical_impossibility",
        "capability_ref": None,
        "source": "intake",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
    }
    with pytest.raises(ValidationError):
        ScopeDeclaration(**bad)

    bad2 = {
        "id": "SD-PI-2",
        "declaration": "cannot do X",
        "type": "physical_impossibility",
        "capability_ref": "   ",
        "source": "intake",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
    }
    with pytest.raises(ValidationError):
        ScopeDeclaration(**bad2)


def test_validate_physical_impossibility_declaration_fails_closed():
    """The intake validator requires the referenced cap to be impossible and evidenced."""
    cap_ok = CapabilityModelEntry(
        id="CAP-1",
        condition="powder reuse",
        physically_possible=False,
        basis="equipment limit documented in process spec",
        basis_evidence="PS-42 §4.3",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    caps = {"CAP-1": cap_ok}

    decl_ok = ScopeDeclaration(
        id="SD-1",
        declaration="no powder reuse",
        type="physical_impossibility",
        capability_ref="CAP-1",
        source="intake",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    # Should not raise
    validate_physical_impossibility_declaration(decl_ok, caps)

    # Missing cap -> fails closed
    # Use fresh construction (model_copy disallowed on VersionedModel per High #4)
    bad_data = decl_ok.model_dump()
    bad_data["capability_ref"] = "CAP-NONE"
    decl_bad_ref = ScopeDeclaration(**bad_data)
    with pytest.raises(ValueError, match="not found"):
        validate_physical_impossibility_declaration(decl_bad_ref, caps)

    # Cap that is possible -> fails closed
    cap_possible = CapabilityModelEntry(
        id=cap_ok.id,
        condition=cap_ok.condition,
        physically_possible=True,
        basis=cap_ok.basis,
        basis_evidence=cap_ok.basis_evidence,
        schema_version=cap_ok.schema_version,
        rule_version=cap_ok.rule_version,
    )
    with pytest.raises(ValueError, match="physically_possible=False"):
        validate_physical_impossibility_declaration(decl_ok, {"CAP-1": cap_possible})

    # Cap without basis_evidence -> fails closed
    cap_no_ev = CapabilityModelEntry(
        id=cap_ok.id,
        condition=cap_ok.condition,
        physically_possible=False,
        basis=cap_ok.basis,
        basis_evidence=None,
        schema_version=cap_ok.schema_version,
        rule_version=cap_ok.rule_version,
    )
    with pytest.raises(ValueError, match="lacks basis_evidence"):
        validate_physical_impossibility_declaration(decl_ok, {"CAP-1": cap_no_ev})


# ----------------------------------------------------------------------------
# (R4 scope correction) ReleaseContext / release-gate tests removed entirely.
# Those surfaces and their tests are out of S1 scope. The inverted-supersedes
# and partial-coverage cases are gone because the code that contained them is gone.
# ----------------------------------------------------------------------------


def test_alternative_control_always_requires_control_class():
    """Medium #5: alternative_control without control_class is rejected for any code."""
    # Even for a CW (not MI/EX), supplying alternative_control demands control_class
    data = _base_unit(
        code="CW",
        alternative_control="some alt",
        # control_class intentionally omitted
    )
    with pytest.raises(ValidationError):
        DispositionUnit(**data)

    # And for MI/EX the existing path still enforces it, but now the independent rule catches it too
    data2 = _base_unit(
        code="MI",
        intent_statement="x",
        alternative_control="y",
        # control_class missing
    )
    with pytest.raises(ValidationError):
        DispositionUnit(**data2)


# ----------------------------------------------------------------------------
# High #2: immutability / frozen records (acceptance, levy, evidence containers)
# ----------------------------------------------------------------------------

def test_frozen_models_reject_mutation_and_in_place_edits():
    """High #2: frozen models + tuple containers prevent in-place mutation."""
    # Evidence list is a tuple on the unit
    u = DispositionUnit(**_base_unit(code="CW"))
    assert isinstance(u.evidence, tuple)

    # Attempting to mutate the tuple fails
    with pytest.raises((TypeError, AttributeError)):
        u.evidence.append(object())  # type: ignore[attr-defined]

    # AcceptanceRecord is frozen
    acc = AcceptanceRecord(
        id="ACC-FROZEN",
        status="proposed",
        customer_authority="Acme",
        approval_artifact="A1",
        approved_scope=ApprovedScope(
            configurations=(),
            part_classes=(),
            valid_from="2026-01-01",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        ),
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    # Normal attribute assignment on a frozen model must be rejected
    with pytest.raises((ValidationError, TypeError, AttributeError)):
        acc.status = "accepted"  # type: ignore[misc]

    # LevyManifest requires >= 1 complete entry (Medium #4)
    entry = LevyManifestEntry(
        doc_id="D1",
        revision="R1",
        effective_date="2026-01-01",
        source="levy",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    lm = LevyManifest(
        run_id="R1",
        levied_at="2026-01-01T00:00:00Z",
        documents=(entry,),
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    assert isinstance(lm.documents, tuple)
    assert len(lm.documents) >= 1
    with pytest.raises((TypeError, AttributeError)):
        lm.documents.append(object())  # type: ignore[attr-defined]

    # Empty manifest is rejected
    with pytest.raises(ValidationError):
        LevyManifest(
            run_id="R2",
            levied_at="2026-01-01T00:00:00Z",
            documents=(),
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )

    # Entry without effective_date is rejected
    with pytest.raises(ValidationError):
        LevyManifestEntry(
            doc_id="D2",
            revision="R2",
            # effective_date omitted
            source="levy",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )


def test_frozen_containers_block_in_place_mutation_on_vectors_and_payloads():
    """High #2 (Atlas R3 #3): composition_vector and requirement_payload are recursively immutable.

    In-place dict mutation must raise after construction. This is the concrete
    failure mode the reviewer described: unit.composition_vector["CW"] = -1 must fail.
    """
    vec = {"CW": 2, "NA": 1}
    payload = {"nested": {"k": [1, 2]}, "arr": ["a", "b"]}

    u = DispositionUnit(
        **_base_unit(
            is_rollup=True,
            code=None,
            composition_vector=vec,
            requirement_payload=payload,
        )
    )

    # composition_vector is a MappingProxyType (or equivalent immutable view)
    assert not isinstance(u.composition_vector, dict) or type(u.composition_vector).__name__.endswith(
        "Proxy"
    )
    with pytest.raises((TypeError, AttributeError, RuntimeError)):
        u.composition_vector["CW"] = -1  # type: ignore[index]

    # requirement_payload must also reject mutation (recursively frozen)
    with pytest.raises((TypeError, AttributeError, RuntimeError)):
        u.requirement_payload["nested"]["k"].append(99)  # type: ignore[index]

    # Top level assignment on frozen key also fails
    with pytest.raises((TypeError, AttributeError)):
        u.requirement_payload["new"] = 1  # type: ignore[index]


# ----------------------------------------------------------------------------
# R4 regressions: stripped-nonblank validator and boundary confirmation
# ----------------------------------------------------------------------------

def test_whitespace_only_strings_rejected_for_required_fields():
    """Whitespace-only must not satisfy required text fields.

    Applies to: scope_citation, intent_statement, alternative_control,
    EvidenceEntry.doc_id/revision/locator, and (via Acceptance) customer_authority/approval_artifact.
    """
    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # scope_citation (NA)
    with pytest.raises(ValidationError):
        DispositionUnit(
            **_base_unit(code="NA", scope_citation="   ", unit_boundary_confirmed_by="b1")
        )

    # intent_statement (MI)
    with pytest.raises(ValidationError):
        DispositionUnit(
            **_base_unit(
                code="MI",
                intent_statement="   ",
                alternative_control="alt",
                control_class="integral",
                unit_boundary_confirmed_by="b1",
            )
        )

    # alternative_control
    with pytest.raises(ValidationError):
        DispositionUnit(
            **_base_unit(
                code="MI",
                intent_statement="intent",
                alternative_control="   ",
                control_class="integral",
                unit_boundary_confirmed_by="b1",
            )
        )

    # EvidenceEntry fields
    with pytest.raises(ValidationError):
        EvidenceEntry(
            doc_id="   ",
            revision="R1",
            locator="s:1",
            link_confidence=0.9,
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )
    with pytest.raises(ValidationError):
        EvidenceEntry(
            doc_id="D1",
            revision="   ",
            locator="s:1",
            link_confidence=0.9,
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )
    with pytest.raises(ValidationError):
        EvidenceEntry(
            doc_id="D1",
            revision="R1",
            locator="   ",
            link_confidence=0.9,
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )

    # Acceptance authority/artifact (via model construction)
    bad_acc = {
        "id": "ACC-BAD1",
        "status": "accepted",
        "customer_authority": "   ",
        "approval_artifact": "ART-1",
        "approved_scope": ApprovedScope(
            configurations=("c",),
            part_classes=("p",),
            valid_from="2026-01-01",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        ),
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
    }
    with pytest.raises(ValidationError):
        AcceptanceRecord(**bad_acc)

    bad_acc2 = {
        "id": "ACC-BAD2",
        "status": "accepted",
        "customer_authority": "QA",
        "approval_artifact": "\t\n",
        "approved_scope": ApprovedScope(
            configurations=("c",),
            part_classes=("p",),
            valid_from="2026-01-01",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        ),
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
    }
    with pytest.raises(ValidationError):
        AcceptanceRecord(**bad_acc2)


def test_unit_boundary_confirmed_by_enforced_for_non_rollup():
    """§7.3: non-rollup unit carrying a code must have stripped-nonblank confirmer."""
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # Missing
    with pytest.raises(ValidationError, match="unit_boundary_confirmed_by"):
        DispositionUnit(
            unit_id="AMR-NO-B",
            requirement_text="shall",
            locator=loc,
            code=DispositionCode.CW,
            proposer="p",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )

    # Whitespace only
    with pytest.raises(ValidationError, match="unit_boundary_confirmed_by"):
        DispositionUnit(
            unit_id="AMR-WS-B",
            requirement_text="shall",
            locator=loc,
            code=DispositionCode.CW,
            proposer="p",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
            unit_boundary_confirmed_by="   ",
        )

    # Valid non-blank allows construction
    u = DispositionUnit(
        unit_id="AMR-OK-B",
        requirement_text="shall",
        locator=loc,
        code=DispositionCode.CW,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="extractor-7",
    )
    assert u.unit_boundary_confirmed_by == "extractor-7"


def test_split_validators_return_self_paths_low5():
    """Low #5: the split focused validators must return self for valid inputs.

    This exercises the early-return paths in _enforce_rollup_invariants,
    _enforce_boundary_confirmation, and _enforce_code_specific_requirements.
    """
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # Roll-up path (returns early in rollup validator)
    u_roll = DispositionUnit(
        unit_id="AMR-ROLL-V",
        is_rollup=True,
        code=None,
        composition_vector={"CW": 2},
        requirement_text="r",
        locator=loc,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    assert u_roll.is_rollup is True

    # Boundary + code path for a normal CW
    u_cw = DispositionUnit(
        unit_id="AMR-CW-V",
        requirement_text="shall",
        locator=loc,
        code=DispositionCode.CW,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )
    assert u_cw.code == DispositionCode.CW

    # OPEN path exercises the code-specific validator
    u_open = DispositionUnit(
        unit_id="AMR-OP-V",
        requirement_text="shall",
        locator=loc,
        code=DispositionCode.OPEN,
        open_sub_reason="evidence_absent",
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )
    assert u_open.code == DispositionCode.OPEN


# ----------------------------------------------------------------------------
# High #1 (Atlas): public construction must reject non-proposed states
# ----------------------------------------------------------------------------

def test_public_construction_rejects_non_proposed_states_high1():
    """High #1: DispositionUnit(..., workflow_state=...) accepts ONLY 'proposed'.

    Non-proposed states are produced exclusively via transition_unit.
    """
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # Direct construction of non-proposed must fail. release_approved is
    # rejected by the S1 scope-boundary guard, which fires first and carries a
    # more specific message; the other two hit the proposed-only guard.
    for bad_state in ("human_confirmed", "release_approved", "rejected"):
        expected = (
            "cannot be constructed in slice S1"
            if bad_state == "release_approved"
            else "accepts only workflow_state='proposed'"
        )
        with pytest.raises(ValidationError, match=expected):
            DispositionUnit(
                unit_id="AMR-H1",
                requirement_text="shall X",
                locator=loc,
                code=DispositionCode.CW,
                proposer="p",
                schema_version=SCHEMA_VERSION,
                rule_version=RULE_VERSION,
                unit_boundary_confirmed_by="b1",
                workflow_state=bad_state,  # type: ignore[arg-type]
            )

    # proposed succeeds
    u = DispositionUnit(
        unit_id="AMR-H1-OK",
        requirement_text="shall X",
        locator=loc,
        code=DispositionCode.CW,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
        workflow_state="proposed",
    )
    assert u.workflow_state == "proposed"


def test_rollup_must_remain_proposed_high1():
    """High #1 + §1.1: roll-up parents must remain in 'proposed' and are never targets."""
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # Attempting to construct a roll-up in a non-proposed state must fail
    with pytest.raises(ValidationError, match="proposed"):
        DispositionUnit(
            unit_id="AMR-ROLL-H1",
            is_rollup=True,
            code=None,
            composition_vector={"CW": 1},
            requirement_text="rollup",
            locator=loc,
            proposer="p",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
            workflow_state="human_confirmed",  # type: ignore[arg-type]
        )


def test_composition_vector_rejects_bool_medium3():
    """Medium #3: bool (True/False) must not be accepted as child counts.

    Python bool is subclass of int; we must reject it explicitly.
    """
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # bool True in vector at construction
    with pytest.raises(ValidationError, match="non-negative int|composition_vector"):
        DispositionUnit(
            unit_id="AMR-BOOL",
            is_rollup=True,
            code=None,
            composition_vector={"CW": True},  # type: ignore[dict-item]
            requirement_text="r",
            locator=loc,
            proposer="p",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )

    # bool False in vector
    with pytest.raises(ValidationError, match="non-negative int|composition_vector"):
        DispositionUnit(
            unit_id="AMR-BOOL2",
            is_rollup=True,
            code=None,
            composition_vector={"CW": False},  # type: ignore[dict-item]
            requirement_text="r",
            locator=loc,
            proposer="p",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )


def test_rollup_badge_rejects_bool_medium3():
    """Medium #3: rollup_badge must reject bool counts (defense at the rollup layer too)."""
    with pytest.raises(ValueError, match="non-negative int|rollup_badge"):
        rollup_badge({"CW": True})  # type: ignore[dict-item]

    with pytest.raises(ValueError, match="non-negative int|rollup_badge"):
        rollup_badge({"NA": False})  # type: ignore[dict-item]


# ----------------------------------------------------------------------------
# Medium #4: additional whitespace-only rejections on core identity fields
# ----------------------------------------------------------------------------

def test_core_identity_fields_reject_whitespace_medium4():
    """Medium #4: unit_id, requirement_text, proposer, Locator fields reject whitespace-only."""
    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # unit_id whitespace
    with pytest.raises(ValidationError):
        DispositionUnit(
            unit_id="   ",
            requirement_text="shall",
            locator=loc,
            code=DispositionCode.CW,
            proposer="p",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
            unit_boundary_confirmed_by="b1",
        )

    # requirement_text whitespace
    with pytest.raises(ValidationError):
        DispositionUnit(
            unit_id="AMR-WS-R",
            requirement_text="   \t",
            locator=loc,
            code=DispositionCode.CW,
            proposer="p",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
            unit_boundary_confirmed_by="b1",
        )

    # proposer whitespace
    with pytest.raises(ValidationError):
        DispositionUnit(
            unit_id="AMR-WS-P",
            requirement_text="shall",
            locator=loc,
            code=DispositionCode.CW,
            proposer="   ",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
            unit_boundary_confirmed_by="b1",
        )

    # Locator fields whitespace
    with pytest.raises(ValidationError):
        Locator(
            standard="   ",
            revision="R1",
            section="s",
            page=1,
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )
    with pytest.raises(ValidationError):
        Locator(
            standard="S",
            revision="   ",
            section="s",
            page=1,
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )
    with pytest.raises(ValidationError):
        Locator(
            standard="S",
            revision="R",
            section="   ",
            page=1,
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )


def test_levy_manifest_entry_and_manifest_reject_whitespace_medium4():
    """Medium #4: LevyManifestEntry and LevyManifest required strings reject whitespace-only."""
    with pytest.raises(ValidationError):
        LevyManifestEntry(
            doc_id="   ",
            revision="R1",
            effective_date="2026-01-01",
            source="levy",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )
    with pytest.raises(ValidationError):
        LevyManifest(
            run_id="   ",
            levied_at="2026-01-01T00:00:00Z",
            documents=(
                LevyManifestEntry(
                    doc_id="D1",
                    revision="R1",
                    effective_date="2026-01-01",
                    source="levy",
                    schema_version=SCHEMA_VERSION,
                    rule_version=RULE_VERSION,
                ),
            ),
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )


def test_high3_actor_name_recorded_into_confirmed_by():
    """High #3: human transitions populate confirmed_by with the actor name."""
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    human = Actor(name="j.wilde@boundstate.ai")

    u = DispositionUnit(
        unit_id="AMR-H3",
        requirement_text="shall",
        locator=loc,
        code=DispositionCode.CW,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )
    assert u.confirmed_by is None

    u2 = transition_unit(u, "human_confirmed", human)
    assert u2.workflow_state == "human_confirmed"
    assert u2.confirmed_by == "j.wilde@boundstate.ai"

    # S1 scope boundary: release_approved is refused outright, so there is no
    # release path on which to record an approver. Asserted by
    # test_release_approved_is_refused_in_s1 below.

    # rejected path also records the human who rejected
    u_r = DispositionUnit(
        unit_id="AMR-H3R",
        requirement_text="shall",
        locator=loc,
        code=DispositionCode.CW,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )
    u_r2 = transition_unit(u_r, "rejected", human)
    assert u_r2.workflow_state == "rejected"
    assert u_r2.confirmed_by == "j.wilde@boundstate.ai"

    # Machine actor must NOT populate confirmed_by
    from oracle.disposition.codes import DispositionCode as _DC
    machine = Actor(name="bot-01", is_machine=True)
    u_m = DispositionUnit(
        unit_id="AMR-H3M",
        requirement_text="shall",
        locator=loc,
        code=_DC.CW,
        proposer="bot-01",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )
    u_m2 = transition_unit(u_m, "proposed", machine)  # machine may only target proposed
    assert u_m2.workflow_state == "proposed"
    assert u_m2.confirmed_by is None


# ----------------------------------------------------------------------------
# High #4 (Atlas R2): model_copy and model_construct bypasses are closed for domain records
# ----------------------------------------------------------------------------

def test_high4_model_copy_and_model_construct_bypasses_closed():
    """High #4: model_copy is rejected; public model_construct of non-proposed is blocked.

    Internal transition_unit path using the authorization token is the only
    way to obtain a non-proposed successor.
    """
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    u = DispositionUnit(
        unit_id="AMR-H4",
        requirement_text="shall",
        locator=loc,
        code=DispositionCode.CW,
        proposer="p",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="b1",
    )

    # model_copy is disallowed on VersionedModel / DispositionUnit
    with pytest.raises(TypeError, match="model_copy is disallowed"):
        u.model_copy(update={"workflow_state": "human_confirmed"})  # type: ignore[attr-defined]

    # Direct model_construct is disallowed entirely (High #4); it bypasses all validators.
    with pytest.raises(TypeError, match="model_construct is disallowed"):
        DispositionUnit.model_construct(unit_id="x", requirement_text="t", locator=loc, code="CW", proposer="p", schema_version=SCHEMA_VERSION, rule_version=RULE_VERSION, unit_boundary_confirmed_by="b1", workflow_state="human_confirmed")  # type: ignore[arg-type]

    # The legitimate path (transition_unit) succeeds
    human = Actor(name="rev")
    succ = transition_unit(u, "human_confirmed", human)
    assert succ.workflow_state == "human_confirmed"


# ----------------------------------------------------------------------------
# Medium #5 (Atlas R2): AcceptanceRecord id + supersedes chaining via factory
# ----------------------------------------------------------------------------

def test_medium5_acceptance_id_and_supersedes_chaining():
    """Medium #5: AcceptanceRecord requires id; supersedes must be set via create_successor;
    self-supersedes is rejected.
    """
    scope = ApprovedScope(
        configurations=("c",),
        part_classes=("p",),
        valid_from="2026-01-01",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    acc1 = AcceptanceRecord(
        id="ACC-1",
        status="accepted",
        customer_authority="A",
        approval_artifact="ART1",
        approved_scope=scope,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    assert acc1.id == "ACC-1"
    assert acc1.supersedes is None

    # Self-supersedes is rejected at construction
    with pytest.raises(ValidationError, match="cannot equal its own id"):
        AcceptanceRecord(
            id="ACC-S",
            status="accepted",
            customer_authority="A",
            approval_artifact="ART",
            approved_scope=scope,
            supersedes="ACC-S",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )

    # Use the factory to produce a proper successor
    acc2 = AcceptanceRecord.create_successor(
        acc1,
        status="accepted",
        customer_authority="A",
        approval_artifact="ART2",
        approved_scope=scope,
    )
    assert acc2.supersedes == "ACC-1"
    assert acc2.id != acc1.id
    assert ":succ" in acc2.id


# ----------------------------------------------------------------------------
# Medium #6 (Atlas R2): ScopeDeclaration derived requires provenance
# ----------------------------------------------------------------------------

def test_medium6_derived_scope_requires_provenance():
    """Medium #6: type=derived without provenance is rejected; providing either
    derived_from_acceptance_artifact or derived_from_unit_id satisfies it.
    """
    # policy and physical_impossibility remain unchanged
    ScopeDeclaration(
        id="SD-P",
        declaration="policy choice",
        type="policy",
        source="intake",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # derived without provenance -> rejected
    with pytest.raises(ValidationError, match="derived scope declarations require"):
        ScopeDeclaration(
            id="SD-DER",
            declaration="derived from exception",
            type="derived",
            source="propagation",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
        )

    # With acceptance artifact provenance -> ok
    sd1 = ScopeDeclaration(
        id="SD-DER1",
        declaration="derived from exception",
        type="derived",
        source="propagation",
        derived_from_acceptance_artifact="ART-EX-7",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    assert sd1.type == "derived"

    # With unit id provenance -> ok
    sd2 = ScopeDeclaration(
        id="SD-DER2",
        declaration="derived from exception",
        type="derived",
        source="propagation",
        derived_from_unit_id="AMR-EX-7(a)",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    assert sd2.derived_from_unit_id == "AMR-EX-7(a)"


# ---------------------------------------------------------------------------
# S1 scope boundary: release_approved is unreachable in this slice.
#
# Release eligibility under §7.1 depends on package-level context S1 does not
# model (run date vs acceptance validity window, approved-scope coverage,
# supersession chain, evidence link-confidence). A unit-local approximation
# returns "release approved" on inputs §7.1 forbids, so S1 refuses the
# transition outright rather than half-implementing the gate. state.py still
# models the edge; what is deferred is any API that PRODUCES a released unit.
# ---------------------------------------------------------------------------

def _releasable_shaped_unit() -> DispositionUnit:
    """A unit that would satisfy every unit-local release precondition.

    Deliberately well-formed: CW with evidence and a confirmed boundary. If a
    partial gate existed, this is exactly the input it would wave through.
    """
    loc = Locator(
        standard="NASA-STD-6030", revision="Baseline", section="4.2", page=17,
        schema_version=SCHEMA_VERSION, rule_version=RULE_VERSION,
    )
    ev = EvidenceEntry(
        doc_id="D1", revision="R1", locator="s:1", link_confidence=0.99,
        schema_version=SCHEMA_VERSION, rule_version=RULE_VERSION,
    )
    return DispositionUnit(
        unit_id="AMR-REL", requirement_text="shall", locator=loc,
        code=DispositionCode.CW, proposer="p", evidence=(ev,),
        unit_boundary_confirmed_by="b1",
        schema_version=SCHEMA_VERSION, rule_version=RULE_VERSION,
    )


def test_release_approved_is_refused_by_transition_unit_in_s1():
    """transition_unit refuses release_approved regardless of unit quality."""
    human = Actor(name="j.wilde@boundstate.ai", is_machine=False)
    u = _releasable_shaped_unit()
    confirmed = transition_unit(u, "human_confirmed", human)
    assert confirmed.workflow_state == "human_confirmed"

    with pytest.raises(NotImplementedError, match="not available from transition_unit"):
        transition_unit(confirmed, "release_approved", human)


def test_release_approved_cannot_be_constructed_by_any_path_in_s1():
    """The refusal is an invariant, not a convention.

    Construction is rejected even though transition_unit is the only caller
    that could hold the internal authorization token — so no code path in this
    slice can yield a release_approved unit.
    """
    loc = Locator(
        standard="NASA-STD-6030", revision="Baseline", section="4.2", page=17,
        schema_version=SCHEMA_VERSION, rule_version=RULE_VERSION,
    )
    with pytest.raises(ValidationError, match="cannot be constructed in slice S1"):
        DispositionUnit(
            unit_id="AMR-REL2", requirement_text="shall", locator=loc,
            code=DispositionCode.CW, proposer="p",
            workflow_state="release_approved",
            unit_boundary_confirmed_by="b1",
            schema_version=SCHEMA_VERSION, rule_version=RULE_VERSION,
        )


def test_state_machine_still_models_the_release_edge():
    """The deferral is at the unit API, not in the §7.1 machine (spec deliverable)."""
    from oracle.disposition.state import apply_transition
    human = Actor(name="j.wilde@boundstate.ai", is_machine=False)
    assert apply_transition("human_confirmed", "release_approved", human) == "release_approved"
