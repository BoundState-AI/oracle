"""Stage D — library export/import. BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.library import LibraryError, export_library, import_library
from oracle.disposition.session import DispositionSession


def test_library_export_import_assumptions(tmp_path):
    s = DispositionSession(tmp_path / "lib1")
    s.open(actor_name="op")
    s.assert_fact(
        key="hardware.process",
        statement="Cold spray",
        author="op",
        confidence="high",
    )
    s.record_paired_answer("scope.joining_in_crediting", "no", "op")
    s.set_axes(
        "AMR-14",
        actor_name="op",
        enforce_decision=False,
        applicability="yes",
        obligated_actor="producer",
        organization_responsibility="owner",
        implementation_state="not_met",
        approval_state="not_required",
    )
    s.attest_unit(
        "AMR-14",
        actor_name="op",
        role="disposition_author",
        decision="accepted",
    )
    out = tmp_path / "lib.json"
    export_library(s, out)
    assert out.is_file()

    s2 = DispositionSession(tmp_path / "lib2")
    s2.open(actor_name="op2")
    counts = import_library(s2, out, actor_name="op2")
    assert counts["facts"] >= 1
    f = s2.state.facts["hardware.process"]
    assert f.assumed is True
    assert f.confirmed is False
    assert f.owner == "op2"
    assert "scope.joining_in_crediting" in s2.state.paired_answers


def test_library_blocklist_refusal(tmp_path):
    s = DispositionSession(tmp_path / "lib_block")
    s.open(actor_name="op")
    s.assert_fact(
        key="customer.email",
        statement="contact ops@prime.gov for schedule",
        author="op",
        confidence="high",
    )
    with pytest.raises(LibraryError, match="blocklist|identifier"):
        export_library(s, tmp_path / "bad.json")
