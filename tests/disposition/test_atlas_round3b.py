"""Atlas re-review of the AR fixes — regressions for findings N1-N10 and
the AR11 completion (coherence floor).

Keyless-deterministic. BoundState AI 2026.
"""

from __future__ import annotations

import io as _io
import json
import zipfile

import pytest

from oracle.disposition.corpus import (
    CorpusError,
    CorpusRow,
    assert_reconciled,
    load_corpus,
)
from oracle.disposition.export import _write_xlsx_book
from oracle.disposition.library import LibraryError, export_library, import_library
from oracle.disposition.session import (
    DispositionSession,
    EvidenceRef,
    SessionError,
)
from oracle.disposition.walk import IOBundle, run_walk


def _open(tmp_path, name="s"):
    s = DispositionSession(tmp_path / name)
    s.open(actor_name="op")
    return s


# ------------------------------------------------------------------- N1


def test_n1_class_gated_na_blocked_even_with_citation(tmp_path):
    """Atlas critical N1: AMR-17 accepted+exported N/A on a bare assertion."""
    s = _open(tmp_path)
    with pytest.raises(SessionError, match="blocked|classification"):
        s.set_axes(
            "AMR-17",
            actor_name="op",
            applicability="no",
            organization_responsibility="external",
            implementation_state="not_reached",
            approval_state="not_required",
            scope_citation="operator assertion: out of scope",
        )


def test_n1_class_gated_na_allowed_once_classification_confirmed(tmp_path):
    s = _open(tmp_path)
    s.assert_fact(
        key="classification.primary",
        statement="Class B secondary structure",
        author="op",
        confidence="high",
    )
    u = s.set_axes(
        "AMR-17",
        actor_name="op",
        applicability="no",
        organization_responsibility="external",
        implementation_state="not_reached",
        approval_state="not_required",
        scope_citation="6030 §1.2: class excludes this control",
    )
    assert u.export_label().value == "N/A"


def test_n1_non_class_prerequisites_still_permit_cited_na(tmp_path):
    # AR8 behavior preserved: AMR-2 (ceo.identity edge) with a citation
    s = _open(tmp_path)
    u = s.set_axes(
        "AMR-2",
        actor_name="op",
        applicability="no",
        organization_responsibility="external",
        implementation_state="not_reached",
        approval_state="not_required",
        scope_citation="6030 §1.2: not flight hardware",
    )
    assert u.export_label().value == "N/A"


# ------------------------------------------------------------------- N2


def test_n2_partial_seed_leaves_applicability_to_interview(tmp_path):
    """Atlas high N2: seeded applicability skipped the classification ask."""
    d = DispositionSession(tmp_path / "s")
    d.open(actor_name="op")
    d.record_library_import(
        source_session_id="src",
        dispositions=[
            {
                "requirement_id": "AMR-17",
                "export_label": "Meet",
                "axes": {
                    "applicability": "yes",
                    "obligated_actor": "producer",
                    "organization_responsibility": "owner",
                    "implementation_state": "meets_as_written",
                    "approval_state": "not_required",
                },
                "comment": None,
                "accepted_with_tbd": False,
                "provenance": {"session_id": "src"},
            }
        ],
        action_patterns=[],
        actor_name="op",
    )
    bundle = IOBundle(
        stdin=_io.StringIO("y\nunknown\ny\nquit\n"),  # intake, accept sug, quit
        stdout=_io.StringIO(),
        require_tty=False,
    )
    run_walk(
        session_dir=tmp_path / "s",
        actor_name="op",
        unit_filter=["AMR-17"],
        io=bundle,
        max_units=1,
    )
    s2 = DispositionSession(tmp_path / "s")
    st = s2.resume(actor_name="op")
    u = st.units["AMR-17"]
    out = bundle.stdout.getvalue()
    # suggestion refused (Meet without evidence) -> partial seed must NOT
    # set applicability, so the classification question stays reachable
    assert "refused" in out
    assert u.applicability == "tbd"
    assert u.obligated_actor == "producer"  # ungated axes still seeded


# ------------------------------------------------------------------- N3


def test_n3_walk_and_session_expose_pinned_records(tmp_path):
    s = _open(tmp_path)
    assert s.loaded_records, "session must retain the records it pinned"
    ids = {r.requirement_id for r in s.loaded_records}
    assert set(s.state.units.keys()) == ids  # renderers see the same set


# ------------------------------------------------------------------- N4


