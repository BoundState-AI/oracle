"""Fix round 3 (Fran's product review): FR1-FR8. BoundState AI 2026.

Keyless-deterministic: the live advisor is exercised only through a canned
subclass; no network, no keys.
"""

from __future__ import annotations

import io as _io
import json

import pytest

from oracle.disposition.actions import ActionRecord
from oracle.disposition.advisor import (
    AdvisorError,
    DeterministicAdvisor,
    LiveAdvisor,
    build_context,
    output_hash,
)
from oracle.disposition.corpus import (
    CorpusError,
    CorpusRow,
    assert_reconciled,
    corpus_path,
    load_corpus,
)
from oracle.disposition.graph import DependencyGraph
from oracle.disposition.library import LibraryError, export_library, import_library
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.rulepack import PackPinError
from oracle.disposition.session import DispositionSession, EvidenceRef, SessionError
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


# ---------------------------------------------------------------- FR1


def test_fr1_ceo_no_asks_who_and_records_identity(tmp_path):
    st, out, _ = _walk(
        tmp_path, ["n", "Acme-Aero", "unknown", "quit"], ["AMR-1"], 0
    )
    assert "Who is the CEO" in out
    assert "ceo.identity" in st.facts
    fact = st.facts["ceo.identity"]
    assert not fact.assumed and fact.confirmed
    assert "Acme-Aero" in fact.statement
    assert any(o.role == "ceo" and o.confirmed for o in st.context.organizations)


def test_fr1_ceo_yes_records_assumption(tmp_path):
    st, _, _ = _walk(tmp_path, ["y", "unknown", "quit"], ["AMR-1"], 0)
    fact = st.facts["ceo.identity"]
    assert fact.assumed and not fact.confirmed


def test_fr1_graph_edges_present():
    g = DependencyGraph.from_seeds()
    deps = {e.dependent_id for e in g.edges if e.fact_key == "ceo.identity"}
    assert {"AMR-2", "AMR-4"} <= deps


# ---------------------------------------------------------------- FR2 (AF3)


def _seeded_session(tmp_path):
    s = DispositionSession(tmp_path / "sess")
    s.open(actor_name="op")
    s.assert_fact(
        key="classification.primary",
        statement="Classification not provided",
        author="op",
        assumed=True,
        owner="op",
    )
    return s


def test_fr2_amr14_proposal_reachable_with_seeded_assumption(tmp_path):
    s = _seeded_session(tmp_path)
    recs = _records()
    ctx = build_context(s.state.units["AMR-14"], recs["AMR-14"], s.state.facts)
    p = DeterministicAdvisor().propose(ctx)
    assert p.proposed_label == "Open/Not Met"
    assert p.proposed_axes is not None


def test_fr2_class_gated_unit_still_low(tmp_path):
    s = _seeded_session(tmp_path)
    recs = _records()
    ctx = build_context(s.state.units["AMR-17"], recs["AMR-17"], s.state.facts)
    p = DeterministicAdvisor().propose(ctx)
    assert p.band.value == "LOW" and p.proposed_axes is None


def test_fr2_unrelated_unit_not_low(tmp_path):
    s = _seeded_session(tmp_path)
    recs = _records()
    ctx = build_context(s.state.units["AMR-50"], recs["AMR-50"], s.state.facts)
    p = DeterministicAdvisor().propose(ctx)
    assert p.band.value != "LOW"


# ---------------------------------------------------------------- FR3


def test_fr3_na_completes_with_citation(tmp_path):
    st, _, _ = _walk(
        tmp_path,
        ["y", "unknown", "no", "6030 §1.2: not flight hardware", "y", "quit"],
        ["AMR-50"],
    )
    u = st.units["AMR-50"]
    assert u.applicability == "no"
    assert u.scope_citation and "1.2" in u.scope_citation
    assert u.export_label().value == "N/A"


