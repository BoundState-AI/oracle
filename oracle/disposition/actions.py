#!/usr/bin/env python3
"""
Module: oracle.disposition.actions
Purpose: Stage A — ActionRecord model (structured open actions).

Replaces bare open_actions strings with id, owner, deliverable, exit_criteria,
etc. Supersession by successor records. Event-logged via session.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

LOGGER = logging.getLogger("oracle.disposition.actions")

ActionPriority = Literal["critical", "high", "medium", "low"]


class ActionRecord(BaseModel):
    """Structured gap-closure / open action (Stage A)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)  # e.g. GOV-01
    title: str = Field(min_length=1)
    owner: str = ""
    deliverable: str = ""
    exit_criteria: str = ""
    priority: ActionPriority = "medium"
    due_or_trigger: str = ""
    work_package: str = ""
    affected_unit_ids: tuple[str, ...] = ()
    status: Literal["open", "closed", "superseded"] = "open"
    supersedes: Optional[str] = None  # prior action_id
    note: str = ""

    @field_validator("action_id", "title", mode="before")
    @classmethod
    def _strip_required(cls, v: object) -> str:
        if v is None:
            raise ValueError("required field missing")
        s = str(v).strip()
        if not s:
            raise ValueError("must be non-blank")
        return s

    def is_plan_quality(self) -> bool:
        """True when owner + exit_criteria present (Not Met with Plan floor)."""
        return bool(self.owner.strip()) and bool(self.exit_criteria.strip())


def migrate_string_action(
    text: str,
    *,
    unit_id: str,
    index: int = 0,
) -> ActionRecord:
    """Lift a legacy open_actions string into a minimal ActionRecord."""
    t = (text or "").strip() or "Open action"
    return ActionRecord(
        action_id=f"LEGACY-{unit_id}-{index + 1}",
        title=t[:120],
        owner="",
        deliverable=t,
        exit_criteria="",
        priority="medium",
        affected_unit_ids=(unit_id,),
        note="migrated from open_actions string",
    )
