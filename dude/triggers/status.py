#!/usr/bin/env python3
"""
Module: dude.triggers.status
Purpose: Deterministic status promotion/demotion for trigger profiles
         (trigger spec v1.1 R4).

The rules, in precedence order:
  1. User retirement always wins: a retired profile never moves again
     unless the user reverses it.
  2. A quorum of contradicting evidence (>= 2 contradicts) demotes one
     level with a visible reason.
  3. Promotion to self_report_supported requires >= 2 calibration
     sessions with temporal separation, >= 1 passed negative control, and
     >= 1 in-vivo confirmation (the user tagging a real case post-hoc).
  4. Match-derived evidence (repeated_case_pattern, assistant_hypothesis)
     is excluded from ALL status math — no closed loop.
  5. Quarantined and revoked calibration is excluded, and out-of-range
     raw scores never count at face value (§13/R6f).

There is no path above self_report_supported: the vocabulary has no such
member (Phase-1 cap, structural).

Safety Critical: False
Psychologically Critical: True — a status engine that inflates support
builds the dismissal machine's authority; one that silently demotes
gaslights the calibration record.

Never-suppress-error: inconsistent inputs raise; nothing is coerced.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dude.triggers.contracts import (
    MATCH_DERIVED_SOURCES,
    CalibrationPrompt,
    EvidenceSourceType,
    PersonalTriggerProfile,
    SupportDirection,
    TriggerCalibrationResponse,
    TriggerEvidence,
    TriggerFamilyStatus,
)
from dude.triggers.store import TriggerStore

LOGGER = logging.getLogger("dude.triggers.status")

CONTRADICTION_QUORUM = 2
MIN_CALIBRATION_SESSIONS = 2
# Two ratings an hour apart are one sitting, not two sessions. A day is
# the coarsest separation that still lets a motivated user recalibrate
# meaningfully between real days.
MIN_SESSION_SEPARATION = timedelta(hours=24)
# A negative control passes when its effective score sits at the floor
# of the declared scale (<= 1): the low arm of the pair genuinely reads
# as cold, so the family is discriminating, not firing on everything.
NEGATIVE_CONTROL_PASS_CEILING = 1

# Demotion ladder, lowest first. RETIRED is deliberately absent: only the
# user can retire, and demotion below CONTRADICTED does not exist.
_LADDER: tuple[TriggerFamilyStatus, ...] = (
    TriggerFamilyStatus.CONTRADICTED,
    TriggerFamilyStatus.CANDIDATE_WITH_LOW_SUPPORT,
    TriggerFamilyStatus.CANDIDATE,
    TriggerFamilyStatus.SELF_REPORT_SUPPORTED,
)

_IN_VIVO_SOURCES = frozenset(
    {EvidenceSourceType.IN_VIVO_CONFIRMATION, EvidenceSourceType.CASE_RESOLUTION}
)


@dataclass(frozen=True)
class StatusDecision:
    """The engine's verdict for one profile, with the visible reason."""

    status: TriggerFamilyStatus
    reason: str
    changed: bool


def usable_responses(
    responses: list[TriggerCalibrationResponse],
) -> list[TriggerCalibrationResponse]:
    """Quarantined and revoked calibration is excluded from matching and
    status alike (R6f/R6d)."""
    return [r for r in responses if not r.quarantined and not r.revoked]


def face_value_responses(
    responses: list[TriggerCalibrationResponse],
) -> list[TriggerCalibrationResponse]:
    """Out-of-range raw scores are preserved verbatim but never count at
    face value in status math (§13/R4)."""
    return [r for r in usable_responses(responses) if not r.out_of_range]


def countable_evidence(evidence: list[TriggerEvidence]) -> list[TriggerEvidence]:
    """Match-derived sources are excluded from all status math (R4)."""
    return [e for e in evidence if e.source_type not in MATCH_DERIVED_SOURCES]


def separated_session_count(responses: list[TriggerCalibrationResponse]) -> int:
    """Distinct sessions, counting a session only when it starts at least
    MIN_SESSION_SEPARATION after the previously counted one."""
    starts: dict[str, datetime] = {}
    for response in responses:
        current = starts.get(response.session_id)
        if current is None or response.timestamp < current:
            starts[response.session_id] = response.timestamp
    count = 0
    last: datetime | None = None
    for start in sorted(starts.values()):
        if last is None or start - last >= MIN_SESSION_SEPARATION:
            count += 1
            last = start
    return count


def passed_negative_controls(
    responses: list[TriggerCalibrationResponse],
    prompts: list[CalibrationPrompt],
) -> int:
    controls = {p.id for p in prompts if p.is_negative_control}
    return sum(
        1
        for r in responses
        if r.prompt_id in controls
        and r.effective_score() <= NEGATIVE_CONTROL_PASS_CEILING
    )


