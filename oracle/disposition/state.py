#!/usr/bin/env python3
"""
Module: oracle.disposition.state
Purpose: Pure workflow_state machine per §7.1.

Transitions:
  proposed → human_confirmed (human only)
  human_confirmed → release_approved (human only)
  proposed | human_confirmed → rejected (human only)

Machine actors (identified by is_machine_actor) may ONLY set "proposed".
All other transitions require a named human actor string.
Illegal transitions raise ValueError with a clear message.
No persistence; pure functions only.

Safety Critical: advisory-only per spec D-1

__safety_critical__: bool = False  # advisory-only per D-1 (S1 is pure data + state)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from oracle.disposition.codes import WorkflowStateValue

LOGGER = logging.getLogger("oracle.disposition.state")

# WorkflowState is the canonical WorkflowStateValue (single source of truth in codes.py)
WorkflowState = WorkflowStateValue

LEGAL_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    "proposed": {"proposed", "human_confirmed", "rejected"},
    "human_confirmed": {"release_approved", "rejected"},
    "release_approved": set(),  # terminal
    "rejected": set(),  # terminal
}


@dataclass(frozen=True)
class Actor:
    """
    Actor identity for a transition.

    name: human-readable identifier (e.g. "j.wilde@...", "reviewer-3").
    is_machine: True for automated proposal paths. Machine actors may only
                produce "proposed" state; they cannot confirm or approve.
    """

    name: str
    is_machine: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Actor.name must be a non-empty string")
        # Normalize for downstream checks
        object.__setattr__(self, "name", self.name.strip())


def is_machine_actor(actor: Actor) -> bool:
    """Return True if this actor is a machine proposer (restricted path)."""
    return actor.is_machine


def apply_transition(
    current: WorkflowState,
    target: WorkflowState,
    actor: Actor,
) -> WorkflowState:
    """
    Apply a state transition and return the new state.

    Raises ValueError on any illegal transition or actor violation.
    Pure function — no side effects, no I/O.

    Machine actors may only ever produce state "proposed".
    All other states require a named human actor.
    """
    if current not in LEGAL_TRANSITIONS:
        raise ValueError(f"Unknown current state: {current}")

    # Machine restriction is checked first and is authoritative.
    # A machine attempting anything except "proposed" is rejected with a
    # specific error, even if the (current → target) pair would be illegal
    # for other reasons.
    if actor.is_machine and target != "proposed":
        raise ValueError(
            f"Machine actor '{actor.name}' may only set state 'proposed', "
            f"not '{target}'."
        )

    allowed = LEGAL_TRANSITIONS[current]
    if target not in allowed:
        raise ValueError(
            f"Illegal transition: {current} → {target}. "
            f"Allowed from {current}: {sorted(allowed) if allowed else 'none (terminal)'}"
        )

    # Named human required for non-machine paths (Actor construction already
    # enforces non-empty name, but we keep a belt-and-suspenders check).
    if not actor.is_machine:
        if not actor.name or not actor.name.strip():
            raise ValueError("Human actor must supply a non-empty name")

    return target
