"""Review gate C1/C2/H1 probes — enforcement on product path. BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.export import ExportError, build_matrix_rows
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.session import DispositionSession, SessionError


def test_c1_refuse_meet_without_evidence_and_export(tmp_path):
    s = DispositionSession(tmp_path / "c1")
    s.open(actor_name="op", multi_pack=False)
    # Seed AMCP fact so AMCP block is not the only reason
    s.assert_fact(key="plan.AMCP", statement="AMCP present", author="op", confidence="high")
    with pytest.raises(SessionError, match="evidence|blocked|Meet"):
        s.set_axes(
            "AMR-45",
            actor_name="op",
            applicability="yes",
            obligated_actor="producer",
            organization_responsibility="owner",
            implementation_state="meets_as_written",
            approval_state="not_required",
        )


def test_c1_refuse_unsupported_na_and_bad_comment(tmp_path):
    s = DispositionSession(tmp_path / "c1b")
    s.open(actor_name="op", multi_pack=False)
    with pytest.raises(SessionError, match="blocked|N/A|scope"):
        s.set_axes(
            "AMR-52",
            actor_name="op",
            applicability="no",
            implementation_state="not_reached",
            organization_responsibility="external",
            approval_state="not_required",
            # no scope_citation
        )
    # With scope citation, N/A allowed
    s.set_axes(
        "AMR-52",
        actor_name="op",
        applicability="no",
        implementation_state="not_reached",
        organization_responsibility="external",
        approval_state="not_required",
        scope_citation="polymer section out of scope",
    )
    with pytest.raises(SessionError, match="13.2|prohibited"):
        s.set_axes(
            "AMR-52",
            actor_name="op",
            comment="The supplier is compliant and complete.",
            election=False,
        )


def test_h1_inferred_requires_confirmation(tmp_path):
    s = DispositionSession(tmp_path / "h1")
    s.open(actor_name="op", multi_pack=False)
    with pytest.raises(SessionError, match="Inferred"):
        s.assert_fact(
            key="derived.x",
            statement="inferred thing",
            author="op",
            kind="inferred",
        )
    f = s.assert_fact(
        key="derived.x",
        statement="inferred thing",
        author="op",
        kind="inferred",
        confirm_assumption=True,
    )
    assert f.confirmed is True
