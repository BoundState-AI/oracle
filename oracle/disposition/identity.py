#!/usr/bin/env python3
"""
Module: oracle.disposition.identity
Purpose: Authenticated actor identity and role/permission model for all
         state transitions and release actions (§1.2, §7.1, §9).

Machine actors remain restricted to "proposed". Unauthorized transitions
are rejected and produce an audit event descriptor for the event log.

S1a is the first disposition slice where release authority is recorded;
therefore this module participates in the tamper-evident audit contract.

Safety Critical: yes — decides and records release authority
__safety_critical__: bool = True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from oracle.disposition.codes import WorkflowStateValue

LOGGER = logging.getLogger("oracle.disposition.identity")

__safety_critical__: bool = True

# Canonical roles for disposition authority.
Role = Literal["proposer", "reviewer", "approver", "admin"]

# Machine identity is a singleton concept for the pure proposer path.
MACHINE_ACTOR_NAME = "machine/proposer"


@dataclass(frozen=True)
class ActorIdentity:
    """
    Authenticated actor for disposition transitions and release actions.

    name: stable human or service identifier (e.g. email or service account).
    roles: zero or more roles from the controlled vocabulary.
    is_machine: True only for automated proposal paths. Machine actors
                may only ever produce "proposed" state.
    """

    name: str
    roles: tuple[Role, ...] = ()
    is_machine: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("ActorIdentity.name must be a non-empty string")
        object.__setattr__(self, "name", self.name.strip())
        # Normalize roles to tuple of known values for fast membership
        if self.roles:
            object.__setattr__(self, "roles", tuple(self.roles))

    @property
    def can_confirm(self) -> bool:
        """Human reviewer or approver can move proposed -> human_confirmed."""
        return not self.is_machine and ("reviewer" in self.roles or "approver" in self.roles or "admin" in self.roles)

    @property
    def can_approve_release(self) -> bool:
        """Only approvers/admins may request release_approved."""
        return not self.is_machine and ("approver" in self.roles or "admin" in self.roles)

    @property
    def can_reject(self) -> bool:
        return not self.is_machine and ("reviewer" in self.roles or "approver" in self.roles or "admin" in self.roles)


def machine_identity() -> ActorIdentity:
    """Return the canonical machine proposer identity (restricted path)."""
    return ActorIdentity(name=MACHINE_ACTOR_NAME, roles=(), is_machine=True)


def is_authorized_transition(
    actor: ActorIdentity,
    current: WorkflowStateValue,
    target: WorkflowStateValue,
) -> tuple[bool, Optional[str]]:
    """
    Return (allowed, reason_if_denied).

    Machine restriction is authoritative and checked first.
    Role requirements are enforced on top of the pure state machine rules.
    """
    if actor.is_machine:
        if target != "proposed":
            return False, f"Machine actor '{actor.name}' may only set state 'proposed'"
        return True, None

    # Human actor
    if target == "human_confirmed":
        if not actor.can_confirm:
            return False, f"Actor '{actor.name}' lacks role to confirm (needs reviewer/approver/admin)"
        return True, None

    if target == "release_approved":
        if not actor.can_approve_release:
            return False, f"Actor '{actor.name}' lacks role to approve release (needs approver/admin)"
        return True, None

    if target == "rejected":
        if not actor.can_reject:
            return False, f"Actor '{actor.name}' lacks role to reject"
        return True, None

    # proposed -> proposed is a no-op for humans (allowed but usually not called)
    if target == "proposed":
        return True, None

    return False, f"Unknown target state {target!r} for authorization"


def require_authorized_transition(
    actor: ActorIdentity,
    current: WorkflowStateValue,
    target: WorkflowStateValue,
) -> None:
    """
    Raise PermissionError (with clear message) if the transition is not authorized.

    The caller (release or transition path) is responsible for turning the
    rejection into an audit event. This function never logs — it only decides.
    """
    allowed, reason = is_authorized_transition(actor, current, target)
    if not allowed:
        raise PermissionError(reason or "Unauthorized transition")


def rejection_event_descriptor(
    actor: ActorIdentity,
    current: WorkflowStateValue,
    target: WorkflowStateValue,
    reason: str,
) -> dict:
    """
    Produce a structured descriptor for an unauthorized-transition audit event.

    The event log will serialize this. It is not itself a transition; it
    records the attempt and denial.
    """
    return {
        "event_type": "transition_rejected",
        "actor": actor.name,
        "is_machine": actor.is_machine,
        "roles": list(actor.roles),
        "from_state": current,
        "to_state": target,
        "reason": reason,
    }