def test_n4_legacy_bad_comment_does_not_wedge_axes(tmp_path):
    s = _open(tmp_path)
    # Simulate a pre-fix session: plant a prohibited comment via model_copy
    # on state (bypassing the gate the way an old event log would).
    u = s.state.units["AMR-50"]
    s.state.units["AMR-50"] = u.model_copy(
        update={"comment": "This requirement is compliant"}
    )
    got = s.set_axes(
        "AMR-50",
        actor_name="op",
        applicability="yes",
        election=False,
    )
    assert got.applicability == "yes"  # axis update proceeds
    # but CHANGING the comment to prohibited text still refuses
    with pytest.raises(SessionError, match="13.2"):
        s.set_axes(
            "AMR-50",
            actor_name="op",
            comment="Fully compliant, guaranteed",
            comment_status="edited",
            election=False,
        )


# ------------------------------------------------------------------- N5


def test_n5_paired_apply_is_one_atomic_batch(tmp_path):
    """Atlas medium N5: crash between elections left the pair divergent."""
    s = _open(tmp_path)
    before = len(
        (tmp_path / "s" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    )
    s.apply_paired_answer(
        "scope.joining_in_crediting", "no", "op",
        scope_citation="6030 §1.2: excluded",
    )
    lines = (
        (tmp_path / "s" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    )
    batch = [json.loads(ln) for ln in lines[before:]]
    types = [b["payload"]["event_type"] for b in batch]
    # elections + record share one batch id prefix (single atomic write)
    assert types == ["election", "election", "paired_answer"]
    bases = {b["event_id"].rsplit("-b", 1)[0] for b in batch}
    assert len(bases) == 1
    # chain remains verifiable and replay sees both units + the answer
    s.eventlog.verify()
    s2 = DispositionSession(tmp_path / "s")
    st = s2.resume(actor_name="op")
    assert st.units["AMR-21"].applicability == "no"
    assert st.units["AMR-82"].applicability == "no"
    assert st.paired_answers["scope.joining_in_crediting"] == "no"


# ------------------------------------------------------------------- N6


_HDR = [
    "requirement_id", "contract_label", "readiness_label", "applicability",
    "organization_responsibility", "implementation_state", "approval_state",
    "comment", "work_package", "action_ids", "raw_answers", "evidence_refs",
]
_ROW = ["AMR-1", "CW", "Met", "yes", "owner", "meets_as_written",
        "not_required", "", "wp-1", "", "", ""]


def test_n6_multisheet_xlsx_prefers_named_corpus_sheet(tmp_path):
    stale = [["AMR-STALE"] + _ROW[1:]]
    good = [["AMR-CORRECT"] + _ROW[1:]]
    p = _write_xlsx_book(
        tmp_path / "multi.xlsx",
        [("Cover", _HDR, stale), ("Corpus", _HDR, good)],
    )
    rows = load_corpus(p)
    assert [r.requirement_id for r in rows] == ["AMR-CORRECT"]


def test_n6_multisheet_without_corpus_name_refuses(tmp_path):
    p = _write_xlsx_book(
        tmp_path / "multi2.xlsx",
        [("Cover", _HDR, [_ROW]), ("Data", _HDR, [_ROW])],
    )
    with pytest.raises(CorpusError, match="none named 'Corpus'"):
        load_corpus(p)


# ------------------------------------------------------------------- N7


def test_n7_evidence_ref_whitespace_normalized(tmp_path):
    from oracle.disposition.evidence import EvidenceStore

    root = tmp_path / "s"
    s = DispositionSession(root)
    s.open(actor_name="op")
    store = EvidenceStore(root / "evidence")
    store.register(
        evidence_id="EV-1", doc_id="REG", revision="A", unit_ids=("AMR-50",),
        effective_date="2026-01-01", approval_date="2026-01-01",
    )
    s.attach_evidence("AMR-50", EvidenceRef(doc_id=" REG ", revision=" A "), "op")
    u = s.state.units["AMR-50"]
    assert u.evidence_refs[0].doc_id == "REG"
    assert u.evidence_refs[0].revision == "A"
    assert s.has_qualifying_meet_evidence(u)


# ------------------------------------------------------------------- N8


def test_n8_library_cli_has_allow_builtin_flag():
    import oracle.cli as cli_mod
    import sys

    for argv in (
        ["oracle", "disposition", "library", "export", "--help"],
        ["oracle", "disposition", "library", "import", "--help"],
    ):
        import io as _io2
        from contextlib import redirect_stdout

        buf = _io2.StringIO()
        old = sys.argv
        sys.argv = argv
        try:
            with redirect_stdout(buf), pytest.raises(SystemExit):
                cli_mod.main()
        finally:
            sys.argv = old
        assert "--allow-builtin" in buf.getvalue()


# ------------------------------------------------------------------- N9


def test_n9_custom_pair_roundtrips_with_citation(tmp_path):
    """Atlas medium N9: custom pair membership + citation were lost."""
    src = _open(tmp_path, "src")
    cite = "6030 §1.2: excluded for this pair"
    src.apply_paired_answer(
        "scope.custom_pair", "no", "op",
        paired_unit_ids=("AMR-50", "AMR-51"),
        scope_citation=cite,
    )
    out = export_library(src, tmp_path / "lib.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "rdw-library/v2"
    assert data["paired_units"]["scope.custom_pair"] == ["AMR-50", "AMR-51"]
    assert data["paired_citations"]["scope.custom_pair"] == cite

    dst = _open(tmp_path, "dst")
    import_library(dst, out, actor_name="op")
    assert dst.state.units["AMR-50"].applicability == "no"
    assert dst.state.units["AMR-50"].scope_citation == cite
    assert dst.state.units["AMR-51"].applicability == "no"
    # classic pair untouched by the custom-pair answer
    assert dst.state.units["AMR-21"].scope_citation is None


def test_n9_unknown_schema_version_refused(tmp_path):
    p = tmp_path / "future.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": "rdw-library/v9",
                "exported_at": "x",
                "source_session_id": "x",
                "pack_hash": "x",
            }
        ),
        encoding="utf-8",
    )
    s = _open(tmp_path)
    with pytest.raises(LibraryError, match="schema_version"):
        import_library(s, p, actor_name="op")


