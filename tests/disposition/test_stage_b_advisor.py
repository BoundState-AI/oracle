"""Stage B — DeterministicAdvisor (keyless). BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.advisor import (
    AdvisorError,
    DeterministicAdvisor,
    AdvisorContext,
    build_context,
    grade_claims_vs_facts,
    scrub_advisor_text,
)
from oracle.disposition.codes import ProposalBand
from oracle.disposition.session import DispositionSession, UnitAxesState


def test_low_band_proposes_nothing(tmp_path):
    s = DispositionSession(tmp_path / "b")
    s.open(actor_name="op")
    s.assert_fact(
        key="classification.primary",
        statement="Classification not provided",
        author="op",
        assumed=True,
        owner="op",
    )
    unit = s.state.units["AMR-17"]
    from oracle.disposition.packs import load_rdw_default_packs

    recs, _ = load_rdw_default_packs(repin=True)
    rec = next(r for r in recs if r.requirement_id == "AMR-17")
    ctx = build_context(unit, rec, s.state.facts)
    adv = DeterministicAdvisor()
    prop = adv.propose(ctx)
    assert prop.band == ProposalBand.LOW
    assert prop.proposed_axes is None
    assert prop.questions


def test_blocked_labels_never_proposed(tmp_path):
    s = DispositionSession(tmp_path / "b2")
    s.open(actor_name="op")
    unit = UnitAxesState(
        unit_id="AMR-2",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    from oracle.disposition.decision import evaluate_unit

    d = evaluate_unit(unit, facts=s.state.facts)
    assert "Meet" in d.blocked
    ctx = AdvisorContext(
        unit_id="AMR-2",
        shall_text="AMCP shall be submitted",
        blocked_labels=dict(d.blocked),
        facts={},
    )
    prop = DeterministicAdvisor().propose(ctx)
    # Must not propose Meet when blocked
    if prop.proposed_label:
        assert prop.proposed_label != "Meet"
        assert prop.proposed_label not in d.blocked


def test_grader_and_prohibited_language():
    with pytest.raises(AdvisorError, match="13.2|prohibited"):
        scrub_advisor_text("The supplier is fully compliant.", {})
    hits = grade_claims_vs_facts("requirement is met without evidence", {})
    assert hits


def test_advisor_events_carry_hashes(tmp_path):
    s = DispositionSession(tmp_path / "b3")
    s.open(actor_name="op")
    from oracle.disposition.packs import load_rdw_default_packs

    recs, _ = load_rdw_default_packs(repin=True)
    rec = next(r for r in recs if r.requirement_id == "AMR-14")
    unit = s.state.units["AMR-14"]
    ctx = build_context(unit, rec, s.state.facts)
    adv = DeterministicAdvisor()
    exp = adv.explain(ctx)
    assert exp.context_hash.startswith("sha256:")
    assert exp.output_hash.startswith("sha256:")
    assert exp.prompt_version
    s.record_advisor_output(
        "explain", exp.model_dump(mode="json"), actor_name="op", unit_id="AMR-14"
    )
    s2 = DispositionSession(tmp_path / "b3")
    s2.resume(actor_name="op", repin=False)
    assert s2.state.advisor_outputs
    assert s2.state.advisor_outputs[0].get("context_hash")


def test_suggest_closure_amr14(tmp_path):
    s = DispositionSession(tmp_path / "b4")
    s.open(actor_name="op")
    from oracle.disposition.packs import load_rdw_default_packs

    recs, _ = load_rdw_default_packs(repin=True)
    rec = next(r for r in recs if r.requirement_id == "AMR-14")
    unit = s.state.units["AMR-14"]
    ctx = build_context(unit, rec, s.state.facts)
    clos = DeterministicAdvisor().suggest_closure(ctx)
    assert clos.actions
    assert clos.actions[0].owner
    assert clos.actions[0].exit_criteria
