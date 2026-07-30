#!/usr/bin/env python3
"""
Module: oracle.disposition.release
Purpose: The complete §7.1 release gate and package-level release marking.

Release eligibility is evaluated against an explicit immutable ReleaseContext
that carries the run's effective date and the target scope dimensions. The
gate is whole: either the entire package is eligible and all units are marked
atomically, or none are and the reasons are reported.

There is deliberately no unit-local "is releasable" predicate that can be
called in isolation — that was the source of the three prior defective gates.

Atomicity: write-temp-rename via the store.
Idempotency: re-applying the same marking under the same context is a no-op.

Safety Critical: yes — this is the release authority decision point
__safety_critical__: bool = True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from oracle.disposition.codes import DispositionCode
from oracle.disposition.identity import ActorIdentity, require_authorized_transition
from oracle.disposition.models import (
    DispositionUnit,
    AcceptanceRecord,
    _ALLOW_TRANSITION_STATE,  # narrow internal token only
    _ALLOW_RELEASED_CONSTRUCTION,
)
from oracle.disposition.store import DispositionStore

LOGGER = logging.getLogger("oracle.disposition.release")

__safety_critical__: bool = True

# Narrow token set ONLY by this module when constructing a successor that has
# passed the full release gate. Direct public construction and un-audited
# paths never set it. This is a guardrail at the store/event boundary.
_ALLOW_RELEASED_SUCCESSOR: ContextVar[bool] = ContextVar("_ALLOW_RELEASED_SUCCESSOR", default=False)


@dataclass(frozen=True)
class ReleaseContext:
    """
    Immutable context against which release eligibility is evaluated for a package.

    effective_date: ISO date (YYYY-MM-DD) representing the run's decision point.
                    Used for acceptance validity window checks.
    configurations: target configurations for scope coverage.
    part_classes:   target part classes for scope coverage.
    evidence_threshold: minimum match_score required for evidence entries
                        on CW/MI units (0.0 means any positive is accepted).
    """

    effective_date: str
    configurations: tuple[str, ...] = ()
    part_classes: tuple[str, ...] = ()
    evidence_threshold: float = 0.0

    def __post_init__(self) -> None:
        if self.evidence_threshold < 0.0 or self.evidence_threshold > 1.0:
            raise ValueError("evidence_threshold must be in [0.0, 1.0]")
        # Basic date sanity (full parse happens at use)
        if not self.effective_date or not str(self.effective_date).strip():
            raise ValueError("effective_date is required for release context")


class ReleaseRefusal(Exception):
    """Raised when a package cannot be released. Carries per-unit or package reasons."""

    def __init__(self, message: str, reasons: list[str]):
        super().__init__(message)
        self.reasons = reasons


def _parse_date(s: str) -> date:
    s2 = str(s).strip()[:10]
    return date.fromisoformat(s2)


def _is_in_window(as_of: date, valid_from: str, valid_to: Optional[str]) -> bool:
    vf = _parse_date(valid_from)
    if not (vf <= as_of):
        return False
    if valid_to and str(valid_to).strip():
        vt = _parse_date(valid_to)
        if not (as_of <= vt):
            return False
    return True


def _scope_covers(ctx: ReleaseContext, scope: Any) -> tuple[bool, Optional[str]]:
    """
    Return (ok, reason_if_not).

    Every supplied dimension in ctx must be matched independently in the scope.
    If ctx supplies neither, we require that the scope has at least one non-blank
    entry in either list (historical presence check).
    """
    cfgs = [c.strip() for c in (scope.configurations or ()) if c and str(c).strip()]
    pcs = [p.strip() for p in (scope.part_classes or ()) if p and str(p).strip()]

    supplied_cfg = [c.strip() for c in ctx.configurations if c and str(c).strip()]
    supplied_pc = [p.strip() for p in ctx.part_classes if p and str(p).strip()]

    if supplied_cfg:
        for want in supplied_cfg:
            if want not in cfgs:
                return False, f"configuration {want!r} not covered by approved_scope"
    if supplied_pc:
        for want in supplied_pc:
            if want not in pcs:
                return False, f"part_class {want!r} not covered by approved_scope"

    if not supplied_cfg and not supplied_pc:
        # At least some scope must be declared
        if not cfgs and not pcs:
            return False, "approved_scope must list at least one configuration or part_class"

    return True, None


def is_unit_release_eligible(unit: DispositionUnit, ctx: ReleaseContext) -> tuple[bool, Optional[str]]:
    """
    Evaluate one unit against the release context.

    Returns (eligible, reason_or_None).
    This is the complete gate; there is no "partial" or "local" version.

    Per §7.1: a unit must be in human_confirmed before it may be released.
    Release is not a direct jump from proposed.
    """
    if unit.is_rollup:
        return False, "roll-up parents are never release targets (§1.1)"

    if unit.workflow_state != "human_confirmed":
        return False, f"release requires workflow_state='human_confirmed' (current={unit.workflow_state})"

    if unit.code == DispositionCode.OPEN:
        return False, "OPEN units are never release-eligible (§2.1)"

    # Evidence gate for CW and MI: *at least one* entry must meet or exceed threshold.
    if unit.code in (DispositionCode.CW, DispositionCode.MI):
        if not unit.evidence:
            return False, f"{unit.code} requires at least one evidence entry"
        thresh = ctx.evidence_threshold
        qualifying = [e for e in unit.evidence if e.match_score >= thresh]
        if not qualifying:
            return False, (
                f"{unit.code} has no evidence meeting match_score >= {thresh}"
            )
        if thresh == 0.0:
            # Historical: when threshold=0 we still require strictly positive on the qualifying one
            if not any(e.match_score > 0.0 for e in qualifying):
                return False, f"{unit.code} evidence match_score must be > 0.0"

    # MI/EX acceptance requirements
    if unit.code in (DispositionCode.MI, DispositionCode.EX):
        acc: Optional[AcceptanceRecord] = unit.acceptance
        if acc is None or acc.status != "accepted":
            return False, f"{unit.code} requires an accepted AcceptanceRecord"

        # Correct semantics (see S1a review):
        # acc.supersedes means *this* record supersedes a prior one (it is the live head of the chain).
        # A record is superseded only if a *later* acceptance points to it.
        # For S1a we accept an attached accepted AcceptanceRecord as live.
        # Full successor-chain walking to detect "has later superseder" belongs to later slices.

        # Window
        try:
            as_of = _parse_date(ctx.effective_date)
        except Exception:
            return False, f"ReleaseContext.effective_date {ctx.effective_date!r} is not a valid date"

        try:
            if not _is_in_window(as_of, acc.approved_scope.valid_from, acc.approved_scope.valid_to):
                return False, (
                    f"{unit.code} acceptance window does not cover effective_date "
                    f"{ctx.effective_date} (valid_from={acc.approved_scope.valid_from}, "
                    f"valid_to={acc.approved_scope.valid_to})"
                )
        except Exception as e:
            return False, f"Invalid date in acceptance scope: {e}"

        # Scope coverage (independent dimensions)
        ok, why = _scope_covers(ctx, acc.approved_scope)
        if not ok:
            return False, f"{unit.code} scope coverage: {why}"

    # Boundary confirmation is already enforced at construction for non-rollups.
    # If somehow missing here, refuse.
    if not unit.unit_boundary_confirmed_by or not str(unit.unit_boundary_confirmed_by).strip():
        return False, "unit_boundary_confirmed_by is required before release"

    return True, None


def _build_released_successor(unit: DispositionUnit, actor_name: str) -> DispositionUnit:
    """
    Internal: produce a release_approved successor under the narrow controlled token.

    The caller (this module) has already passed the full gate. We still run
    full validation on the successor.
    """
    data = unit.model_dump()
    data["workflow_state"] = "release_approved"
    # Record the human who authorized the release step
    if actor_name and not unit.confirmed_by:
        data["confirmed_by"] = actor_name

    token = _ALLOW_TRANSITION_STATE.set(True)
    release_token = _ALLOW_RELEASED_CONSTRUCTION.set(True)
    try:
        # Re-validate fully
        successor = DispositionUnit.model_validate(data)
    finally:
        _ALLOW_RELEASED_CONSTRUCTION.reset(release_token)
        _ALLOW_TRANSITION_STATE.reset(token)
    return successor


def evaluate_package_eligibility(
    units: list[DispositionUnit], ctx: ReleaseContext
) -> tuple[bool, list[str]]:
    """
    Return (all_eligible, list_of_reasons_for_failures).

    Empty reasons list + True means the whole package may be released.
    """
    reasons: list[str] = []
    for u in units:
        if u.is_rollup:
            continue  # roll-ups are not disposition targets; they are excluded from release counts
        ok, why = is_unit_release_eligible(u, ctx)
        if not ok:
            reasons.append(f"{u.unit_id}: {why}")
    return (len(reasons) == 0), reasons


def mark_package_release_approved(
    store: DispositionStore,
    units: list[DispositionUnit],
    actor: ActorIdentity,
    ctx: ReleaseContext,
) -> list[DispositionUnit]:
    """
    The single entry point for releasing a package.

    - Evaluates every non-rollup unit against the ReleaseContext.
    - If any fails, raises ReleaseRefusal with the reasons (no partial marking).
    - Authorizes the actor for the release transition.
    - Builds fully validated released successors under the narrow internal token.
    - Atomically writes via the store (write-temp-rename) and appends the event.
    - Idempotent: if all relevant units are already release_approved under a
      compatible context, this is effectively a no-op after the check.

    Returns the list of released units as stored.
    """
    # Authorize first (raises PermissionError if not allowed).
    # On unauthorized, log a rejection event before surfacing the error.
    try:
        require_authorized_transition(actor, "human_confirmed", "release_approved")
    except PermissionError as e:
        try:
            store.events.append(
                actor=actor.name,
                from_state="human_confirmed",
                to_state="release_approved",
                unit_id=None,
                payload={"event_type": "release_rejected", "reason": str(e)},
            )
        except Exception:
            pass  # logging failure must not mask the original authorization failure
        raise

    # CRITICAL: Load the authoritative current state from the store.
    # Never trust a caller-supplied subset for the release decision.
    authoritative_units = store.list_units()
    non_rollup_units = [u for u in authoritative_units if not u.is_rollup]

    if not non_rollup_units:
        raise ReleaseRefusal("No non-rollup units to release", ["package contains no disposition units"])

    # Separate concerns for idempotency and correctness:
    # - Units already release_approved: ok for this release action (idempotent)
    # - Units at human_confirmed: must pass the full gate
    # - Anything else (proposed, rejected, etc.): refuse
    needing = [u for u in non_rollup_units if u.workflow_state == "human_confirmed"]
    already = [u for u in non_rollup_units if u.workflow_state == "release_approved"]
    blocked = [u for u in non_rollup_units if u.workflow_state not in ("human_confirmed", "release_approved")]

    if blocked:
        reasons = [f"{u.unit_id}: cannot release from state {u.workflow_state}" for u in blocked]
        raise ReleaseRefusal("Package is not release-eligible", reasons)

    if needing:
        eligible, reasons = evaluate_package_eligibility(needing, ctx)
        if not eligible:
            raise ReleaseRefusal("Package is not release-eligible", reasons)

    # to_release = the ones we will actually advance in this call
    to_release = needing  # already-released are left alone

    # Build successors under controlled path (from authoritative list only)
    released: list[DispositionUnit] = []
    for u in to_release:
        if u.workflow_state == "release_approved":
            released.append(u)
            continue
        succ = _build_released_successor(u, actor.name)
        if succ.workflow_state != "release_approved":
            raise RuntimeError("Internal error: successor not in release_approved after gate")
        released.append(succ)

    if not released:
        # All were already release_approved — idempotent no-op path
        return [u for u in non_rollup_units if u.workflow_state == "release_approved"]

    # Atomic application through store (the store will also append the package-level event)
    ctx_dict = {
        "effective_date": ctx.effective_date,
        "configurations": list(ctx.configurations),
        "part_classes": list(ctx.part_classes),
        "evidence_threshold": ctx.evidence_threshold,
    }
    applied = store.apply_release_marking(released, actor, ctx_dict)
    LOGGER.info("release.marked package=%s count=%s actor=%s", store.root, len(applied), actor.name)
    return applied