# ------------------------------------------------------------------- N10


def test_n10_malformed_sheet_xml_is_corpus_error(tmp_path):
    import zipfile as _zf

    p = _write_xlsx_book(tmp_path / "bad.xlsx", [("Corpus", _HDR, [_ROW])])
    # Corrupt the worksheet XML inside a still-valid zip
    src = tmp_path / "bad.xlsx"
    dst = tmp_path / "bad2.xlsx"
    with _zf.ZipFile(src) as zin, _zf.ZipFile(dst, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "xl/worksheets/sheet1.xml":
                data = b"<worksheet><unclosed"
            zout.writestr(item, data)
    with pytest.raises(CorpusError, match="Malformed XLSX XML"):
        load_corpus(dst)


# ------------------------------------------------------ AR11 completion


def _blank_axes_rows():
    contract = ["CW"] * 85 + ["MI"] * 6 + ["EX"] * 7 + ["NA"] * 17
    readiness = (
        ["Met"] * 2 + ["Not Met with Plan"] * 39 + ["TBD"] * 34
        + ["Program Action"] * 18 + ["Technical N/A"] * 21 + ["Not Yet Due"] * 1
    )
    return [
        CorpusRow(
            requirement_id=f"AMR-{i + 1}",
            contract_label=contract[i],
            readiness_label=readiness[i],
            work_package=f"WP-{(i % 16) + 1}",
        )
        for i in range(115)
    ]


def test_ar11b_blank_axes_corpus_refused():
    """Atlas AR11-partial probe: matching tallies with empty axes passed."""
    with pytest.raises(CorpusError, match="axis .* is blank"):
        assert_reconciled(_blank_axes_rows())


def test_ar11b_incoherent_label_axis_refused():
    from oracle.disposition.corpus import _assert_row_coherent

    base = dict(
        organization_responsibility="external",
        implementation_state="not_reached",
        approval_state="not_required",
    )
    # NA claiming applicability=yes must refuse
    with pytest.raises(CorpusError, match="contract NA but applicability"):
        _assert_row_coherent(
            CorpusRow(
                requirement_id="AMR-99", contract_label="NA",
                readiness_label="Technical N/A", applicability="yes", **base,
            )
        )
    # NMWP without a plan action must refuse
    with pytest.raises(CorpusError, match="requires at least one action_id"):
        _assert_row_coherent(
            CorpusRow(
                requirement_id="AMR-3", contract_label="CW",
                readiness_label="Not Met with Plan", applicability="yes",
                organization_responsibility="owner",
                implementation_state="not_met", approval_state="not_required",
            )
        )
    # Met without meets_as_written must refuse
    with pytest.raises(CorpusError, match="readiness Met but"):
        _assert_row_coherent(
            CorpusRow(
                requirement_id="AMR-1", contract_label="CW",
                readiness_label="Met", applicability="yes",
                organization_responsibility="owner",
                implementation_state="not_met", approval_state="not_required",
            )
        )
