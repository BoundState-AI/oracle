#!/usr/bin/env python3
"""
Module: oracle.disposition.review
Purpose: Phase 3 review controls — package assignments, role-bound decisions.

Decisions must also be recorded on the session event log via
DispositionSession.record_review_decision (C3). No silent auto-approval.
No disposition_author exemption from assignment.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from oracle.disposition.session import DispositionSession, UnitAxesState

LOGGER = logging.getLogger("oracle.disposition.review")

Role = Literal[
    "disposition_author",
    "technical_reviewer",
    "quality_reviewer",
    "program_ceo_reviewer",
    "administrator",
    "auditor",
]

ReviewState = Literal[
    "not_reviewed",
    "proposed",
    "in_review",
    "accepted",
    "rejected",
    "superseded",
]


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    assignee: str
    role: Role
    assigned_at: str
    assigned_by: str


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    decision: Literal["accepted", "rejected", "superseded"]
    reviewer: str
    role: Role
    comment: str = ""
    timestamp: str


class ReviewPackage(BaseModel):
    """Package-level review board for a disposition session."""

    model_config = ConfigDict(extra="forbid")

    package_id: str
    session_id: str
    created_at: str
    created_by: str
    assignments: list[Assignment] = Field(default_factory=list)
    decisions: list[ReviewDecision] = Field(default_factory=list)
    unit_review_state: dict[str, ReviewState] = Field(default_factory=dict)

    def assign(
        self,
        unit_id: str,
        assignee: str,
        role: Role,
        assigned_by: str,
    ) -> Assignment:
        if role == "auditor":
            raise ValueError("auditor is read-only; cannot assign as reviewer")
        a = Assignment(
            unit_id=unit_id,
            assignee=assignee,
            role=role,
            assigned_at=_utcnow(),
            assigned_by=assigned_by,
        )
        self.assignments.append(a)
        self.unit_review_state.setdefault(unit_id, "proposed")
        if self.unit_review_state[unit_id] in ("not_reviewed", "proposed"):
            self.unit_review_state[unit_id] = "in_review"
        return a

    def _assignment_for(self, unit_id: str, reviewer: str, role: Role) -> bool:
        """Require matching unit + reviewer name + role (C3)."""
        return any(
            a.unit_id == unit_id and a.assignee == reviewer and a.role == role
            for a in self.assignments
        )

    def decide(
        self,
        unit_id: str,
        *,
        decision: Literal["accepted", "rejected", "superseded"],
        reviewer: str,
        role: Role,
        comment: str = "",
        session: Optional["DispositionSession"] = None,
        unit: Optional["UnitAxesState"] = None,
        accepted_with_tbd: bool = False,
    ) -> ReviewDecision:
        if role == "auditor":
            raise ValueError("auditor cannot accept/reject")
        # C3: no author exemption; role must match assignment
        if not self._assignment_for(unit_id, reviewer, role):
            raise ValueError(
                f"{reviewer!r} is not assigned to {unit_id} as {role}; "
                "refuse unassigned or role-spoofed review"
            )

        # C3: review-coherence at decide() when unit axes available
        u = unit
        if u is None and session is not None and session.state is not None:
            u = session.state.units.get(unit_id)
        if decision == "accepted" and u is not None:
            has_tbd = (
                u.applicability == "tbd"
                or u.organization_responsibility == "tbd"
                or u.implementation_state == "tbd"
                or u.approval_state == "tbd"
            )
            if has_tbd and not (accepted_with_tbd or u.accepted_with_tbd):
                raise ValueError(
                    "review_coherence: accepted requires non-TBD axes or "
                    "accepted_with_tbd election"
                )

        d = ReviewDecision(
            unit_id=unit_id,
            decision=decision,
            reviewer=reviewer,
            role=role,
            comment=comment,
            timestamp=_utcnow(),
        )
        self.decisions.append(d)
        self.unit_review_state[unit_id] = decision  # type: ignore[assignment]

        # C3: bind to hash-chained session log when provided
        if session is not None:
            session.record_review_decision(
                unit_id,
                decision=decision,
                reviewer=reviewer,
                role=role,
                comment=comment,
                accepted_with_tbd=accepted_with_tbd,
            )

        LOGGER.info(
            "Review %s on %s by %s (%s)", decision, unit_id, reviewer, role
        )
        return d

    def is_package_accepted(self, unit_ids: list[str]) -> bool:
        return all(self.unit_review_state.get(u) == "accepted" for u in unit_ids)

    def save(self, path: Path | str) -> None:
        Path(path).write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | str) -> "ReviewPackage":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


def create_review_package(
    session_id: str,
    created_by: str,
    unit_ids: Optional[list[str]] = None,
) -> ReviewPackage:
    return ReviewPackage(
        package_id=f"rp-{session_id[:12]}",
        session_id=session_id,
        created_at=_utcnow(),
        created_by=created_by,
        unit_review_state={u: "proposed" for u in (unit_ids or [])},
    )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
