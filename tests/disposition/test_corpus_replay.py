"""CR3 — corpus-replay golden (identity-first, Fran ruling 2026-08-02).

The synthetic corpus below is SYNTHETIC: unit ids are real pack ids but
the label assignments are test shapes, NOT engagement truth (operator
instruction 2026-08-02 — never treat these identities as adjudicated).
The real engagement corpus runs via RDW_CORPUS_PATH and is compared row
by row against its own locked identities. BoundState AI 2026.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from oracle.disposition.corpus import (
    CorpusRow,
    assert_reconciled,
    corpus_path,
    load_corpus,
    load_work_packages,
)
from oracle.disposition.replay import replay_corpus
from oracle.disposition.session import DispositionSession
from oracle.disposition.workpackage import WorkPackageRecord

_FIELDS = list(CorpusRow.model_fields.keys())


def _write_corpus(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in _FIELDS}, **r})
    return path


def _write_wps(corpus: Path, wps: list[dict]) -> Path:
    sib = corpus.with_name(corpus.stem + ".workpackages.csv")
    fields = list(WorkPackageRecord.model_fields.keys())
    with sib.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in wps:
            w.writerow({**{k: "" for k in fields}, **r})
    return sib


# SYNTHETIC shapes — one per label class the engine must reproduce.
_SYNTH_ROWS = [
    dict(requirement_id="AMR-45", contract_label="CW", readiness_label="Met",
         applicability="yes", obligated_actor="producer",
         organization_responsibility="owner", fulfillment_path="as_written",
         execution_state="evidenced", approval_state="not_required",
         evidence_refs="QMS@A", evidence_date="2026-01-01"),
    dict(requirement_id="AMR-46", contract_label="CW",
         readiness_label="Not Met with Plan", applicability="yes",
         obligated_actor="producer", organization_responsibility="owner",
         fulfillment_path="as_written", execution_state="not_started",
         approval_state="not_required", action_ids="WP-1"),
    dict(requirement_id="AMR-47", contract_label="CW", readiness_label="TBD",
         applicability="yes", obligated_actor="producer",
         organization_responsibility="owner", fulfillment_path="as_written",
         execution_state="tbd", approval_state="not_required"),
    dict(requirement_id="AMR-48", contract_label="CW",
         readiness_label="Program Action", applicability="yes",
         obligated_actor="program", organization_responsibility="external",
         fulfillment_path="as_written", execution_state="not_started",
         approval_state="not_required", action_ids="WP-1"),
    dict(requirement_id="AMR-49", contract_label="CW",
         readiness_label="Not Yet Due", applicability="yes",
         obligated_actor="producer", organization_responsibility="owner",
         fulfillment_path="as_written", execution_state="not_started",
         approval_state="not_required", not_yet_due="yes",
         not_yet_due_justification="levied at first delivery"),
    dict(requirement_id="AMR-52", contract_label="MI",
         readiness_label="Not Met with Plan", applicability="yes",
         obligated_actor="producer", organization_responsibility="owner",
         fulfillment_path="alternative_intent", execution_state="partial",
         approval_state="required", intent_statement="control the process",
         alternative_control="vendor QMS control", control_class="integral",
         action_ids="WP-1"),
    dict(requirement_id="AMR-53", contract_label="EX",
         readiness_label="Not Met with Plan", applicability="yes",
         obligated_actor="producer", organization_responsibility="owner",
         fulfillment_path="exception", execution_state="not_started",
         approval_state="required",
         exception_basis="cannot meet as written for this process",
         closure_action_id="WP-1", action_ids="WP-1"),
    dict(requirement_id="AMR-54", contract_label="NA",
         readiness_label="Technical N/A", applicability="no",
         organization_responsibility="external",
         fulfillment_path="not_applicable", execution_state="not_started",
         approval_state="not_required",
         scope_citation="6030 1.2: outside the declared scope"),
]
_SYNTH_WPS = [
    dict(wp_id="WP-1", title="Synthetic closure package", gate="Gate 1",
         priority="P0", owner="op", objective="close the synthetic gaps",
         affected_unit_ids="AMR-46; AMR-48; AMR-52; AMR-53",
         exit_criteria="all synthetic evidence accepted"),
]


def test_synthetic_replay_every_label_class(tmp_path):
    corpus = _write_corpus(tmp_path / "synthetic_corpus.csv", _SYNTH_ROWS)
    _write_wps(corpus, _SYNTH_WPS)
    rows = load_corpus(corpus)
    assert_reconciled(rows)  # coherence floor holds on v2 rows
    assert len(load_work_packages(corpus)) == 1

    report = replay_corpus(corpus, tmp_path / "sess")
    assert report.replayed == len(_SYNTH_ROWS)
    assert report.ok, f"mismatches: {report.mismatches}"
    # tallies are computed OUTPUTS (identity-first) — spot-check shape
    assert report.contract_tally["CW"] == 5
    assert report.readiness_tally["Not Met with Plan"] == 3

    # the replayed session is a REAL session: resumable, attested, WP-bearing
    st = DispositionSession(tmp_path / "sess").resume(actor_name="replay")
    assert st.units["AMR-45"].review_state == "accepted"
    assert "WP-1" in st.work_packages


def test_synthetic_replay_surfaces_identity_mismatch(tmp_path):
    """A corpus row whose locked code the engine cannot derive is a NAMED
    mismatch — identity comparison, not tally comparison."""
    # coherent under the floor (no CW->fulfillment rule, by design) but
    # underivable: an exception-elected row locked as CW
    rows = [dict(_SYNTH_ROWS[6])]
    rows[0]["contract_label"] = "CW"
    corpus = _write_corpus(tmp_path / "bad_corpus.csv", rows)
    _write_wps(corpus, _SYNTH_WPS)
    report = replay_corpus(corpus, tmp_path / "sess")
    assert not report.ok
    assert any(
        m.kind == "contract" and m.requirement_id == "AMR-53"
        and m.expected == "CW" and m.derived == "EX"
        for m in report.mismatches
    )


def test_work_package_record_replays(tmp_path):
    s = DispositionSession(tmp_path / "s")
    s.open(actor_name="op")
    s.record_work_package(
        WorkPackageRecord(
            wp_id="GOV-01", title="Governance", gate="Gate 0", owner="op",
            exit_criteria="approvals recorded",
        ),
        actor_name="op",
    )
    st = DispositionSession(tmp_path / "s").resume(actor_name="op")
    assert st.work_packages["GOV-01"].gate == "Gate 0"
    assert st.work_packages["GOV-01"].is_plan_quality()


# ------------------------------------- Atlas corpus-replay findings


def test_cr1_split_elected_never_caller_settable(tmp_path):
    """Atlas High 1: forged provenance unlocked the split-only allowances."""
    from oracle.disposition.session import SessionError

    s = DispositionSession(tmp_path / "s")
    s.open(actor_name="op")
    with pytest.raises(SessionError, match="never caller-settable"):
        s.set_axes(
            "AMR-50",
            actor_name="op",
            split_elected=True,
            exception_basis="forged",
            permanent_relief_basis="forged",
        )
    assert not s.state.units["AMR-50"].split_elected


def test_cr2_evidenced_claim_blocked_label_independently(tmp_path):
    """Atlas High 2: an evidenced claim under an unresolved prerequisite
    must refuse whatever label it maps to — including Exception."""
    from oracle.disposition.session import EvidenceRef, SessionError

    s = DispositionSession(tmp_path / "s")
    s.open(actor_name="op")
    s.register_evidence(doc_id="DOC", revision="1", unit_ids=("AMR-2",),
                        effective_date="2026-01-01")
    s.attach_evidence("AMR-2", EvidenceRef(doc_id="DOC", revision="1"), "op")
    with pytest.raises(SessionError, match="blocked"):
        s.set_axes(
            "AMR-2",  # AMCP + ceo.identity unresolved
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            fulfillment_path="exception",
            execution_state="evidenced",
            approval_state="required",
            exception_basis="basis",
            permanent_relief_basis="relief",
        )
    # the same election WITHOUT the evidenced claim elects fine
    u = s.set_axes(
        "AMR-2",
        actor_name="op",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        fulfillment_path="exception",
        execution_state="not_started",
        approval_state="required",
        exception_basis="basis",
        permanent_relief_basis="relief",
    )
    assert u.export_label().value == "Exception"


def test_cr3_replay_enforces_floor_and_full_split(tmp_path):
    """Atlas High 3: a half-split row must refuse, never replay on a
    defaulted axis; the harness runs the same floor as the checker."""
    from oracle.disposition.corpus import CorpusError

    row = dict(_SYNTH_ROWS[1])
    row["execution_state"] = ""  # fulfillment set, execution blank
    corpus = _write_corpus(tmp_path / "half.csv", [row])
    with pytest.raises(CorpusError, match="axis implementation_state is blank"):
        replay_corpus(corpus, tmp_path / "s")
    # duplicate identities refuse at the public floor too
    r = CorpusRow(
        requirement_id="AMR-1", contract_label="CW", readiness_label="Met",
        applicability="yes", organization_responsibility="owner",
        fulfillment_path="as_written", execution_state="evidenced",
        approval_state="not_required",
    )
    with pytest.raises(CorpusError, match="duplicate requirement_id"):
        assert_reconciled([r, r])


def test_cr4_work_package_sibling_is_d3_scanned(tmp_path):
    """Atlas Medium 4: identifiers in the sibling refused before persistence."""
    from oracle.disposition.corpus import CorpusError

    corpus = _write_corpus(tmp_path / "c.csv", [_SYNTH_ROWS[1]])
    wps = [dict(_SYNTH_WPS[0])]
    wps[0]["dependencies"] = "per contract no. NNX99AB12C"
    _write_wps(corpus, wps)
    with pytest.raises(CorpusError, match="identifier hits"):
        replay_corpus(corpus, tmp_path / "s")
    from oracle.disposition.corpus_scrub import check

    rep = check(corpus)
    assert rep["reconciled"] is False
    assert any("work package" in e for e in rep["coherence_errors"])


def test_cr5_wp_supersession_stable_and_duplicates_refused(tmp_path):
    """Atlas Medium 5: self-supersession rejected; live == resume;
    duplicate sibling rows refuse."""
    from oracle.disposition.corpus import CorpusError, load_work_packages

    with pytest.raises(ValueError, match="supersede itself"):
        WorkPackageRecord(wp_id="GOV-01", title="x", supersedes="GOV-01")

    s = DispositionSession(tmp_path / "s")
    s.open(actor_name="op")
    s.record_work_package(
        WorkPackageRecord(wp_id="GOV-01", title="v1"), actor_name="op"
    )
    s.record_work_package(
        WorkPackageRecord(wp_id="GOV-02", title="v2", supersedes="GOV-01"),
        actor_name="op",
    )
    live = {k: w.status for k, w in s.state.work_packages.items()}
    st = DispositionSession(tmp_path / "s").resume(actor_name="op")
    resumed = {k: w.status for k, w in st.work_packages.items()}
    assert live == resumed == {"GOV-01": "superseded", "GOV-02": "open"}

    corpus = _write_corpus(tmp_path / "c.csv", [_SYNTH_ROWS[1]])
    _write_wps(corpus, [_SYNTH_WPS[0], _SYNTH_WPS[0]])
    with pytest.raises(CorpusError, match="duplicate wp_id"):
        load_work_packages(corpus)


# ---------------------------------------------------------- the real golden


def test_engagement_corpus_replay_golden(tmp_path):
    """The acceptance test: replay the adjudicated engagement corpus and
    compare engine-derived labels against every locked row identity."""
    p = corpus_path()
    if p is None:
        pytest.skip(
            "engagement corpus not present (set RDW_CORPUS_PATH to the "
            "scrubbed corpus CSV per RDW_CORPUS_REPLAY_SPEC)"
        )
    report = replay_corpus(p, tmp_path / "golden_sess")
    assert report.replayed == report.rows
    assert report.ok, (
        f"{len(report.mismatches)} identity mismatches: "
        f"{report.mismatches[:10]}"
    )
    # Anchors (standard-scoped ids + expected codes only; the full map
    # lives outside the repo). Contract codes per the 2026-08-02
    # adjudication; readiness per the RevA matrix.
    rows = {r.requirement_id: r for r in load_corpus(p)}
    anchors = {
        "AMR-2": ("CW", "Program Action"),
        "AMR-14": ("CW", "Not Met with Plan"),
        "AMR-51": ("MI", "Not Met with Plan"),
        "AMR-57": ("CW", "Not Met with Plan"),
        "AMR-106": ("CW", "Not Met with Plan"),
        "AMR-113": ("CW", "Program Action"),
    }
    for uid, (code, ready) in anchors.items():
        assert rows[uid].contract_label == code, f"{uid} contract"
        assert rows[uid].readiness_label == ready, f"{uid} readiness"