def test_fr3_meet_completes_with_evidence(tmp_path):
    st, _, _ = _walk(
        tmp_path,
        [
            "y", "unknown", "yes", "producer", "owner", "as_written",
            "evidenced", "QMS-001", "A", "2026-01-01",
            "not_required", "y", "quit",
        ],
        ["AMR-50"],
    )
    u = st.units["AMR-50"]
    assert u.export_label().value == "Meet"
    assert u.fulfillment_path == "as_written"
    assert u.execution_state == "evidenced"
    assert any(r.doc_id == "QMS-001" for r in u.evidence_refs)


def test_fr3_meets_intent_gathers_fields(tmp_path):
    st, _, _ = _walk(
        tmp_path,
        [
            "y", "unknown", "yes", "producer", "owner", "alternative",
            "intent: control the process", "alt: vendor QMS control",
            "integral", "partial", "required",
            "n",  # plan offer (MI with execution partial)
            "y", "quit",
        ],
        ["AMR-50"],
    )
    u = st.units["AMR-50"]
    assert u.export_label().value == "Meets Intent"
    assert u.fulfillment_path == "alternative_intent"
    assert u.intent_statement and u.alternative_control
    assert u.control_class == "integral"


def test_fr3_exception_gathers_basis_and_action(tmp_path):
    st, _, _ = _walk(
        tmp_path,
        [
            "y", "unknown", "yes", "producer", "owner", "exception",
            "not_started", "required",
            "cannot meet as written for cold spray",  # basis
            "action",  # closure choice
            "", "Pursue MUA relief", "op", "MUA", "MUA granted",
            "high", "", "relief-wp",
            "y", "quit",
        ],
        ["AMR-50"],
    )
    u = st.units["AMR-50"]
    assert u.export_label().value == "Exception"
    assert u.fulfillment_path == "exception"
    assert u.exception_basis
    assert u.closure_path_action_id


def test_fr3_open_not_met_offers_plan(tmp_path):
    st, _, s = _walk(
        tmp_path,
        [
            "y", "unknown", "yes", "producer", "owner", "open",
            "not_started", "not_required",
            "y",  # record a plan
            "", "Close the gap", "op", "Evidence package", "evidence registered",
            "medium", "", "wp-1",
            "y", "quit",
        ],
        ["AMR-50"],
    )
    u = st.units["AMR-50"]
    assert u.export_label().value == "Open/Not Met"
    assert u.execution_state == "not_started"
    acts = s.actions_for_unit("AMR-50")
    assert acts and acts[0].is_plan_quality()


def test_fr3_not_yet_due_path(tmp_path):
    st, _, _ = _walk(
        tmp_path,
        [
            "y", "unknown", "yes", "producer", "owner", "as_written",
            "not_yet_due",
            "levied at flight production; program not at phase",
            "unknown", "y", "quit",
        ],
        ["AMR-50"],
    )
    u = st.units["AMR-50"]
    assert u.not_yet_due and u.not_yet_due_justification
    # Fran's corpus: the NYD row still carries a CW commitment
    assert u.fulfillment_path == "as_written"
    assert u.execution_state == "not_started"


def test_fr3_mi_gate_refuses_without_fields(tmp_path):
    s = DispositionSession(tmp_path / "g")
    s.open(actor_name="op")
    with pytest.raises(SessionError, match="Meets Intent requires"):
        s.set_axes(
            "AMR-50",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="alternate_proposed",
            approval_state="required",
        )


# ---------------------------------------------------------------- FR4


class _CannedLive(LiveAdvisor):
    """Keyless live advisor: canned completions, no network."""

    def __init__(self, canned: str):
        super().__init__(model_id="canned-live-model")
        self._canned = canned

    def _complete(self, system: str, user: str) -> str:  # noqa: D401
        if self._canned == "RAISE":
            raise AdvisorError("simulated outage")
        return self._canned


def _hash_ok(res) -> bool:
    return res.output_hash == output_hash(res.model_copy(update={"output_hash": ""}))


