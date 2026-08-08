"""Atlas review of fix round 3 — regressions for findings AR1-AR13.

Each test pins the behavior Atlas's probe showed broken. Keyless-deterministic:
live advisor exercised only through a canned subclass; no network, no keys.

BoundState AI 2026
"""

from __future__ import annotations

import csv as _csv
import io as _io
import json
import zipfile

import pytest

from oracle.disposition.advisor import (
    AdvisorError,
    DeterministicAdvisor,
    LiveAdvisor,
    build_context,
    derive_label_from_axes,
    output_hash,
    verify_proposal_label,
)
from oracle.disposition.corpus import CorpusError, load_corpus
from oracle.disposition.decision import evaluate_unit
from oracle.disposition.export import (
    _write_xlsx_book,
    export_appendix_a,
    export_appendix_a_xlsx,
    export_implementation_guide,
)
from oracle.disposition.library import LibraryError, export_library, import_library
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.rulepack import PackPinError
from oracle.disposition.session import (
    DispositionSession,
    EvidenceRef,
    SessionError,
    UnitAxesState,
)
from oracle.disposition.walk import IOBundle, run_walk


def _records():
    recs, _ = load_rdw_default_packs(repin=True)
    return {r.requirement_id: r for r in recs}


def _walk(tmp_path, answers, units, max_units=1, advisor=False):
    bundle = IOBundle(
        stdin=_io.StringIO("\n".join(answers) + "\n"),
        stdout=_io.StringIO(),
        require_tty=False,
    )
    run_walk(
        session_dir=tmp_path / "s",
        actor_name="op",
        unit_filter=units,
        io=bundle,
        max_units=max_units,
        advisor=advisor,
    )
    s = DispositionSession(tmp_path / "s")
    return s.resume(actor_name="op"), bundle.stdout.getvalue(), s


class _CannedLive(LiveAdvisor):
    """Keyless live advisor: canned completions, no network."""

    def __init__(self, canned: str):
        super().__init__(model_id="canned-live-model")
        self._canned = canned

    def _complete(self, system: str, user: str) -> str:  # noqa: D401
        return self._canned


def _hash_ok(res) -> bool:
    return res.output_hash == output_hash(res.model_copy(update={"output_hash": ""}))


# ------------------------------------------------------------------- AR1


def test_ar1_live_label_axes_divergence_falls_back(tmp_path):
    """Atlas critical 1: shown label must be what the axes elect."""
    s = DispositionSession(tmp_path / "a1")
    s.open(actor_name="op")
    recs = _records()
    ctx = build_context(s.state.units["AMR-14"], recs["AMR-14"], s.state.facts)
    canned = json.dumps(
        {
            "band": "HIGH",
            "basis": "divergent",
            "proposed_axes": {
                "applicability": "yes",
                "obligated_actor": "producer",
                "organization_responsibility": "owner",
                "implementation_state": "not_met",
                "approval_state": "not_required",
            },
            # axes derive Open/Not Met; MI is NOT in blocked_labels here, so
            # only the AR1 verification can catch the divergence
            "proposed_label": "Meets Intent",
            "questions": [],
        }
    )
    res = _CannedLive(canned).propose(ctx)
    # Divergent proposal must never surface — deterministic fallback instead.
    assert "live-fallback" in res.basis
    assert res.proposed_label != "Meets Intent"
    assert _hash_ok(res)


def test_ar1_verify_helper_contract():
    axes = {
        "applicability": "yes",
        "obligated_actor": "producer",
        "organization_responsibility": "owner",
        "implementation_state": "not_met",
        "approval_state": "not_required",
    }
    assert derive_label_from_axes(axes) == "Open/Not Met"
    verify_proposal_label(axes, "Open/Not Met")  # agreeing pair passes
    with pytest.raises(AdvisorError, match="does not match"):
        verify_proposal_label(axes, "Meet")
    with pytest.raises(AdvisorError, match="together"):
        verify_proposal_label(axes, None)


# ------------------------------------------------------------------- AR2