def _family_responses(
    profile: PersonalTriggerProfile,
    responses: list[TriggerCalibrationResponse],
    prompts: list[CalibrationPrompt],
) -> list[TriggerCalibrationResponse]:
    family_prompt_ids = {
        p.id for p in prompts if p.family_slug == profile.family_slug
    }
    return [r for r in responses if r.prompt_id in family_prompt_ids]


def _promotion_eligible(
    profile: PersonalTriggerProfile,
    evidence: list[TriggerEvidence],
    responses: list[TriggerCalibrationResponse],
    prompts: list[CalibrationPrompt],
) -> bool:
    family_responses = _family_responses(profile, responses, prompts)
    if separated_session_count(face_value_responses(family_responses)) < (
        MIN_CALIBRATION_SESSIONS
    ):
        return False
    if passed_negative_controls(usable_responses(family_responses), prompts) < 1:
        return False
    return any(
        e.source_type in _IN_VIVO_SOURCES
        and e.support_direction is SupportDirection.SUPPORTS
        for e in evidence
    )


def evaluate(
    profile: PersonalTriggerProfile,
    evidence: list[TriggerEvidence],
    responses: list[TriggerCalibrationResponse],
    prompts: list[CalibrationPrompt],
) -> StatusDecision:
    """The deterministic verdict (R4). Precedence: retirement > demotion
    quorum > promotion > no change."""
    if profile.status is TriggerFamilyStatus.RETIRED:
        return StatusDecision(
            status=TriggerFamilyStatus.RETIRED,
            reason="User retirement always wins; only the user can reverse it.",
            changed=False,
        )
    family_evidence = [
        e for e in countable_evidence(evidence) if e.family_slug == profile.family_slug
    ]
    contradicts = [
        e
        for e in family_evidence
        if e.support_direction is SupportDirection.CONTRADICTS
    ]
    if len(contradicts) >= CONTRADICTION_QUORUM:
        demoted = _one_level_down(profile.status)
        if demoted is not profile.status:
            refs = ", ".join(sorted(e.id for e in contradicts))
            return StatusDecision(
                status=demoted,
                reason=(
                    f"Demoted one level: {len(contradicts)} contradicting "
                    f"evidence records ({refs}) met the quorum of "
                    f"{CONTRADICTION_QUORUM} (R4)."
                ),
                changed=True,
            )
    if profile.status in (
        TriggerFamilyStatus.CANDIDATE,
        TriggerFamilyStatus.CANDIDATE_WITH_LOW_SUPPORT,
    ) and _promotion_eligible(profile, family_evidence, responses, prompts):
        return StatusDecision(
            status=TriggerFamilyStatus.SELF_REPORT_SUPPORTED,
            reason=(
                "Promoted: >=2 temporally separated calibration sessions, "
                ">=1 passed negative control, and an in-vivo confirmation "
                "(R4). Phase-1 cap: nothing promotes higher."
            ),
            changed=True,
        )
    return StatusDecision(status=profile.status, reason="No change.", changed=False)


def _one_level_down(status: TriggerFamilyStatus) -> TriggerFamilyStatus:
    if status not in _LADDER:
        return status
    index = _LADDER.index(status)
    return _LADDER[max(0, index - 1)]


def apply_decision(
    store: TriggerStore,
    profile: PersonalTriggerProfile,
    decision: StatusDecision,
) -> PersonalTriggerProfile:
    """Persist a changed decision as a SUPERSEDING record — status moves
    are visible history, never in-place flips."""
    if not decision.changed:
        return profile
    updated = profile.model_copy(
        update={
            "id": _new_profile_id(),
            "supersedes": profile.id,
            "status": decision.status,
            "status_reason": decision.reason,
        }
    )
    store.append(updated)
    LOGGER.info(
        "Profile %s (%s): %s -> %s (%s)",
        profile.id,
        profile.family_slug,
        profile.status.value,
        decision.status.value,
        decision.reason,
    )
    return updated


def retire(
    store: TriggerStore, profile: PersonalTriggerProfile, reason: str
) -> PersonalTriggerProfile:
    """User retirement — always wins, and is recorded with the user's
    reason (R4)."""
    retired = profile.model_copy(
        update={
            "id": _new_profile_id(),
            "supersedes": profile.id,
            "status": TriggerFamilyStatus.RETIRED,
            "status_reason": f"Retired by user: {reason}",
        }
    )
    store.append(retired)
    return retired


def _new_profile_id() -> str:
    import uuid

    return uuid.uuid4().hex
