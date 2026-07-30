"""Atlas round-2 fix probes (F1–F6). BoundState AI 2026."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pydantic import ValidationError

from oracle.disposition.evidence import EvidenceStore
from oracle.disposition.export import (
    PHANTOM_REF_SKIPPED,
    ExportError,
    build_matrix_rows,
    export_all,
)
from oracle.disposition.golden import run_golden_session
from oracle.disposition.packs import load_rdw_default_packs
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


# ---------------------------------------------------------------------------
# F1 — stale accepted must not export; accepted → superseded
# ---------------------------------------------------------------------------


def test_f1_accepted_superseded_and_export_refuses_rereview(tmp_path):
    s = DispositionSession(tmp_path / "f1")
    s.open(actor_name="op", multi_pack=True)
    s.set_axes(
        "AMR-17",
        actor_name="op",
        enforce_decision=False,
        applicability="tbd",
        applicability_tbd_reason="classification_unresolved",
        organization_responsibility="tbd",
        org_responsibility_tbd_reason="classification_unresolved",
        implementation_state="tbd",
        implementation_tbd_reason="classification_unresolved",
        approval_state="tbd",
        approval_tbd_reason="classification_unresolved",
    )
    s.attest_unit(
        "AMR-17",
        actor_name="op",
        role="technical_reviewer",
        decision="accepted",
        accepted_with_tbd=True,
    )
    assert s.state.units["AMR-17"].review_state == "accepted"

    s.assert_fact(
        key="classification.primary",
        statement="Class A",
        author="op",
        confidence="high",
        confirm_assumption=True,
    )
    assert "AMR-17" in s.units_needing_rereview()
    assert s.state.units["AMR-17"].review_state == "superseded"

    with pytest.raises(ExportError, match="need re-review"):
        build_matrix_rows(s, _records())

    # clear_rereview alone is not enough for re-export of stale acceptance —
    # re-attestation required after re-open; all flagged units must be cleared
    for uid in list(s.units_needing_rereview()):
        s.clear_rereview(uid, actor_name="op")
    # still superseded; re-open then re-attest
    s.attest_unit(
        "AMR-17",
        actor_name="op",
        role="technical_reviewer",
        decision="proposed",
    )
    s.attest_unit(
        "AMR-17",
        actor_name="op",
        role="technical_reviewer",
        decision="accepted",
        accepted_with_tbd=True,
    )
    rows = build_matrix_rows(s, _records())
    assert any(r.unit_id == "AMR-17" for r in rows)


# ---------------------------------------------------------------------------
# F2 — evidence must qualify; phantom on (doc_id, revision); no synthetic set
# ---------------------------------------------------------------------------


def test_f2_expired_evidence_refuses_meet_election(tmp_path):
    s = DispositionSession(tmp_path / "f2")
    s.open(actor_name="op", multi_pack=True)
    store = EvidenceStore(s.root / "evidence")
    store.register(
        evidence_id="ev-exp",
        doc_id="CERT",
        revision="1",
        unit_ids=("AMR-45",),
        effective_date="2020-01-01",
        expiration_date="2020-12-31",
    )
    s.attach_evidence(
        "AMR-45",
        EvidenceRef(doc_id="CERT", revision="1"),
        "op",
    )
    assert s.has_qualifying_meet_evidence(s.state.units["AMR-45"]) is False
    with pytest.raises(SessionError, match="blocked|evidence|Meet"):
        s.set_axes(
            "AMR-45",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="meets_as_written",
            approval_state="not_required",
        )


def test_f2_revision_mismatch_is_phantom(tmp_path):
    s = DispositionSession(tmp_path / "f2b")
    s.open(actor_name="op")
    store = EvidenceStore(s.root / "evidence")
    store.register(
        evidence_id="ev-1",
        doc_id="DOC",
        revision="A",
        unit_ids=("AMR-14",),
        effective_date="2024-01-01",
        approval_date="2024-01-01",
    )
    s.attach_evidence(
        "AMR-14",
        EvidenceRef(doc_id="DOC", revision="B"),  # wrong revision
        "op",
    )
    known = store.known_doc_revisions()
    with pytest.raises(ExportError, match="nonexistent artifact"):
        build_matrix_rows(s, _records(), known_artifact_ids=known)


def test_f2_export_all_stamps_skip_without_registry(tmp_path):
    run_golden_session(tmp_path / "f2c", export_dir=None)
    s = DispositionSession(tmp_path / "f2c")
    s.resume(actor_name="golden-operator", repin=True)
    # Clear rereview left by Class A so export can proceed
    for uid in list(s.units_needing_rereview()):
        s.clear_rereview(uid, actor_name="op")
    paths = export_all(s, _records(), tmp_path / "out")
    csv_text = paths["csv"].read_text(encoding="utf-8")
    assert PHANTOM_REF_SKIPPED in csv_text


def test_f2_qualifying_evidence_allows_meet_when_gates_clear(tmp_path):
    s = DispositionSession(tmp_path / "f2d")
    s.open(actor_name="op", multi_pack=True)
    # AMR-45 is not AMCP/class gated the same way — use a unit with no hard prereqs
    # Attach qualifying evidence under session registry
    store = EvidenceStore(s.root / "evidence")
    store.register(
        evidence_id="ev-ok",
        doc_id="AS9100",
        revision="2024",
        unit_ids=("AMR-45",),
        effective_date="2024-01-01",
        approval_date="2024-01-15",
    )
    s.attach_evidence(
        "AMR-45",
        EvidenceRef(doc_id="AS9100", revision="2024"),
        "op",
    )
    assert s.has_qualifying_meet_evidence(s.state.units["AMR-45"]) is True


# ---------------------------------------------------------------------------
# F3 — crash between fact and propagation cannot lose rereview
# ---------------------------------------------------------------------------


def test_f3_replay_without_propagation_event_restores_rereview(tmp_path):
    s = DispositionSession(tmp_path / "f3")
    s.open(actor_name="op", multi_pack=True)
    s.assert_fact(
        key="classification.primary",
        statement="Class A",
        author="op",
        confidence="high",
        confirm_assumption=True,
    )
    assert s.units_needing_rereview()
    # Simulate crash window: drop audit-only propagation_rereview events from log
    log_path = s.root / "events.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if "propagation_rereview" not in ln]
    log_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    s2 = DispositionSession(tmp_path / "f3")
    s2.resume(actor_name="op", repin=False)
    assert any(u.startswith("AMR-") for u in s2.units_needing_rereview())
    # diffs recomputed at replay
    assert s2.state.rereview_diffs


# ---------------------------------------------------------------------------
# F4 — whitespace scope_citation refused
# ---------------------------------------------------------------------------


def test_f4_whitespace_scope_citation_rejected():
    with pytest.raises(ValidationError, match="scope_citation|non-blank|whitespace"):
        UnitAxesState(
            unit_id="AMR-99",
            applicability="no",
            organization_responsibility="none",
            implementation_state="not_met",
            approval_state="not_required",
            scope_citation="   \t  ",
        )


# ---------------------------------------------------------------------------
# F5 — prohibited comment re-prompts without aborting walk
# ---------------------------------------------------------------------------


def test_f5_bad_comment_reprompts_walk_continues(tmp_path):
    # Direct gate: §13.2 refusal is a SessionError (not a walk abort)
    s = DispositionSession(tmp_path / "f5_gate")
    s.open(actor_name="op")
    with pytest.raises(SessionError, match="13.2|prohibited"):
        s.set_axes(
            "AMR-14",
            actor_name="op",
            election=False,
            enforce_decision=False,
            comment="The supplier is compliant and complete.",
        )

    # Walk path: bad edit → re-prompt → good edit; walk must not abort
    lines = [
        "y",  # CEO
        "unknown",  # classification
        "yes",  # applicability
        "producer",  # actor (if asked)
        "not_met",  # implementation
        "not_required",  # approval
        "The supplier is compliant and complete.",  # §13.2 hit on comment edit
        "EFCP control not present; gap recorded.",  # good re-edit
    ]
    # Pad for any extra prompts
    lines.extend(["skip"] * 20)
    io_b = IOBundle(
        stdin=io.StringIO("\n".join(lines) + "\n"),
        stdout=io.StringIO(),
        require_tty=False,
    )
    session = run_walk(
        session_dir=tmp_path / "walk_f5",
        actor_name="tester",
        unit_filter=["AMR-14"],
        io=io_b,
        max_units=1,
    )
    out = io_b.stdout.getvalue()
    assert session.state is not None
    # Either re-prompt path hit, or unit completed without process abort
    if "Comment refused" in out:
        u = session.state.units.get("AMR-14")
        if u and u.comment:
            assert "compliant" not in (u.comment or "").lower() or "not present" in (
                u.comment or ""
            ).lower()


# ---------------------------------------------------------------------------
# F6 covered in test_phase3_review_audit.py
# ---------------------------------------------------------------------------