def test_ar2_nyd_cleared_when_implementation_becomes_concrete(tmp_path):
    """Atlas critical 2: sticky not_yet_due must not survive a later Meet."""
    s = DispositionSession(tmp_path / "a2")
    s.open(actor_name="op")
    s.register_evidence(doc_id="QMS-1", revision="A",
                        unit_ids=("AMR-50",), effective_date="2026-01-01")
    s.set_axes(
        "AMR-50",
        actor_name="op",
        implementation_state="tbd",
        not_yet_due=True,
        not_yet_due_justification="levied at flight production",
        election=False,
    )
    assert s.state.units["AMR-50"].not_yet_due
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="QMS-1", revision="A"), "op")
    u = s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    assert u.not_yet_due is False
    assert u.export_label().value == "Meet"


def test_ar2_explicit_nyd_with_concrete_impl_refused(tmp_path):
    s = DispositionSession(tmp_path / "a2b")
    s.open(actor_name="op")
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="QMS-1", revision="A"), "op")
    with pytest.raises(SessionError, match="not_yet_due requires"):
        s.set_axes(
            "AMR-50",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="meets_as_written",
            approval_state="not_required",
            not_yet_due=True,
        )


# ------------------------------------------------------------------- AR3


def test_ar3_eof_at_evidence_prompt_is_cancel_not_docid(tmp_path):
    """Atlas high 3: EOF became the literal doc id 'quit' before."""
    st, out, s = _walk(
        tmp_path,
        # stream ends right where the evidence doc id is asked (the
        # 'evidenced' claim cites its evidence immediately — model split)
        ["y", "unknown", "yes", "producer", "owner", "as_written", "evidenced"],
        ["AMR-50"],
    )
    u = st.units["AMR-50"]
    assert not any(r.doc_id == "quit" for r in u.evidence_refs)
    assert not u.evidence_refs
    # cancelled citation downgrades the claim to an uncited 'implemented'
    assert u.execution_state == "implemented"
    # the sub-prompt answer itself is raw-logged (Stage A discipline)
    assert any(
        a["question_key"] == "evidence.doc_id" and a["raw"] == "quit"
        for a in st.raw_answers
    )


def test_ar3_eof_at_na_citation_prompt_is_cancel(tmp_path):
    st, _, _ = _walk(tmp_path, ["y", "unknown", "no"], ["AMR-50"])
    u = st.units["AMR-50"]
    assert u.applicability == "tbd"
    assert not (u.scope_citation or "").strip()
    assert any(a["question_key"].endswith(".citation") for a in st.raw_answers)


def test_ar3_intake_eof_never_becomes_ceo_name(tmp_path):
    # "n" to assumed-CEO, then EOF at the who-is-CEO prompt
    bundle = IOBundle(
        stdin=_io.StringIO("n\n"), stdout=_io.StringIO(), require_tty=False
    )
    run_walk(
        session_dir=tmp_path / "s2",
        actor_name="op",
        unit_filter=["AMR-1"],
        io=bundle,
        max_units=0,
    )
    s = DispositionSession(tmp_path / "s2")
    st = s.resume(actor_name="op")
    fact = st.facts["ceo.identity"]
    assert "quit" not in fact.statement
    assert fact.assumed and not fact.confirmed


# ------------------------------------------------------------------- AR4


def test_ar4_single_pack_default_fails_closed(tmp_path):
    """Atlas high 4: open(multi_pack=False) loaded the corrupt builtin."""
    s = DispositionSession(tmp_path / "a4")
    with pytest.raises(PackPinError, match="builtin"):
        s.open(actor_name="op", multi_pack=False)
    s2 = DispositionSession(tmp_path / "a4b")
    st = s2.open(actor_name="op", multi_pack=False, allow_builtin=True)
    assert st.units  # explicit escape still works


# ------------------------------------------------------------------- AR5


def test_ar5_paired_no_without_citation_is_tbd(tmp_path):
    """Atlas high 5: the synthesized paired citation was laundering."""
    s = DispositionSession(tmp_path / "a5")
    s.open(actor_name="op")
    s.apply_paired_answer("scope.joining_in_crediting", "no", "op")
    for uid in ("AMR-21", "AMR-82"):
        u = s.state.units[uid]
        assert u.applicability == "tbd"
        assert not (u.scope_citation or "").strip()
    assert s.state.paired_answers["scope.joining_in_crediting"] == "no"


