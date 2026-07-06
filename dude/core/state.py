#!/usr/bin/env python3
"""
Module: dude.core.state
Purpose: The case lifecycle state machine (spec v0.1 §10, mechanized per
         review A15).

v0.1 had states but no machine. This module is the machine: an explicit
transition table with named events; anything not in the table raises.
WAITING_FOR_DATA is not a stored state — it is computed from the gate
(waiting_for_data()), so there is exactly one source of truth. REOPENED
is an edge (reopening moves a finished case back to ACTIVE), not a state.

Safety Critical: False
Psychologically Critical: True — a stale stored "waiting" status over
real new evidence is review A15's failure.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging
from enum import Enum

from dude.data.enums import CaseStatus, GateMode

LOGGER = logging.getLogger("dude.core.state")


class CaseEvent(str, Enum):
    """Named lifecycle events — the only way a case changes status."""

    ANALYSIS_PERSISTED = "analysis_persisted"
    DECISION_RECORDED = "decision_recorded"
    USER_RESOLVED = "user_resolved"
    USER_ARCHIVED = "user_archived"
    REOPENED = "reopened"


class InvalidTransition(Exception):
    """Raised for any (status, event) pair not in the table. Callers
    surface this as a refusal — never swallow it into a silent no-op."""


# (current status, event) -> next status. Absence means invalid.
_TRANSITIONS: dict[tuple[CaseStatus, CaseEvent], CaseStatus] = {
    (CaseStatus.UNSTRUCTURED, CaseEvent.ANALYSIS_PERSISTED): CaseStatus.ACTIVE,
    (CaseStatus.STRUCTURED, CaseEvent.ANALYSIS_PERSISTED): CaseStatus.ACTIVE,
    (CaseStatus.ACTIVE, CaseEvent.ANALYSIS_PERSISTED): CaseStatus.ACTIVE,
    (CaseStatus.ACTION_SELECTED, CaseEvent.ANALYSIS_PERSISTED): CaseStatus.ACTION_SELECTED,
    (CaseStatus.ACTIVE, CaseEvent.DECISION_RECORDED): CaseStatus.ACTION_SELECTED,
    (CaseStatus.ACTION_SELECTED, CaseEvent.DECISION_RECORDED): CaseStatus.ACTION_SELECTED,
    (CaseStatus.ACTIVE, CaseEvent.USER_RESOLVED): CaseStatus.RESOLVED,
    (CaseStatus.ACTION_SELECTED, CaseEvent.USER_RESOLVED): CaseStatus.RESOLVED,
    (CaseStatus.RESOLVED, CaseEvent.USER_ARCHIVED): CaseStatus.ARCHIVED,
    (CaseStatus.RESOLVED, CaseEvent.REOPENED): CaseStatus.ACTIVE,
    (CaseStatus.ARCHIVED, CaseEvent.REOPENED): CaseStatus.ACTIVE,
}


def transition(status: CaseStatus, event: CaseEvent) -> CaseStatus:
    """Apply one lifecycle event. Raises InvalidTransition otherwise."""
    key = (status, event)
    if key not in _TRANSITIONS:
        raise InvalidTransition(
            f"Event {event.value!r} is not valid from status {status.value!r}."
        )
    nxt = _TRANSITIONS[key]
    if nxt is not status:
        LOGGER.info("Case status %s -> %s on %s", status.value, nxt.value, event.value)
    return nxt


def waiting_for_data(mode: GateMode) -> bool:
    """The computed WAITING_FOR_DATA view (review A15: never stored)."""
    return mode is GateMode.NO_NEW_DATA