def test_fr4_live_propose_hash_integrity(tmp_path):
    s = _seeded_session(tmp_path)
    recs = _records()
    ctx = build_context(s.state.units["AMR-14"], recs["AMR-14"], s.state.facts)
    canned = json.dumps(
        {
            "band": "HIGH",
            "basis": "EFCP absent per facts",
            "proposed_axes": {
                "applicability": "yes",
                "obligated_actor": "producer",
                "organization_responsibility": "owner",
                "implementation_state": "not_met",
                "approval_state": "not_required",
            },
            "proposed_label": "Open/Not Met",
            "questions": [],
        }
    )
    res = _CannedLive(canned).propose(ctx)
    assert res.model_id == "canned-live-model"
    assert res.proposed_label == "Open/Not Met"
    assert _hash_ok(res)


def test_fr4_live_fallback_hash_integrity(tmp_path):
    s = _seeded_session(tmp_path)
    recs = _records()
    ctx = build_context(s.state.units["AMR-14"], recs["AMR-14"], s.state.facts)
    res = _CannedLive("RAISE").propose(ctx)
    assert "live-fallback" in res.basis
    assert res.model_id == "canned-live-model"
    assert _hash_ok(res)


def test_fr4_live_blocked_label_stripped(tmp_path):
    s = _seeded_session(tmp_path)
    recs = _records()
    ctx = build_context(s.state.units["AMR-14"], recs["AMR-14"], s.state.facts)
    ctx = ctx.model_copy(update={"blocked_labels": {"Open/Not Met": "test"}})
    canned = json.dumps(
        {
            "band": "HIGH",
            "basis": "x",
            "proposed_axes": {"applicability": "yes"},
            "proposed_label": "Open/Not Met",
            "questions": [],
        }
    )
    res = _CannedLive(canned).propose(ctx)
    assert res.proposed_label is None and res.proposed_axes is None
    assert _hash_ok(res)


# ---------------------------------------------------------------- FR5


def test_fr5_blocklist_scans_comments(tmp_path):
    s = DispositionSession(tmp_path / "lib")
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
        comment="Contract No. ABC-99 flowdown satisfied",
    )
    s.attest_unit(
        "AMR-1", actor_name="op", role="disposition_author", decision="accepted"
    )
    with pytest.raises(LibraryError, match="disposition comment"):
        export_library(s, tmp_path / "lib.json")


def test_fr5_import_suggestions_and_paired_apply(tmp_path):
    s = DispositionSession(tmp_path / "src")
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
        comment="QMS controls implemented per plan",
    )
    s.attest_unit(
        "AMR-1", actor_name="op", role="disposition_author", decision="accepted"
    )
    # AR5: a paired "no" needs the operator's real citation to elect N/A
    s.apply_paired_answer(
        "scope.joining_in_crediting", "no", "op",
        scope_citation="6030 §1.2: joining processes excluded from crediting scope",
    )
    out = export_library(s, tmp_path / "lib.json")

    d = DispositionSession(tmp_path / "dst")
    d.open(actor_name="op")
    res = import_library(d, out, actor_name="op")
    assert res["disposition_suggestions"] >= 1
    assert "AMR-1" in d.state.library_suggestions
    # AF5: paired answers APPLY through the gated path, never silent
    assert d.state.units["AMR-21"].applicability == "no"
    assert d.state.units["AMR-21"].scope_citation


# ---------------------------------------------------------------- FR6


def test_fr6_appendix_xlsx_full_text_and_guide(tmp_path):
    import zipfile

    s = DispositionSession(tmp_path / "e")
    s.open(actor_name="op")
    recs = _records()
    from oracle.disposition.export import export_dual_products

    paths = export_dual_products(s, recs, tmp_path / "out", include_draft=True)
    assert str(paths["appendix_a"]).endswith(".xlsx")
    with zipfile.ZipFile(paths["appendix_a"]) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    long_text = recs["AMR-39"].shall_text
    probe = long_text[300:380]
    assert probe and (probe in sheet or probe.replace("&", "&amp;") in sheet)
    guide = paths["implementation_guide"].read_text(encoding="utf-8")
    assert "Done-when" in guide and "Related AMRs" in guide
    assert "— (not yet established)" in guide  # explicit gaps, never invented