def test_ar5_paired_no_with_real_citation_elects_na(tmp_path):
    s = DispositionSession(tmp_path / "a5b")
    s.open(actor_name="op")
    cite = "6030 §1.2: joining processes excluded from crediting scope"
    s.apply_paired_answer(
        "scope.joining_in_crediting", "no", "op", scope_citation=cite
    )
    for uid in ("AMR-21", "AMR-82"):
        u = s.state.units[uid]
        assert u.applicability == "no"
        assert u.scope_citation == cite


def test_ar5_walk_prompts_for_paired_citation(tmp_path):
    cite = "6030 §1.2: joining excluded"
    st, out, _ = _walk(
        tmp_path, ["y", "unknown", "no", cite, "y", "quit"], ["AMR-21"]
    )
    assert st.units["AMR-21"].scope_citation == cite
    assert st.units["AMR-82"].scope_citation == cite
    assert any(a["question_key"].endswith(".citation") for a in st.raw_answers)


# ------------------------------------------------------------------- AR10


def test_ar10_paired_answer_recorded_after_elections(tmp_path):
    """Atlas medium 10: record-first left a suppressed question on crash."""
    s = DispositionSession(tmp_path / "a10")
    s.open(actor_name="op")
    s.apply_paired_answer(
        "scope.joining_in_crediting", "no", "op",
        scope_citation="6030 §1.2: excluded",
    )
    lines = (
        (tmp_path / "a10" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    )
    types = [json.loads(ln).get("payload", {}).get("event_type") for ln in lines]
    paired_idx = types.index("paired_answer")
    election_idxs = [i for i, t in enumerate(types) if t in ("election", "axis_set")]
    assert election_idxs and max(election_idxs) < paired_idx


# ------------------------------------------------------------------- AR6


def test_ar6_blocklist_covers_action_free_text(tmp_path):
    """Atlas high 6: due_or_trigger/work_package escaped the D-3 scan."""
    s = DispositionSession(tmp_path / "a6")
    s.open(actor_name="op")
    from oracle.disposition.actions import ActionRecord

    s.record_action(
        ActionRecord(
            action_id="GAP-1",
            title="Close gap",
            owner="op",
            deliverable="report",
            exit_criteria="done",
            due_or_trigger="per contract no. NNX99AB12C milestone 3",
            affected_unit_ids=("AMR-50",),
        ),
        actor_name="op",
    )
    with pytest.raises(LibraryError, match="due_or_trigger"):
        export_library(s, tmp_path / "lib.json")


# ------------------------------------------------------------------- AR7


def _accepted_meet_session(tmp_path, name):
    s = DispositionSession(tmp_path / name)
    s.open(actor_name="op")
    s.register_evidence(doc_id="QMS", revision="A",
                        unit_ids=("AMR-1",), effective_date="2026-01-01")
    s.attach_evidence("AMR-1", EvidenceRef(doc_id="QMS", revision="A"), "op")
    s.set_axes(
        "AMR-1",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    s.attest_unit(
        "AMR-1", actor_name="op", role="disposition_author", decision="accepted"
    )
    return s


def test_ar7_export_carries_obligated_actor(tmp_path):
    s = _accepted_meet_session(tmp_path, "a7")
    out = export_library(s, tmp_path / "lib.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    axes = data["dispositions"][0]["axes"]
    assert axes["obligated_actor"] == "producer"


def test_ar7_walk_consumes_library_action_pattern(tmp_path):
    d = DispositionSession(tmp_path / "s")
    d.open(actor_name="op")
    d.record_library_import(
        source_session_id="src-1",
        dispositions=[],
        action_patterns=[
            {
                "action_id": "PLAN-X",
                "title": "Stand up EFCP",
                "owner": "op",
                "deliverable": "EFCP doc",
                "exit_criteria": "EFCP approved",
                "priority": "high",
                "due_or_trigger": "",
                "work_package": "wp-1",
                "affected_unit_ids": ["AMR-50"],
                "status": "open",
                "note": "",
            }
        ],
        actor_name="op",
    )
    bundle = IOBundle(
        stdin=_io.StringIO(
            "\n".join(
                [
                    "y", "unknown",  # intake (resumed session still runs it)
                    "yes", "producer", "owner", "open",
                    "not_started", "not_required",
                    "y",  # apply the library plan pattern
                    "y",  # accept comment
                    "quit",
                ]
            )
            + "\n"
        ),
        stdout=_io.StringIO(),
        require_tty=False,
    )
    run_walk(
        session_dir=tmp_path / "s",
        actor_name="op",
        unit_filter=["AMR-50"],
        io=bundle,
        max_units=1,
    )
    s2 = DispositionSession(tmp_path / "s")
    s2.resume(actor_name="op")
    acts = s2.actions_for_unit("AMR-50")
    assert any(a.action_id == "PLAN-X" and a.is_plan_quality() for a in acts)
    assert "Library plan pattern" in bundle.stdout.getvalue()


# ------------------------------------------------------------------- AR8


def test_ar8_cited_na_not_blocked_by_unresolved_fact():
    """Atlas medium 8: ceo.identity edges blocked N/A even with a citation."""
    unit = UnitAxesState(
        unit_id="AMR-2",
        applicability="no",
        organization_responsibility="external",
        implementation_state="not_reached",
        approval_state="not_required",
        scope_citation="6030 §1.2: not flight hardware",
    )
    res = evaluate_unit(unit, facts={})  # ceo.identity entirely unresolved
    assert "N/A" not in res.blocked
    # claim-scoped (corpus-replay slice): the Meet BLOCK applies to rows
    # claiming execution — an evidenced AMR-2 claim stays blocked
    claim = UnitAxesState(
        unit_id="AMR-2",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="as_written",
        execution_state="evidenced",
        approval_state="not_required",
    )
    res2 = evaluate_unit(claim, facts={})
    assert "Meet" in res2.blocked


def test_ar8_uncited_na_still_blocked():
    unit = UnitAxesState(
        unit_id="AMR-2",
        applicability="no",
        organization_responsibility="external",
        implementation_state="not_reached",
        approval_state="not_required",
    )
    res = evaluate_unit(unit, facts={})
    assert "N/A" in res.blocked


# ------------------------------------------------------------------- AR9


def test_ar9_invalid_mi_class_reprompts(tmp_path):
    """Atlas medium 9: 'bogus' silently became integral before."""
    st, out, _ = _walk(
        tmp_path,
        [
            "y", "unknown", "yes", "producer", "owner", "alternative",
            "intent: control the process", "alt: vendor QMS control",
            "bogus", "disclosed",  # invalid then corrected
            "partial", "required",
            "n",  # plan offer (MI with execution partial)
            "y", "quit",
        ],
        ["AMR-50"],
    )
    assert "Invalid control class" in out
    assert st.units["AMR-50"].control_class == "disclosed"


# ------------------------------------------------------------------- AR11


_CORPUS_HEADER = (
    "requirement_id,contract_label,readiness_label,applicability,"
    "organization_responsibility,implementation_state,approval_state,"
    "comment,work_package,action_ids,raw_answers,evidence_refs"
)


def test_ar11_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(
        _CORPUS_HEADER + "\nAMR-1,CW,Met,,,,,,,,,\nAMR-1,CW,Met,,,,,,,,,\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusError, match="duplicate requirement_id"):
        load_corpus(p)


def test_ar11_unknown_labels_rejected(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(_CORPUS_HEADER + "\nAMR-1,BOGUS,Met,,,,,,,,,\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="unknown contract_label"):
        load_corpus(p)
    p.write_text(_CORPUS_HEADER + "\nAMR-1,CW,Someday,,,,,,,,,\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="unknown readiness_label"):
        load_corpus(p)
    p.write_text(_CORPUS_HEADER + "\nAMR-1,CW,Met,maybe,,,,,,,,\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="applicability"):
        load_corpus(p)


def test_ar11_xlsx_corpus_loads_and_normalizes(tmp_path):
    headers = _CORPUS_HEADER.split(",")
    rows = [
        ["AMR-1", "Comply as Written", "Met", "yes", "owner",
         "meets_as_written", "not_required", "ok", "wp-1", "", "", ""],
        ["AMR-2", "EX", "Not Met with Plan", "yes", "owner",
         "not_met", "required", "", "wp-2", "A-1;A-2", "", ""],
    ]
    p = _write_xlsx_book(tmp_path / "c.xlsx", [("Corpus", headers, rows)])
    loaded = load_corpus(p)
    assert [r.requirement_id for r in loaded] == ["AMR-1", "AMR-2"]
    assert loaded[0].contract_label == "CW"  # full form normalized
    assert loaded[1].action_ids == ("A-1", "A-2")


# ------------------------------------------------------------------- AR12


def test_ar12_appendix_a_is_amr_only(tmp_path):
    """Atlas medium 12: 8 EFCR rows leaked into the Appendix A deliverable."""
    s = DispositionSession(tmp_path / "a12")
    s.open(actor_name="op")
    recs = _records()
    assert any(uid.startswith("EFCR-") for uid in s.state.units)  # precondition
    csv_path = export_appendix_a(
        s, recs, tmp_path / "out" / "appendix.csv", enforce_decision=False,
        include_draft=True,
    )
    body = [
        row for row in _csv.reader(
            ln for ln in csv_path.read_text(encoding="utf-8").splitlines()
            if not ln.startswith("#")
        )
    ]
    ids = [r[2] for r in body[1:] if len(r) > 2]
    assert ids and all(u.startswith("AMR-") for u in ids)
    xlsx_path = export_appendix_a_xlsx(
        s, recs, tmp_path / "out" / "appendix.xlsx", enforce_decision=False,
        include_draft=True,
    )
    with zipfile.ZipFile(xlsx_path) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "EFCR-" not in sheet


# ------------------------------------------------------------------- AR13


def test_ar13_guide_objective_evidence_requires_registry(tmp_path):
    """Atlas medium 13: unregistered refs were labeled objective evidence."""
    s = DispositionSession(tmp_path / "a13")
    s.open(actor_name="op")
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="UNREG", revision="9"), "op")
    recs = _records()
    guide = export_implementation_guide(
        s, recs, tmp_path / "guide.md"
    ).read_text(encoding="utf-8")
    sect = guide.split("## AMR-50")[1].split("## ")[0]
    assert "UNREG@9" in sect  # still listed as a cited (unverified) ref
    assert "no evidence registry" in sect  # but never as objective evidence


def test_ar13_guide_registered_refs_only_and_no_comment_masquerade(tmp_path):
    from oracle.disposition.evidence import EvidenceStore

    root = tmp_path / "a13b"
    s = DispositionSession(root)
    s.open(actor_name="op")
    store = EvidenceStore(root / "evidence")
    store.register(
        evidence_id="EV-1", doc_id="REG", revision="A", unit_ids=("AMR-50",),
        effective_date="2026-01-01", approval_date="2026-01-01",
    )
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="REG", revision="A"), "op")
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="UNREG", revision="9"), "op")
    s.set_axes(
        "AMR-50", actor_name="op", comment="Documented in the QMS manual.",
        comment_status="accepted", election=False,
    )
    recs = _records()
    guide = export_implementation_guide(
        s, recs, tmp_path / "guide2.md"
    ).read_text(encoding="utf-8")
    sect = guide.split("## AMR-50")[1].split("## ")[0]
    obj_line = next(
        ln for ln in sect.splitlines() if "Objective evidence" in ln
    )
    assert "REG@A" in obj_line and "UNREG@9" not in obj_line
    interp_line = next(
        ln for ln in sect.splitlines() if "Process interpretation" in ln
    )
    # comment must not masquerade as interpretation (it has its own line)
    assert "QMS manual" not in interp_line
