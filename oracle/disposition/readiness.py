#!/usr/bin/env python3
"""
Module: oracle.disposition.readiness
Purpose: Stage A — readiness derived view (§7.1-style, never SoR).

Maps axes + ActionRecords + not_yet_due → readiness labels. Exhaustive
truth-table discipline matches export_map.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Iterable, Optional

from pydantic import BaseModel, ConfigDict

from oracle.disposition.actions import ActionRecord
from oracle.disposition.session import UnitAxesState

LOGGER = logging.getLogger("oracle.disposition.readiness")


class ReadinessLabel(str, Enum):
    MET = "Met"
    NOT_MET_WITH_PLAN = "Not Met with Plan"
    TBD_VERIFY = "TBD Verify"
    EXTERNAL_ACTION = "External Action"
    NOT_YET_DUE = "Not Yet Due"
    TECHNICAL_NA = "Technical N/A"


class ReadinessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    label: ReadinessLabel
    reasons: tuple[str, ...] = ()


def _open_actions(actions: Iterable[ActionRecord], unit_id: str) -> list[ActionRecord]:
    out = []
    for a in actions:
        if a.status != "open":
            continue
        if unit_id in a.affected_unit_ids or not a.affected_unit_ids:
            out.append(a)
    return out


def map_readiness(
    unit: UnitAxesState,
    actions: Iterable[ActionRecord] = (),
    *,
    has_qualifying_evidence: bool = False,
) -> ReadinessResult:
    """
    Derived readiness label (never system of record).

    Priority order (first match wins):
      1. Not Yet Due — marker + justification
      2. Technical N/A — applicability no + scope_citation
      3. TBD Verify — any TBD axis
      4. External Action — org external + open action
      5. Met — meets_as_written + qualifying evidence (+ not external-only gap)
      6. Not Met with Plan — not_met/partial + plan-quality open action
      7. Fallback TBD Verify when incomplete plan / residual open
    """
    uid = unit.unit_id
    reasons: list[str] = []
    open_acts = _open_actions(actions, uid)
    plan_acts = [a for a in open_acts if a.is_plan_quality()]

    # 1. Not Yet Due
    if getattr(unit, "not_yet_due", False):
        just = (getattr(unit, "not_yet_due_justification", None) or "").strip()
        if just:
            return ReadinessResult(
                unit_id=uid,
                label=ReadinessLabel.NOT_YET_DUE,
                reasons=(just,),
            )
        reasons.append("not_yet_due set without justification — treated as TBD")

    # 2. Technical N/A
    if unit.applicability == "no" and unit.scope_citation:
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.TECHNICAL_NA,
            reasons=(f"scope_citation={unit.scope_citation}",),
        )

    # 3. TBD Verify — any unresolved axis (execution is the split-model
    # input; the legacy implementation view no longer decides anything)
    tbd_bits = []
    if unit.applicability == "tbd":
        tbd_bits.append(f"applicability:{unit.applicability_tbd_reason}")
    if unit.organization_responsibility == "tbd":
        tbd_bits.append(f"org:{unit.org_responsibility_tbd_reason}")
    if unit.execution_state == "tbd":
        tbd_bits.append(f"execution:{unit.implementation_tbd_reason}")
    if unit.approval_state == "tbd":
        tbd_bits.append(f"appr:{unit.approval_tbd_reason}")
    if tbd_bits:
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.TBD_VERIFY,
            reasons=tuple(tbd_bits),
        )

    # 4. External Action
    if unit.organization_responsibility == "external" and open_acts:
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.EXTERNAL_ACTION,
            reasons=tuple(a.action_id for a in open_acts),
        )

    # 4b. Support on a program/CEO obligation with tracked work is
    # externally-owned action we assist (AMR-113 anchor — model split).
    if (
        unit.organization_responsibility == "support"
        and unit.obligated_actor in ("program", "ceo")
        and open_acts
    ):
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.EXTERNAL_ACTION,
            reasons=tuple(a.action_id for a in open_acts),
        )

    # 5. Met — execution evidenced/verified with qualifying evidence
    if (
        unit.execution_state in ("evidenced", "verified")
        and unit.applicability == "yes"
        and has_qualifying_evidence
    ):
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.MET,
            reasons=(f"execution {unit.execution_state} + qualifying evidence",),
        )

    # 6. Not Met with Plan — applicable work not started/partial + a plan
    if (
        unit.applicability == "yes"
        and unit.execution_state in ("not_started", "partial")
        and plan_acts
    ):
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.NOT_MET_WITH_PLAN,
            reasons=tuple(
                f"{a.action_id}:{a.owner}" for a in plan_acts
            ),
        )

    # External without open action still external-leaning when org is external
    if unit.organization_responsibility == "external":
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.EXTERNAL_ACTION,
            reasons=("org_responsibility=external; no open action yet",),
        )

    # Claimed/evidenced without qualifying evidence → TBD Verify
    if unit.execution_state in ("implemented", "evidenced", "verified"):
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.TBD_VERIFY,
            reasons=(f"execution {unit.execution_state} pending qualifying evidence",),
        )

    # not started/partial without plan-quality action (AF2 floor)
    if unit.execution_state in ("not_started", "partial"):
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.TBD_VERIFY,
            reasons=(
                (
                    "open actions lack owner+exit_criteria (plan-quality floor)"
                    if open_acts
                    else "execution not started without open ActionRecord"
                ),
            ),
        )

    # N/A without citation already handled; bare no without citation
    if unit.applicability == "no":
        return ReadinessResult(
            unit_id=uid,
            label=ReadinessLabel.TBD_VERIFY,
            reasons=("applicability=no without scope_citation",),
        )

    return ReadinessResult(
        unit_id=uid,
        label=ReadinessLabel.TBD_VERIFY,
        reasons=tuple(reasons) or ("residual open axes",),
    )


def readiness_counts(
    results: Iterable[ReadinessResult],
) -> dict[str, int]:
    counts = {lab.value: 0 for lab in ReadinessLabel}
    for r in results:
        counts[r.label.value] = counts.get(r.label.value, 0) + 1
    return counts