# ---------------------------------------------------------------- FR7


def test_fr7_fail_closed_without_curated(tmp_path):
    with pytest.raises(PackPinError, match="Curated 6030 pack missing"):
        load_rdw_default_packs(curated_path=tmp_path / "nope.json")
    recs, _ = load_rdw_default_packs(
        curated_path=tmp_path / "nope.json", allow_builtin=True
    )
    assert recs  # explicit escape loads the builtin (with a logged warning)


# ---------------------------------------------------------------- FR8


def _corpus_rows_ok():
    """115 coherent rows hitting the exact engagement tallies (AR11: rows
    carry full axes and label/axis coherence, not just matching counts)."""
    # (contract, readiness, applicability, org, implementation, approval, plan?)
    shapes = (
        [("CW", "Met", "yes", "owner", "meets_as_written", "not_required", False)] * 2
        + [("CW", "Not Met with Plan", "yes", "owner", "not_met", "not_required", True)] * 32
        + [("EX", "Not Met with Plan", "yes", "owner", "not_met", "required", True)] * 7
        + [("CW", "TBD", "yes", "owner", "tbd", "tbd", False)] * 28
        + [("MI", "TBD", "yes", "owner", "alternate_proposed", "required", False)] * 6
        + [("CW", "Program Action", "yes", "external", "tbd", "tbd", False)] * 18
        + [("NA", "Technical N/A", "no", "external", "not_reached", "not_required", False)] * 17
        + [("CW", "Technical N/A", "no", "external", "not_reached", "not_required", False)] * 4
        + [("CW", "Not Yet Due", "yes", "owner", "tbd", "tbd", False)] * 1
    )
    rows = []
    for i, (cl, rl, app, org, impl, appr, plan) in enumerate(shapes):
        rows.append(
            CorpusRow(
                requirement_id=f"AMR-{i + 1}",
                contract_label=cl,
                readiness_label=rl,
                applicability=app,
                organization_responsibility=org,
                implementation_state=impl,
                approval_state=appr,
                work_package=f"WP-{(i % 16) + 1}",
                action_ids=(f"A-{i + 1}",) if plan else (),
            )
        )
    return rows


def test_fr8_reconciliation_exact():
    assert_reconciled(_corpus_rows_ok())


def test_fr8_reconciliation_rejects_drift():
    rows = _corpus_rows_ok()
    bad = rows[:-1] + [rows[-1].model_copy(update={"contract_label": "NA"})]
    with pytest.raises(CorpusError, match="Contract counts differ|contract NA"):
        assert_reconciled(bad)


def test_fr8_loader_roundtrip(tmp_path):
    p = tmp_path / "corpus.csv"
    lines = [
        "requirement_id,contract_label,readiness_label,applicability,"
        "organization_responsibility,implementation_state,approval_state,"
        "work_package,action_ids"
    ]
    for r in _corpus_rows_ok():
        lines.append(
            f"{r.requirement_id},{r.contract_label},{r.readiness_label},"
            f"{r.applicability},{r.organization_responsibility},"
            f"{r.implementation_state},{r.approval_state},"
            f"{r.work_package},{';'.join(r.action_ids)}"
        )
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = load_corpus(p)
    assert_reconciled(rows)


def test_fr8_golden_blocked_until_corpus_exists():
    if corpus_path() is None:
        pytest.skip(
            "115-row engagement corpus not yet provided (set RDW_CORPUS_PATH "
            "to the scrubbed CSV per RDW_FIX3_HANDOFF FR8)"
        )
    rows = load_corpus(corpus_path())
    assert_reconciled(rows)
