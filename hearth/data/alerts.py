#!/usr/bin/env python3
"""
Module: hearth.data.alerts
Purpose: PropertyAlert — landmine scan output, evidence-first (spec v0.3
         §2.2 landmine rules, §6; §13 P2-D).

A PropertyAlert is what a data_query landmine rule produces when evaluated
against the evidence store. Three statuses, none of them silence:
  alert                  threshold matched; severity says how loudly
  clear                  evidence present, below every threshold
  insufficient_evidence  the rule could not be evaluated — surfaced, never
                         assumed clear (§3.1 minimum-evidence gate)

Every alert embeds the PropertyEvidence rows it rests on (§6: every number
cites a row; every row cites a source).

Safety Critical: False
Financially Critical: False (contract definition; the scan engine that
  emits these is the financially-critical decider)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

from typing import Literal

from pydantic import Field, model_validator

from hearth.data.base import HearthModel
from hearth.data.property import PropertyEvidence

AlertStatus = Literal["alert", "clear", "insufficient_evidence"]
AlertSeverity = Literal["info", "warn", "flag"]


class PropertyAlert(HearthModel):
    """One landmine rule's verdict for one property (§13 P2-D)."""

    property_uid: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    category: Literal["landmine"] = "landmine"
    status: AlertStatus
    severity: AlertSeverity | None = None
    summary: str
    analysis: str
    evidence: list[PropertyEvidence]
    requires_human_review: Literal[True] = True

    @model_validator(mode="after")
    def _severity_iff_alert(self) -> "PropertyAlert":
        # WHY: a severity on a non-alert would let "clear" rows masquerade
        # as findings in sorted views; an alert without severity is mute.
        if self.status == "alert" and self.severity is None:
            raise ValueError(f"alert for {self.rule_id} requires a severity")
        if self.status != "alert" and self.severity is not None:
            raise ValueError(f"{self.status} for {self.rule_id} must not carry severity")
        return self
