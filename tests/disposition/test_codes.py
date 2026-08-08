"""Tests for oracle.disposition.codes. BoundState AI 2026.

Lightweight header per repo convention for test modules.
"""

from __future__ import annotations

import pytest

from oracle.disposition.codes import (
    DISPOSITION_CODES,
    OPEN_SUBREASONS,
    DispositionCode,
    OPENSubReason,
)


def test_disposition_code_enum_is_closed():
    """Only the five named codes exist; construction of unknown is impossible."""
    assert set(DispositionCode) == {
        DispositionCode.CW,
        DispositionCode.MI,
        DispositionCode.EX,
        DispositionCode.NA,
        DispositionCode.OPEN,
    }
    # String values are the canonical codes
    assert {c.value for c in DispositionCode} == {"CW", "MI", "EX", "NA", "OPEN"}
    assert DISPOSITION_CODES == {"CW", "MI", "EX", "NA", "OPEN"}


def test_open_subreason_enum_is_closed():
    """§2.3 vocabulary is closed; unknown sub-reasons are impossible."""
    expected = {
        "evidence_absent",
        "scope_decision_not_made",
        "customer_input_missing",
        "authority_unidentified",
        "approval_not_exercised",
        "referenced_artifact_missing",
        "referenced_standard_unavailable",
        "reference_semantics_unresolved",
        "dependency_eliminated",
        "classification_unresolved",
    }
    assert {r.value for r in OPENSubReason} == expected
    assert OPEN_SUBREASONS == expected


def test_unknown_code_or_subreason_impossible():
    """Pydantic + enum construction prevents unknown values."""
    with pytest.raises(ValueError):
        DispositionCode("FOO")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        OPENSubReason("not_a_reason")  # type: ignore[arg-type]
