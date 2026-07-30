"""Tailor helper: session persistence, cursor, and the §8 LOW rule.

BoundState AI 2026
"""

from __future__ import annotations

import json

import pytest

from oracle.disposition.codes import DispositionCode, OPENSubReason, ProposalBand
from oracle.tailor.advisor import Advisor, AdvisorError, Proposal, _to_proposal
from oracle.tailor.session import SCHEMA_VERSION, TailorError, TailorSession

PACK = {
    "schema_version": "gpcm_rulepack/v1",
    "standard_id": "TEST-STD-1",
    "requirements": [
        {"id": "r-1", "source_tag": "R 1", "section": "4.1", "page": 1,
         "subject": "The supplier", "requirement": "do X", "shall_text": "The supplier shall do X."},
        {"id": "r-2", "source_tag": "R 2", "section": "4.2", "page": 2,
         "subject": "The supplier", "requirement": "do Y", "shall_text": "The supplier shall do Y."},
        {"id": "r-3", "source_tag": "R 3", "section": "4.3", "page": 3,
         "subject": "The supplier", "requirement": "do Z", "shall_text": "The supplier shall do Z."},
    ],
}


@pytest.fixture
def pack_path(tmp_path):
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(PACK), encoding="utf-8")
    return p


@pytest.fixture
def session(tmp_path, pack_path):
    return TailorSession.start(pack_path, tmp_path / "s.json", "j.wilde")


def test_start_loads_requirements_in_order(session):
    assert session.total == 3
    assert [r.tag for r in session.requirements] == ["R 1", "R 2", "R 3"]
    assert session.current().id == "r-1"


def test_empty_pack_refuses(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"standard_id": "X", "requirements": []}), encoding="utf-8")
    with pytest.raises(TailorError, match="no requirements"):
        TailorSession.start(p, tmp_path / "s.json", "op")


def test_rationale_is_mandatory(session):
    """The reasoning is the product; a bare code is what this tool prevents."""
    with pytest.raises(TailorError, match="rationale is required"):
        session.record(DispositionCode.CW, "   ")
    assert session.decided_count == 0


def test_open_requires_sub_reason(session):
    with pytest.raises(TailorError, match="sub-reason"):
        session.record(DispositionCode.OPEN, "not yet known")


def test_record_and_resume_round_trip(session, tmp_path):
    session.record(DispositionCode.CW, "Already satisfied by procedure P-1.")
    session.advance_to_next_undecided()
    session.record(
        DispositionCode.OPEN, "Depends on an undeclared scope decision.",
        open_sub_reason=OPENSubReason.SCOPE_DECISION_NOT_MADE,
    )
    session.save()

    resumed = TailorSession.resume(tmp_path / "s.json")
    assert resumed.decided_count == 2
    assert resumed.operator == "j.wilde"
    assert resumed.decisions["r-1"].code is DispositionCode.CW
    assert resumed.decisions["r-2"].open_sub_reason is OPENSubReason.SCOPE_DECISION_NOT_MADE
    assert resumed.decisions["r-1"].decided_by == "j.wilde"


def test_resume_rejects_unknown_schema_version(session, tmp_path):
    session.save()
    p = tmp_path / "s.json"
    state = json.loads(p.read_text(encoding="utf-8"))
    state["schema_version"] = "tailor/v99"
    p.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(TailorError, match="schema_version"):
        TailorSession.resume(p)


def test_save_is_atomic_and_leaves_no_temp(session, tmp_path):
    session.record(DispositionCode.NA, "Excluded by scope declaration SD-1.")
    session.save()
    assert (tmp_path / "s.json").is_file()
    assert not list(tmp_path.glob("*.tmp"))


def test_tally_is_computed_not_stored(session):
    """A stored count is a second source of truth that drifts (fixture case 22)."""
    session.record(DispositionCode.CW, "ok")
    session.save()
    state = json.loads(session.session_path.read_text(encoding="utf-8"))
    assert "tally" not in state and "counts" not in state
    assert session.tally()["CW"] == 1


