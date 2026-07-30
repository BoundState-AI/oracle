"""
RDW §7.1 export truth table — every reachable axis combination maps to
exactly one export label or one named contradiction.

BoundState AI 2026.
"""

from __future__ import annotations

import itertools

import pytest

from oracle.disposition.codes import ExportLabel, TBDReason
from oracle.disposition.export_map import (
    AxisContradiction,
    AxisSnapshot,
    export_label_to_code,
    map_axes_to_export_label,
)


APPLICABILITY = ("yes", "no", "tbd")
ORG = ("owner", "support", "external", "tbd")
IMPL = (
    "meets_as_written",
    "alternate_proposed",
    "partial",
    "not_met",
    "tbd",
    "not_reached",
)
APPR = (
    "not_required",
    "required",
    "draft",
    "submitted",
    "approved",
    "rejected",
    "tbd",
)
ACTORS = ("program", "ceo", "producer", "supplier", "subtier", "other", None)


def _snap(
    app: str,
    org: str,
    impl: str,
    appr: str,
    actor: str | None = "producer",
) -> AxisSnapshot:
    reason = TBDReason.EVIDENCE_ABSENT
    return AxisSnapshot(
        applicability=app,  # type: ignore[arg-type]
        obligated_actor=actor,  # type: ignore[arg-type]
        organization_responsibility=org,  # type: ignore[arg-type]
        implementation_state=impl,  # type: ignore[arg-type]
        approval_state=appr,  # type: ignore[arg-type]
        applicability_tbd_reason=reason if app == "tbd" else None,
        org_responsibility_tbd_reason=reason if org == "tbd" else None,
        implementation_tbd_reason=reason if impl == "tbd" else None,
        approval_tbd_reason=reason if appr == "tbd" else None,
    )


def test_exhaustive_axis_combinations_map_or_named_contradiction():
    """Every combination yields exactly one ExportLabel or AxisContradiction.name."""
    results: dict[str, int] = {}
    contradictions: dict[str, int] = {}
    for app, org, impl, appr in itertools.product(APPLICABILITY, ORG, IMPL, APPR):
        actor = "producer" if app == "yes" and org == "owner" else (
            None if app == "no" else "producer"
        )
        snap = _snap(app, org, impl, appr, actor=actor)
        try:
            label = map_axes_to_export_label(snap)
            assert isinstance(label, ExportLabel)
            results[label.value] = results.get(label.value, 0) + 1
        except AxisContradiction as e:
            contradictions[e.name] = contradictions.get(e.name, 0) + 1

    # All six labels must appear at least once
    for lab in ExportLabel:
        assert lab.value in results, f"label {lab.value} never produced"

    # Named contradictions only (closed set of gate names)
    allowed_contra = {
        "applicability_coherence",
        "tbd_validity",
        "actor_coherence",
        "export_coherence",
        "approval_coherence",
        "review_coherence",
    }
    for name in contradictions:
        assert name in allowed_contra, f"unexpected contradiction name {name}"

    assert sum(results.values()) + sum(contradictions.values()) == (
        len(APPLICABILITY) * len(ORG) * len(IMPL) * len(APPR)
    )


def test_canonical_label_examples():
    """Spot-check the §7.1 table rows."""
    meet = _snap("yes", "owner", "meets_as_written", "not_required")
    assert map_axes_to_export_label(meet) == ExportLabel.MEET

    mi = _snap("yes", "owner", "alternate_proposed", "required")
    assert map_axes_to_export_label(mi) == ExportLabel.MEETS_INTENT

    na = _snap("no", "external", "not_reached", "not_required", actor=None)
    assert map_axes_to_export_label(na) == ExportLabel.NA

    tbd = _snap("tbd", "tbd", "tbd", "tbd", actor=None)
    assert map_axes_to_export_label(tbd) == ExportLabel.TBD

    onm = _snap("yes", "owner", "not_met", "not_required")
    assert map_axes_to_export_label(onm) == ExportLabel.OPEN_NOT_MET

    ex = _snap("yes", "owner", "not_met", "required")
    assert map_axes_to_export_label(ex) == ExportLabel.EXCEPTION


def test_c2_rejected_and_partial_do_not_leak_compliance():
    """Review C2: four cells must not export as Meets Intent / live Exception."""
    # alternate_proposed + rejected → Open/Not Met
    assert (
        map_axes_to_export_label(
            _snap("yes", "owner", "alternate_proposed", "rejected")
        )
        == ExportLabel.OPEN_NOT_MET
    )
    # partial + rejected → Open/Not Met
    assert (
        map_axes_to_export_label(_snap("yes", "owner", "partial", "rejected"))
        == ExportLabel.OPEN_NOT_MET
    )
    # not_met + rejected → Open/Not Met
    assert (
        map_axes_to_export_label(_snap("yes", "owner", "not_met", "rejected"))
        == ExportLabel.OPEN_NOT_MET
    )
    # partial + approved → Open/Not Met (not Meets Intent)
    assert (
        map_axes_to_export_label(_snap("yes", "owner", "partial", "approved"))
        == ExportLabel.OPEN_NOT_MET
    )
    # AC-3 AMR-1 shape: external + not_met + required → Open/Not Met
    assert (
        map_axes_to_export_label(
            _snap("yes", "external", "not_met", "required", actor="program")
        )
        == ExportLabel.OPEN_NOT_MET
    )


def test_no_exception_softening_to_meet():
    """Guard 1: not_met + relief path never maps to Meet or Meets Intent as Meet."""
    ex = _snap("yes", "owner", "not_met", "required")
    label = map_axes_to_export_label(ex)
    assert label == ExportLabel.EXCEPTION
    assert export_label_to_code(label).value == "EX"


def test_applicability_no_plus_meets_is_contradiction():
    snap = _snap("no", "external", "meets_as_written", "not_required", actor=None)
    with pytest.raises(AxisContradiction) as ei:
        map_axes_to_export_label(snap)
    assert ei.value.name == "applicability_coherence"


def test_five_code_collapse_of_open_not_met():
    onm = map_axes_to_export_label(_snap("yes", "owner", "not_met", "not_required"))
    assert export_label_to_code(onm).value == "OPEN"
    tbd = map_axes_to_export_label(_snap("tbd", "tbd", "tbd", "tbd", actor=None))
    assert export_label_to_code(tbd).value == "OPEN"
    # Labels still distinguish
    assert onm != tbd
