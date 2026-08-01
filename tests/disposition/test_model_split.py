"""Model split (Fran P0, RDW_MODEL_SPLIT_SPEC.md): fulfillment_path drives
the contract label; execution_state + evidence + actions drive readiness.

Pins: exhaustive legacy-equivalence of the contract mapping against the
frozen pre-split truth table; the AMR-106 and AMR-113 anchors through the
REAL session; replay compatibility for pre-split event payloads; the one
documented readiness divergence; the M7 CEO reopen edges (pack-derived,
with a drift test). Keyless deterministic. BoundState AI 2026.
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

from oracle.disposition.actions import ActionRecord
from oracle.disposition.codes import TBDReason, legacy_from_split, split_from_legacy
from oracle.disposition.decision import evaluate_unit
from oracle.disposition.export_map import (
    AxisContradiction,
    AxisSnapshot,
    map_axes_to_export_label,
)
from oracle.disposition.graph import DependencyGraph
from oracle.disposition.readiness import map_readiness
from oracle.disposition.session import DispositionSession, EvidenceRef, SessionError, UnitAxesState

R = TBDReason.CUSTOMER_INPUT_MISSING

APPL = ("yes", "no", "tbd")
ORG = ("owner", "support", "external", "tbd")
IMPL = ("meets_as_written", "alternate_proposed", "partial", "not_met", "tbd", "not_reached")
APPR = ("not_required", "required", "draft", "submitted", "approved", "rejected", "tbd")


def _legacy_expected(appl, org, impl, appr):
    """The FROZEN pre-split §7.1 truth table (verbatim behavior of the
    engine before the model split). Any drift from this on legacy inputs
    is a replay-compat regression — do not edit to make tests pass."""
    if appl == "tbd":
        return "TBD"
    if appl == "no":
        if impl in ("meets_as_written", "alternate_proposed", "partial", "not_met"):
            return None  # contradiction
        return "N/A"
    if org == "tbd" or impl == "tbd" or appr == "tbd":
        return "TBD"
    if impl == "meets_as_written":
        if appr in ("not_required", "approved"):
            return "Meet"
        if appr == "rejected":
            return "Open/Not Met"
        return "TBD"  # required/draft/submitted
    if impl == "alternate_proposed":
        return "Open/Not Met" if appr == "rejected" else "Meets Intent"
    if impl == "partial":
        return "Open/Not Met"
    if impl == "not_met":
        if appr in ("not_required", "rejected"):
            return "Open/Not Met"
        if org == "external":
            return "Open/Not Met"
        return "Exception"
    return None  # not_reached with applicability yes: contradiction


def _snap(appl, org, impl, appr):
    return AxisSnapshot(
        applicability=appl,
        obligated_actor="producer" if appl == "yes" and org == "owner" else None,
        organization_responsibility=org,
        implementation_state=impl,
        approval_state=appr,
        applicability_tbd_reason=R if appl == "tbd" else None,
        org_responsibility_tbd_reason=R if org == "tbd" else None,
        implementation_tbd_reason=R if impl == "tbd" else None,
        approval_tbd_reason=R if appr == "tbd" else None,
    )


def test_contract_mapping_equivalent_on_every_legacy_combo():
    """504 combos: legacy-only snapshots (auto-converted) derive the exact
    pre-split labels — including which combos are contradictions."""
    diffs = []
    for appl, org, impl, appr in itertools.product(APPL, ORG, IMPL, APPR):
        expected = _legacy_expected(appl, org, impl, appr)
        try:
            got = map_axes_to_export_label(_snap(appl, org, impl, appr)).value
        except AxisContradiction:
            got = None
        if got != expected:
            diffs.append((appl, org, impl, appr, expected, got))
    assert not diffs, f"{len(diffs)} legacy-equivalence diffs, first: {diffs[:5]}"


def test_split_conversion_round_trips():
    for impl, appl, appr in itertools.product(IMPL, APPL, APPR):
        if impl == "not_reached" and appl != "no":
            continue  # invalid/transitional — the mapping rejects it
        ful, execu = split_from_legacy(impl, appl, appr)
        view = legacy_from_split(ful, execu)
        # the view re-splits to the same pair under the same appl/appr
        assert split_from_legacy(view, appl, appr)[0] == ful or appl == "no"


# ------------------------------------------------------------- anchors


def _open(tmp_path, name="s"):
    s = DispositionSession(tmp_path / name)
    s.open(actor_name="op")
    return s


def test_amr106_anchor_cw_plus_not_met_with_plan(tmp_path):
    """Fran P0: commit as-written while execution has not started — ONE
    record, contract Meet(CW), readiness Not Met with Plan."""
    s = _open(tmp_path)
    s.record_action(
        ActionRecord(
            action_id="EIDP-1", title="Stand up EIDP system", owner="op",
            exit_criteria="EIDP operational and populated",
            affected_unit_ids=("AMR-106",),
        ),
        actor_name="op",
    )
    u = s.set_axes(
        "AMR-106",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="as_written",
        execution_state="not_started",
        approval_state="not_required",
    )
    assert u.export_label().value == "Meet"  # contract view: CW
    rr = map_readiness(
        u, s.actions_for_unit("AMR-106"),
        has_qualifying_evidence=s.has_qualifying_meet_evidence(u),
    )
    assert rr.label.value == "Not Met with Plan"
    # legacy view reflects the commitment, split axes stay authoritative
    assert u.implementation_state == "meets_as_written"
    assert u.split_elected


def test_amr113_anchor_ceo_obligation_titomic_support(tmp_path):
    """Fran P0 #2: CEO-obligated, evaluated org supports — External Action,
    never supplier-owned."""
    s = _open(tmp_path)
    s.record_action(
        ActionRecord(
            action_id="QPP-1", title="Support CEO QPP change methodology",
            owner="op", exit_criteria="CEO methodology issued",
            affected_unit_ids=("AMR-113",),
        ),
        actor_name="op",
    )
    u = s.set_axes(
        "AMR-113",
        actor_name="op",
        applicability="yes",
        obligated_actor="ceo",
        organization_responsibility="support",
        fulfillment_path="as_written",
        execution_state="not_started",
        approval_state="not_required",
    )
    rr = map_readiness(u, s.actions_for_unit("AMR-113"))
    assert rr.label.value == "External Action"


def test_evidence_gate_protects_claims_not_commitments(tmp_path):
    """CW + not_started elects without evidence (AMR-106); an evidenced
    CLAIM without qualifying evidence still refuses (C1 preserved)."""
    s = _open(tmp_path)
    u = s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="as_written",
        execution_state="not_started",
        approval_state="not_required",
    )
    assert u.export_label().value == "Meet"
    with pytest.raises(SessionError, match="evidence|blocked"):
        s.set_axes("AMR-50", actor_name="op", execution_state="evidenced")
    # legacy meets_as_written without evidence stays refused too
    with pytest.raises(SessionError, match="evidence|blocked"):
        s.set_axes(
            "AMR-51",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="meets_as_written",
            approval_state="not_required",
        )


def test_nyd_coexists_with_cw_commitment(tmp_path):
    s = _open(tmp_path)
    u = s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="as_written",
        execution_state="not_started",
        approval_state="not_required",
        not_yet_due=True,
        not_yet_due_justification="levied at flight production phase",
    )
    assert u.export_label().value == "Meet"  # contract CW
    assert map_readiness(u, ()).label.value == "Not Yet Due"


# ------------------------------------------------- replay compatibility


def test_pre_split_event_payload_replays(tmp_path):
    """Old event payloads carry no split fields — the model validator
    derives them and labels are unchanged."""
    legacy_payload = {
        "unit_id": "AMR-50",
        "applicability": "yes",
        "obligated_actor": "producer",
        "organization_responsibility": "owner",
        "implementation_state": "not_met",
        "approval_state": "required",
        "applicability_tbd_reason": None,
        "org_responsibility_tbd_reason": None,
        "implementation_tbd_reason": None,
        "approval_tbd_reason": None,
        "exception_basis": "cannot meet as written",
        "closure_path_action_id": "REL-1",
    }
    u = UnitAxesState.model_validate(legacy_payload)
    assert u.fulfillment_path == "exception"
    assert u.execution_state == "not_started"
    assert not u.split_elected
    assert u.export_label().value == "Exception"


def test_legacy_session_resume_preserves_labels(tmp_path):
    s = _open(tmp_path)
    s.register_evidence(doc_id="QMS", revision="A",
                        unit_ids=("AMR-50",), effective_date="2026-01-01")
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="QMS", revision="A"), "op")
    s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="meets_as_written",
        approval_state="not_required",
    )
    before = s.state.units["AMR-50"].export_label().value
    s2 = DispositionSession(tmp_path / "s")
    st = s2.resume(actor_name="op")
    u = st.units["AMR-50"]
    assert u.export_label().value == before == "Meet"
    assert u.execution_state == "evidenced"  # migration applied at replay


# --------------------------------------- documented readiness divergence


def test_alternate_with_plan_is_nmwp_documented_divergence(tmp_path):
    """Pre-split this was TBD Verify by fallthrough; the spec documents the
    change: an alternative control with a live plan IS Not Met with Plan."""
    s = _open(tmp_path)
    s.record_action(
        ActionRecord(
            action_id="ALT-1", title="Implement alternative control",
            owner="op", exit_criteria="control operational",
            affected_unit_ids=("AMR-50",),
        ),
        actor_name="op",
    )
    u = s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="alternate_proposed",
        approval_state="required",
        intent_statement="control the process",
        alternative_control="vendor QMS",
        control_class="integral",
    )
    assert u.export_label().value == "Meets Intent"
    rr = map_readiness(u, s.actions_for_unit("AMR-50"))
    assert rr.label.value == "Not Met with Plan"


# ----------------------------------- Atlas model-split round 1 findings


def test_ms1_execution_tbd_cannot_be_accepted(tmp_path):
    """Atlas High 1: CW commitment with execution TBD attested as fully
    reviewed — the gates read the legacy view instead of execution."""
    s = _open(tmp_path)
    u = s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="as_written",
        execution_state="tbd",
        approval_state="not_required",
    )
    assert u.export_label().value == "Meet"  # commitment stands (contract)
    assert u.execution_state == "tbd"
    with pytest.raises(SessionError, match="review_coherence"):
        s.attest_unit(
            "AMR-50", actor_name="op", role="disposition_author",
            decision="accepted",
        )
    # the explicit accepted-with-TBD election remains available
    s.attest_unit(
        "AMR-50", actor_name="op", role="disposition_author",
        decision="accepted", accepted_with_tbd=True,
    )
    st = DispositionSession(tmp_path / "s").resume(actor_name="op")
    assert st.units["AMR-50"].execution_state == "tbd"


def test_ms2_unevidenced_claim_refused_on_every_path(tmp_path):
    """Atlas High 2: the claim gate must be label-independent — MI/EX/Open
    with an unevidenced evidenced/verified execution all refuse."""
    s = _open(tmp_path)
    with pytest.raises(SessionError, match="qualifying evidence"):
        s.set_axes(
            "AMR-50",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            fulfillment_path="alternative_intent",
            execution_state="evidenced",
            approval_state="required",
            intent_statement="control the process",
            alternative_control="vendor QMS",
            control_class="integral",
        )
    with pytest.raises(SessionError, match="qualifying evidence"):
        s.set_axes(
            "AMR-51",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            fulfillment_path="exception",
            execution_state="verified",
            approval_state="required",
            exception_basis="cannot meet as written",
            permanent_relief_basis="permanent relief granted",
        )
    with pytest.raises(SessionError, match="qualifying evidence"):
        s.set_axes(
            "AMR-52",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            fulfillment_path="tbd",
            execution_state="evidenced",
            approval_state="not_required",
        )


def test_ms3_library_roundtrip_preserves_split_axes(tmp_path):
    """Atlas Medium: legacy-only export round-tripped not_started up to
    evidenced through the migration."""
    from oracle.disposition.library import export_library
    from oracle.disposition.walk import _split_axes_payload

    s = _open(tmp_path, "src")
    s.record_action(
        ActionRecord(
            action_id="P-1", title="plan", owner="op", exit_criteria="done",
            affected_unit_ids=("AMR-106",),
        ),
        actor_name="op",
    )
    s.set_axes(
        "AMR-106",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="as_written",
        execution_state="not_started",
        approval_state="not_required",
    )
    s.attest_unit(
        "AMR-106", actor_name="op", role="disposition_author",
        decision="accepted",
    )
    out = export_library(s, tmp_path / "lib.json")
    axes = json.loads(out.read_text(encoding="utf-8"))["dispositions"][0]["axes"]
    assert axes["fulfillment_path"] == "as_written"
    assert axes["execution_state"] == "not_started"
    # the apply payload keeps the split — never re-migrates the legacy view
    payload = _split_axes_payload(axes)
    assert payload["execution_state"] == "not_started"
    assert "implementation_state" not in payload


# ------------------------------------------- round 2: M3 / M4 / M5


def test_m3_unregistered_citation_never_qualifies(tmp_path):
    """M3 (Fran P1): a typed citation without a registry entry is a claim,
    not qualifying evidence — fail closed, no warn-and-pass."""
    s = _open(tmp_path)
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="QMS", revision="A"), "op")
    assert not s.has_qualifying_meet_evidence(s.state.units["AMR-50"])
    with pytest.raises(SessionError, match="qualifying evidence"):
        s.set_axes(
            "AMR-50",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            fulfillment_path="as_written",
            execution_state="evidenced",
            approval_state="not_required",
        )
    # dated registration is what qualifies
    s.register_evidence(
        doc_id="QMS", revision="A", unit_ids=("AMR-50",),
        effective_date="2026-01-01",
    )
    u = s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="as_written",
        execution_state="evidenced",
        approval_state="not_required",
    )
    assert u.export_label().value == "Meet"
    assert map_readiness(
        u, (), has_qualifying_evidence=s.has_qualifying_meet_evidence(u)
    ).label.value == "Met"


def test_m4_external_exports_gate_on_accepted(tmp_path):
    """M4 (Fran P1): releasable products refuse unaccepted rows; the
    working copy is explicitly DRAFT-watermarked."""
    from oracle.disposition.export import ExportError, export_all

    s = _open(tmp_path)
    recs = {r.requirement_id: r for r in s.loaded_records}
    with pytest.raises(ExportError, match="not review-accepted"):
        export_all(s, recs, tmp_path / "strict")
    paths = export_all(s, recs, tmp_path / "draft", include_draft=True)
    text = paths["csv"].read_text(encoding="utf-8")
    assert "DRAFT — NOT RELEASABLE" in text


def test_m5_prompt_version_is_content_hash():
    """M5 (Fran P2): prompt provenance hashes the prompt CONTENT."""
    import hashlib

    from oracle.disposition.advisor import (
        PROMPT_VERSION,
        SYSTEM_CLOSURE,
        SYSTEM_EXPLAIN,
        SYSTEM_PROPOSE,
    )

    expected = "rdw-advisor/sha256:" + hashlib.sha256(
        "\n---\n".join((SYSTEM_EXPLAIN, SYSTEM_PROPOSE, SYSTEM_CLOSURE)).encode()
    ).hexdigest()[:12]
    assert PROMPT_VERSION == expected
    assert PROMPT_VERSION != "rdw-advisor/v1"


def test_m5_closure_runs_after_elections(tmp_path):
    """M5 (Fran P1): closure suggestions are generated AFTER the operator's
    elections — never from a stale pre-election context."""
    import io as _io

    from oracle.disposition.walk import IOBundle, run_walk

    bundle = IOBundle(
        stdin=_io.StringIO("\n".join(
            ["y", "unknown", "y", "y", "y", "quit"]
        ) + "\n"),
        stdout=_io.StringIO(),
        require_tty=False,
    )
    run_walk(
        session_dir=tmp_path / "s",
        actor_name="op",
        unit_filter=["AMR-14"],
        io=bundle,
        max_units=1,
        advisor=True,
    )
    lines = (tmp_path / "s" / "events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    events = [json.loads(ln)["payload"] for ln in lines]
    closure_idx = [
        i for i, p in enumerate(events)
        if p.get("event_type") == "advisor_output"
        and p.get("kind") == "suggest_closure"
    ]
    election_idx = [
        i for i, p in enumerate(events)
        if p.get("event_type") == "election"
        and (p.get("unit") or {}).get("unit_id") == "AMR-14"
    ]
    assert closure_idx and election_idx
    # every AXIS election happened before closure (the comment write —
    # an axis_set — legitimately follows closure in the done branch)
    assert all(i < min(closure_idx) for i in election_idx)


# --------------------------------- Atlas model-split round 2 findings


def test_ms4_evidence_same_artifact_must_be_cited_and_linked(tmp_path):
    """Atlas r2 High 1: a qualifying-but-uncited artifact plus a
    cited-but-other-unit artifact must never combine into a pass."""
    s = _open(tmp_path)
    # A: qualifying, linked to AMR-50, NOT cited
    s.register_evidence(doc_id="DOC-A", revision="1", unit_ids=("AMR-50",),
                        effective_date="2026-01-01")
    # B: qualifying, linked ONLY to AMR-51, cited by AMR-50
    s.register_evidence(doc_id="DOC-B", revision="1", unit_ids=("AMR-51",),
                        effective_date="2026-01-01")
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="DOC-B", revision="1"), "op")
    assert not s.has_qualifying_meet_evidence(s.state.units["AMR-50"])
    # citing the SAME linked artifact is what qualifies
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="DOC-A", revision="1"), "op")
    assert s.has_qualifying_meet_evidence(s.state.units["AMR-50"])


def test_ms5_direct_writers_invoke_release_gate(tmp_path):
    """Atlas r2 High 2: export_csv/docx/xlsx must gate themselves."""
    import zipfile

    from oracle.disposition.export import (
        ExportError,
        export_csv,
        export_docx,
        export_xlsx,
    )

    s = _open(tmp_path)
    recs = {r.requirement_id: r for r in s.loaded_records}
    for fn, name in (
        (export_csv, "m.csv"), (export_docx, "m.docx"), (export_xlsx, "m.xlsx")
    ):
        with pytest.raises(ExportError, match="not review-accepted"):
            fn(s, recs, tmp_path / name)
    p = export_csv(s, recs, tmp_path / "d.csv", include_draft=True)
    assert "DRAFT — NOT RELEASABLE" in p.read_text(encoding="utf-8")
    px = export_xlsx(s, recs, tmp_path / "d.xlsx", include_draft=True)
    with zipfile.ZipFile(px) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".xml"))
    assert b"NOT RELEASABLE" in blob


def test_ms6_malformed_dates_never_qualify(tmp_path):
    """Atlas r2 Medium 3: effective/approval dates parse fail-closed."""
    from oracle.disposition.evidence import EvidenceArtifact, evidence_supports_meet

    s = _open(tmp_path)
    s.register_evidence(doc_id="DOC", revision="1", unit_ids=("AMR-50",),
                        effective_date="not-a-date")
    s.attach_evidence("AMR-50", EvidenceRef(doc_id="DOC", revision="1"), "op")
    assert not s.has_qualifying_meet_evidence(s.state.units["AMR-50"])
    res = evidence_supports_meet(
        EvidenceArtifact(
            evidence_id="E", doc_id="D", revision="1",
            effective_date="not-a-date",
        )
    )
    assert not res.ok and any("unparseable effective_date" in r for r in res.reasons)


def test_ms7_appendix_gate_scopes_to_exported_rows(tmp_path):
    """Atlas r2 Medium 4: Appendix A (AMR-only) must not refuse over
    excluded EFCR rows; the full supplier suite still does."""
    from oracle.disposition.export import (
        ExportError,
        export_all,
        export_appendix_a,
    )

    s = _open(tmp_path)
    recs = {r.requirement_id: r for r in s.loaded_records}
    for uid in s.state.units:
        if uid.upper().startswith("AMR-"):
            s.attest_unit(
                uid, actor_name="op", role="disposition_author",
                decision="accepted", accepted_with_tbd=True,
            )
    p = export_appendix_a(
        s, recs, tmp_path / "a.csv", enforce_decision=False
    )  # strict — EFCRs unaccepted but not exported here
    assert "NOT RELEASABLE" not in p.read_text(encoding="utf-8")
    with pytest.raises(ExportError, match="not review-accepted"):
        export_all(s, recs, tmp_path / "suite")  # EFCRs ARE in this product


# ----------------------------------------------------- M7 CEO reopening


def test_m7_ceo_edges_match_pack_text():
    """Drift test: the reopen edge list is DERIVED from the curated pack —
    re-derive and compare so pack recuration flags stale edges."""
    p = Path(__file__).resolve().parents[2] / (
        "oracle/disposition/data/nasa_std_6030_curated.json"
    )
    d = json.loads(p.read_text(encoding="utf-8"))
    recs = d.get("requirements") or d.get("records") or d
    expected = set()
    for r in recs:
        t = " ".join(
            str(r.get(k) or "")
            for k in ("shall_text", "requirement", "context", "notes", "rationale")
        )
        if re.search(r"\bCEO\b|cognizant engineering", t, re.I):
            expected.add((r.get("id") or "").upper())
    g = DependencyGraph.from_seeds()
    reopen = {
        e.dependent_id
        for e in g.edges
        if e.fact_key == "ceo.identity" and e.kind == "reopen_fact"
    }
    blocking = {
        e.dependent_id
        for e in g.edges
        if e.fact_key == "ceo.identity" and e.kind == "fact"
    }
    assert blocking == {"AMR-2", "AMR-4"}  # richer edges keep blocking
    assert reopen | blocking == expected | {"AMR-2", "AMR-4"}


def test_m7_ceo_change_reopens_amr113_without_blocking_meet(tmp_path):
    g = DependencyGraph.from_seeds()
    assert "AMR-113" in g.propagate_from_fact("ceo.identity")
    # reopen edges never block elections or drive advisor LOW
    unit = UnitAxesState(
        unit_id="AMR-113",
        applicability="yes",
        obligated_actor="ceo",
        organization_responsibility="support",
        fulfillment_path="as_written",
        execution_state="not_started",
        approval_state="not_required",
    )
    res = evaluate_unit(unit, facts={})  # ceo.identity entirely unresolved
    assert "Meet" not in res.blocked
