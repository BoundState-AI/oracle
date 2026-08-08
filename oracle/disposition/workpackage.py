#!/usr/bin/env python3
"""
Module: oracle.disposition.workpackage
Purpose: CR1 — WorkPackageRecord, the engagement Gap-Action-Register shape.

Work packages are first-class records (owner, objective, dependencies,
execution actions, deliverables, evidence, exit criteria, gate) rather
than bare strings — the corpus-replay golden and the implementation
guide's work-package chapters both consume them.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

LOGGER = logging.getLogger("oracle.disposition.workpackage")

WorkPackageStatus = Literal["open", "blocked", "closed", "superseded"]


class WorkPackageRecord(BaseModel):
    """One gap-closure work package (e.g. GOV-01)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wp_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    gate: str = ""  # e.g. "Gate 0 - Governance"
    priority: str = ""  # engagement vocabulary (P0/P1/...)
    status: WorkPackageStatus = "open"
    owner: str = ""
    objective: str = ""
    affected_unit_ids: tuple[str, ...] = ()
    dependencies: str = ""
    execution_actions: str = ""
    deliverables: str = ""
    objective_evidence: str = ""
    exit_criteria: str = ""
    supersedes: Optional[str] = None  # prior wp_id

    @field_validator("wp_id", "title", mode="before")
    @classmethod
    def _strip_required(cls, v: object) -> str:
        if v is None:
            raise ValueError("required field missing")
        s = str(v).strip()
        if not s:
            raise ValueError("must be non-blank")
        return s

    @field_validator("supersedes")
    @classmethod
    def _no_self_supersession(cls, v: Optional[str], info) -> Optional[str]:
        # Atlas CR Medium 5: self-supersession made live and replay
        # disagree about the final status — reject it at the model.
        if v is not None and v == info.data.get("wp_id"):
            raise ValueError("a work package cannot supersede itself")
        return v

    def is_plan_quality(self) -> bool:
        """Owner + exit criteria present — same floor as ActionRecord."""
        return bool(self.owner.strip()) and bool(self.exit_criteria.strip())
