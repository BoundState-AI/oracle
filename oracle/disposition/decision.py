#!/usr/bin/env python3
"""
Module: oracle.disposition.decision
Purpose: RDW §10.1 deterministic decision rules — allowed states & blockers.

Language models may propose but must not override these blocks.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from oracle.disposition.codes import ExportLabel, TBDReason
from oracle.disposition.export_map import AxisSnapshot, map_axes_to_export_label
from oracle.disposition.graph import DependencyGraph
from oracle.disposition.session import Fact, UnitAxesState

LOGGER = logging.getLogger("oracle.disposition.decision")


@dataclass(frozen=True)
class DecisionResult:
    """Explainable deterministic decision for one unit."""

    unit_id: str
    allowed_export_labels: tuple[str, ...]
    blocked: dict[str, str]  # label -> reason
    current_label: Optional[str]
    blockers_meet: tuple[str, ...]
    requires_approval_action: bool
    open_actions: tuple[str, ...]
    notes: tuple[str, ...] = ()


def _label_allowed(label: ExportLabel, blocked: dict[str, str]) -> bool:
    return label.value not in blocked


def evaluate_unit(
    unit: UnitAxesState,
    *,
    facts: dict[str, Fact],
    graph: Optional[DependencyGraph] = None,
    has_scope_rationale: bool = False,
    has_evidence_for_meet: bool = False,
) -> DecisionResult:
    """
    Compute allowed export labels and explain blockers (FR-009 / §10.1).
    """
    graph = graph or DependencyGraph.from_seeds()
    blocked: dict[str, str] = {}
    notes: list[str] = []
    actions: list[str] = []
    meet_blockers: list[str] = []

    # --- §10.1 rules ---
    # TBD when unresolved customer/program input
    class_fact = facts.get("classification.primary")
    class_unresolved = class_fact is None or (
        class_fact.assumed and not class_fact.confirmed
    )

    # N/A requires positive rationale
    if unit.applicability == "no" and not has_scope_rationale and not unit.comment:
        # still allow N/A if axes already No — comment should carry rationale
        notes.append("N/A should cite scope/trigger rationale in comment or scope_citation")

    # Dependency / classification gates
    for edge in graph.prerequisites_of(unit.unit_id):
        if edge.fact_key:
            f = facts.get(edge.fact_key)
            if f is None or (f.assumed and not f.confirmed):
                meet_blockers.append(
                    f"prerequisite fact {edge.fact_key} unresolved ({edge.note})"
                )
                blocked[ExportLabel.MEET.value] = (
                    blocked.get(ExportLabel.MEET.value)
                    or f"unresolved fact {edge.fact_key}"
                )
                blocked[ExportLabel.NA.value] = (
                    blocked.get(ExportLabel.NA.value)
                    or f"class/plan fact {edge.fact_key} unresolved — cannot force N/A"
                )

    class_gated = any(
        e.fact_key == "classification.primary"
        for e in graph.prerequisites_of(unit.unit_id)
    )
    if class_unresolved and class_gated:
        meet_blockers.append("classification_unresolved")
        blocked[ExportLabel.MEET.value] = "classification_unresolved"
        blocked[ExportLabel.MEETS_INTENT.value] = "classification_unresolved"
        notes.append("Render TBD(classification_unresolved) until class inputs arrive")

    # EFCP / AMR-14
    efcp = facts.get("plan.EFCP")
    if unit.unit_id in {"AMR-14", "EFCR-1", "EFCR-2"} and (
        efcp is None or not efcp.confirmed
    ):
        if unit.applicability == "yes" or unit.applicability == "tbd":
            notes.append("EFCP absent → Open/Not Met when applicability established")
            if unit.applicability == "yes" and unit.implementation_state == "not_met":
                actions.append("Obtain EFCP / mapped 6033 control set")

    # AMCP / AMR-2 — cannot satisfy by supplier matrix alone
    amcp = facts.get("plan.AMCP")
    if unit.unit_id == "AMR-2" and (amcp is None or not amcp.confirmed):
        blocked[ExportLabel.MEET.value] = "no approved AMCP present"
        meet_blockers.append("AMCP not observed — supplier matrix cannot close AMR-2")
        actions.append("Obtain approved AMCP (identity/revision/approver/date/scope)")

    # External responsibility never forces N/A
    if unit.organization_responsibility == "external":
        if unit.applicability == "no" and not has_scope_rationale:
            notes.append(
                "External responsibility alone is not N/A; store states separately"
            )

    # Meets Intent / alternate requires approval action
    requires_approval = False
    if unit.implementation_state == "alternate_proposed":
        requires_approval = True
        if unit.approval_state in ("not_required",):
            actions.append(
                "Create tailoring/exception approval action (alternate changes as-written)"
            )
            requires_approval = True
        notes.append("Meets Intent must not render under compliance heading")

    if unit.implementation_state == "not_met" and unit.approval_state in (
        "required",
        "draft",
        "submitted",
    ):
        requires_approval = True
        actions.append("Track exception/relief approval separately from implementation")

    # Hard evidence gate for Meet when applicability is established (FR-009 / C1)
    if unit.implementation_state == "meets_as_written" and unit.applicability == "yes":
        if not has_evidence_for_meet:
            meet_blockers.append("Meet requires at least one qualifying evidence reference")
            blocked[ExportLabel.MEET.value] = "no qualifying evidence for Meet"
            notes.append("Evidence gate HARD: Meet blocked without evidence")

    # N/A without scope rationale is blocked (C1 UNSUPPORTED_NA)
    if unit.applicability == "no":
        rationale = has_scope_rationale or bool(
            getattr(unit, "scope_citation", None)
            or (unit.comment and "scope" in (unit.comment or "").lower())
        )
        if not rationale:
            blocked[ExportLabel.NA.value] = (
                "N/A requires positive scope/trigger rationale (scope_citation or comment)"
            )

    # Axis mapping
    try:
        current = map_axes_to_export_label(unit.snapshot())
        current_s = current.value
    except Exception as e:
        current_s = None
        notes.append(f"axes unmapped: {e}")

    # If mapped label is blocked, it is not current-allowed
    if current_s and current_s in blocked:
        notes.append(f"current mapped label {current_s!r} is blocked: {blocked[current_s]}")

    # Allowed = all labels not blocked, plus always TBD if facts open
    all_labels = [lab.value for lab in ExportLabel]
    allowed = tuple(lab for lab in all_labels if lab not in blocked)

    # Force TBD preference when classification fact gates this unit (graph-driven, M6)
    class_gated = any(
        e.fact_key == "classification.primary"
        for e in graph.prerequisites_of(unit.unit_id)
    )
    if class_unresolved and class_gated:
        if ExportLabel.TBD.value not in allowed:
            allowed = allowed + (ExportLabel.TBD.value,)
        blocked.setdefault(ExportLabel.MEET.value, "classification_unresolved")
        blocked.setdefault(ExportLabel.MEETS_INTENT.value, "classification_unresolved")

    # Axis-level Meet blockers
    if unit.applicability != "yes":
        meet_blockers.append(f"applicability is {unit.applicability}")
    if unit.implementation_state != "meets_as_written":
        meet_blockers.append(
            f"implementation is {unit.implementation_state}, not meets_as_written"
        )
    if unit.approval_state not in ("not_required", "approved"):
        meet_blockers.append(f"approval is {unit.approval_state}")

    return DecisionResult(
        unit_id=unit.unit_id,
        allowed_export_labels=allowed,
        blocked=blocked,
        current_label=current_s,
        blockers_meet=tuple(dict.fromkeys(meet_blockers)),
        requires_approval_action=requires_approval,
        open_actions=tuple(dict.fromkeys(actions + list(unit.open_actions))),
        notes=tuple(notes),
    )


def apply_classification_tbd(unit_id: str) -> dict:
    """Axis fields for classification_unresolved landing (AC #5)."""
    r = TBDReason.CLASSIFICATION_UNRESOLVED
    return {
        "applicability": "tbd",
        "applicability_tbd_reason": r,
        "organization_responsibility": "tbd",
        "org_responsibility_tbd_reason": r,
        "implementation_state": "tbd",
        "implementation_tbd_reason": r,
        "approval_state": "tbd",
        "approval_tbd_reason": r,
    }


def apply_open_not_met_control_absent() -> dict:
    """Axes for Open/Not Met when control/evidence absent (AC #6 AMR-14)."""
    return {
        "applicability": "yes",
        "obligated_actor": "producer",
        "organization_responsibility": "owner",
        "implementation_state": "not_met",
        "approval_state": "not_required",
    }
