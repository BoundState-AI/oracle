"""Stage E: export truth, banner, phantom-ref refusal. BoundState AI 2026."""

from __future__ import annotations

from pathlib import Path

import pytest

from oracle.disposition.export import (
    ADVISORY_BANNER,
    ExportError,
    build_matrix_rows,
    count_by_export_label,
    export_csv,
    export_docx,
)
from oracle.disposition.rulepack import load_requirement_records
from oracle.disposition.session import DispositionSession, EvidenceRef


def _session_with_rows(tmp_path: Path) -> tuple[DispositionSession, dict]:
    s = DispositionSession(tmp_path / "exp")
    s.open(actor_name="exporter")
    # AMR-14 → Open/Not Met
    s.set_axes(
        "AMR-14",
        actor_name="exporter",
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="not_met",
        approval_state="not_required",
        comment="EFCP not present; control absent.",
        open_actions=("Obtain EFCP / 6033 matrix",),
    )
    # AMR-17 → TBD classification
    s.set_axes(
        "AMR-17",
        actor_name="exporter",
        applicability="tbd",
        applicability_tbd_reason="classification_unresolved",
        organization_responsibility="tbd",
        org_responsibility_tbd_reason="classification_unresolved",
        implementation_state="tbd",
        implementation_tbd_reason="classification_unresolved",
        approval_state="tbd",
        approval_tbd_reason="classification_unresolved",
        comment="Applicability TBD pending classification.",
    )
    s.assert_fact(
        key="ceo.assumed",
        statement="Customer assumed CEO",
        author="exporter",
        assumed=True,
        owner="exporter",
    )
    records_list, _ = load_requirement_records(repin=True)
    records = {r.requirement_id: r for r in records_list}
    return s, records


def test_counts_computed_from_matrix_and_banner(tmp_path):
    s, records = _session_with_rows(tmp_path)
    rows = build_matrix_rows(s, records)
    counts = count_by_export_label(rows)
    assert sum(counts.values()) == len(rows)
    assert counts.get("Open/Not Met", 0) >= 1
    assert counts.get("TBD", 0) >= 1

    path = export_csv(s, records, tmp_path / "m.csv")
    text = path.read_text(encoding="utf-8")
    assert ADVISORY_BANNER in text
    assert "session_id=" in text
    assert "pack_hash=" in text
    assert "counts=" in text


def test_refuse_phantom_artifact_ref(tmp_path):
    s, records = _session_with_rows(tmp_path)
    s.attach_evidence(
        "AMR-14",
        EvidenceRef(doc_id="PHANTOM-DOC", revision="A", note="missing"),
        "exporter",
    )
    with pytest.raises(ExportError, match="nonexistent artifact"):
        build_matrix_rows(s, records, known_artifact_ids=set())


def test_docx_export_and_golden_snapshot(tmp_path):
    s, records = _session_with_rows(tmp_path)
    # Local evidence refs allowed when known set includes (doc_id, revision)
    s.attach_evidence(
        "AMR-14",
        EvidenceRef(doc_id="EFCP-gap", revision="n/a", note="absent"),
        "exporter",
    )
    known = {("EFCP-gap", "n/a")}
    csv_path = export_csv(
        s, records, tmp_path / "golden.csv", known_artifact_ids=known
    )
    docx_path = export_docx(
        s, records, tmp_path / "golden.docx", known_artifact_ids=known
    )
    assert csv_path.is_file()
    assert docx_path.is_file()
    # Golden-ish snapshot: stable labels present
    text = csv_path.read_text(encoding="utf-8")
    assert "AMR-14" in text
    assert "Open/Not Met" in text
    assert "AMR-17" in text
    assert "TBD" in text
    assert "ASSUMPTION" in text