def test_seek_id_matches_id_or_tag(session):
    assert session.seek_id("R 3") and session.current().id == "r-3"
    assert session.seek_id("r-1") and session.current().id == "r-1"
    assert not session.seek_id("nope")


def test_advance_skips_decided_and_runs_off_the_end(session):
    session.record(DispositionCode.CW, "a")
    session.advance_to_next_undecided()
    assert session.current().id == "r-2"
    session.record(DispositionCode.CW, "b")
    session.advance_to_next_undecided()
    assert session.current().id == "r-3"
    session.record(DispositionCode.CW, "c")
    session.advance_to_next_undecided()
    assert session.current() is None


def test_clear_removes_a_decision(session):
    session.record(DispositionCode.CW, "a")
    assert session.clear("r-1") is True
    assert session.decided_count == 0
    assert session.clear("r-1") is False


# ── advisor ─────────────────────────────────────────────────────────────────


def _raw(**over):
    base = {
        "code": "CW", "band": "HIGH", "basis": "b", "reasoning": "r",
        "draft_rationale": "d", "open_sub_reason": "", "questions": [],
        "evidence_needed": [],
    }
    base.update(over)
    return base


def test_low_band_never_carries_a_substantive_code():
    """§8: a LOW unit renders as a question, not a code with a caveat.

    Enforced here rather than trusted to the prompt — the model proposing CW at
    LOW band is exactly the failure the rule exists to stop.
    """
    p = _to_proposal(_raw(code="CW", band="LOW", questions=["Which part classes?"]))
    assert p.code is DispositionCode.OPEN
    assert p.open_sub_reason is OPENSubReason.SCOPE_DECISION_NOT_MADE
    assert p.is_question


def test_open_without_sub_reason_gets_one():
    p = _to_proposal(_raw(code="OPEN", band="MEDIUM"))
    assert p.open_sub_reason is not None


def test_high_band_proposal_passes_through():
    p = _to_proposal(_raw(code="MI", band="HIGH", draft_rationale="intent + control"))
    assert p.code is DispositionCode.MI
    assert p.band is ProposalBand.HIGH
    assert not p.is_question
    assert p.draft_rationale == "intent + control"


def test_unusable_model_output_raises():
    with pytest.raises(AdvisorError):
        _to_proposal({"code": "NOPE", "band": "HIGH"})
    with pytest.raises(AdvisorError):
        _to_proposal(_raw(band="0.73"))


def test_advisor_passes_prior_decisions_for_consistency(session):
    """Paired requirements must not be dispositioned two different ways."""
    seen = {}

    class Recorder:
        def complete(self, system, user, schema):
            seen["user"] = user
            return _raw()

    session.record(DispositionCode.EX, "Cannot meet; closure plan in annex A.")
    adv = Advisor(backend=Recorder(), standard_id="TEST-STD-1", scope_notes="Freestanding only.")
    adv.propose(session.requirements[1], (("r-1", "EX"),))

    assert "Freestanding only." in seen["user"]
    assert "r-1: EX" in seen["user"]
    assert "The supplier shall do Y." in seen["user"]


def test_advisor_without_scope_is_told_not_to_assume_one(session):
    seen = {}

    class Recorder:
        def complete(self, system, user, schema):
            seen["user"] = user
            return _raw()

    Advisor(backend=Recorder(), standard_id="X").propose(session.requirements[0])
    assert "scope_decision_not_made" in seen["user"]


def test_advisor_failure_surfaces_never_silently_empty(session):
    """An advisor failure must raise, not read as 'no opinion'."""

    class Broken:
        def complete(self, system, user, schema):
            raise AdvisorError("model call failed: boom")

    with pytest.raises(AdvisorError, match="boom"):
        Advisor(backend=Broken(), standard_id="X").propose(session.requirements[0])
