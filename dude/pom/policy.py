#!/usr/bin/env python3
"""
Module: dude.pom.policy
Purpose: The POM policy engine (build instruction §4–§5, §8, §10) and the
         model-lag check.

Machine-enforced constitutional invariants, fail closed:
  historical_context is not current_case_evidence
  trigger_match is not hypothesis_support or hypothesis_contradiction
  assistant_interpretation is not user_fact (enforced in contracts)
  semantic_similarity is not corroboration
  personal_history shapes uncertainty handling, never causal truth
  stale data is not current truth

The model-lag output is evidence-state language only, validated against
the banned-phrase floor: "Parts of the model remain supported. The
<component> component appears stale." — never "your fear is false."

Safety Critical: True — a policy hole here is biography becoming
evidence, the exact harm the instruction exists to prevent.
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import logging
from datetime import datetime, timezone
from enum import Enum

from pydantic import Field

from dude.core.loop import validate_copy
from dude.data.base import DudeModel
from dude.pom.contracts import (
    PROHIBITED_USES,
    AllowedUse,
    GroundingCoordinate,
    PomItem,
    Temporal,
    WorkingModel,
)

LOGGER = logging.getLogger("dude.pom.policy")


class PolicyViolation(Exception):
    """A prohibited, unauthorized, or stale use. Always fail closed."""


def authorize(item: PomItem, use: AllowedUse | str, now: datetime | None = None) -> None:
    """Raise PolicyViolation unless `use` is explicitly allowed for this
    item RIGHT NOW. Evidence-class uses raise for every item, always."""
    if isinstance(use, str) and use in PROHIBITED_USES:
        raise PolicyViolation(
            f"Use {use!r} is constitutionally prohibited for all POM items: "
            "personal history may shape uncertainty handling, communication, "
            "and safety — never what happened in the external world (§5/§17)."
        )
    try:
        resolved = AllowedUse(use)
    except ValueError as exc:
        raise PolicyViolation(f"Unknown use {use!r}; nothing is allowed by default.") from exc
    if not item.active:
        raise PolicyViolation(f"Item {item.id} is inactive.")
    if item.temporal is Temporal.HISTORICAL:
        raise PolicyViolation(
            f"Item {item.id} is historical/stale (e.g. a financial snapshot) "
            "and is excluded from operational retrieval (§10)."
        )
    moment = now or datetime.now(timezone.utc)
    if item.temporal is Temporal.WINDOWED and item.valid_to and moment > item.valid_to:
        raise PolicyViolation(f"Item {item.id} validity window expired (§10).")
    if resolved not in item.allowed_uses:
        raise PolicyViolation(
            f"Use {resolved.value!r} is not in the allowed-use policy of "
            f"item {item.id} (nothing is allowed by default)."
        )


def surface_grounding(coordinate: GroundingCoordinate, context: str) -> str:
    """A grounding phrase surfaces ONLY in an allowed activation context
    and never in a contraindicated one (§8)."""
    if not coordinate.active:
        raise PolicyViolation(f"Grounding {coordinate.id} is inactive.")
    if context in coordinate.contraindications:
        raise PolicyViolation(
            f"Context {context!r} is contraindicated for this grounding phrase."
        )
    if context not in coordinate.activation_contexts:
        raise PolicyViolation(
            f"Context {context!r} is not an allowed activation context; "
            "grounding phrases are never deployed generically (§8)."
        )
    return coordinate.phrase


class LagStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    APPEARS_STALE = "appears_stale"
    UNRESOLVED = "unresolved"


class LagVerdict(DudeModel):
    component: str
    status: LagStatus
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)


def model_lag_check(model: WorkingModel) -> list[LagVerdict]:
    """Per-component staleness verdicts from CURRENT evidence only.

    Deterministic: a component with only contradicting current evidence
    APPEARS STALE (not "is false"); only supporting evidence -> still
    supported; both -> partially supported; neither -> unresolved. The
    historical basis is context, never a vote in either direction."""
    verdicts = []
    for component in model.components:
        has_for = bool(component.currently_supporting)
        has_against = bool(component.currently_contradicting)
        if has_for and has_against:
            status = LagStatus.PARTIALLY_SUPPORTED
        elif has_for:
            status = LagStatus.SUPPORTED
        elif has_against:
            status = LagStatus.APPEARS_STALE
        else:
            status = LagStatus.UNRESOLVED
        verdicts.append(
            LagVerdict(
                component=component.name,
                status=status,
                supporting=component.currently_supporting,
                contradicting=component.currently_contradicting,
            )
        )
    return verdicts


def lag_summary(model: WorkingModel, verdicts: list[LagVerdict]) -> str:
    """Evidence-state copy for a lag check. Never a motive attribution,
    never 'your fear is false' — validated against the banned-phrase
    floor before it can leave this function."""
    supported = [v.component for v in verdicts if v.status is LagStatus.SUPPORTED]
    partial = [v.component for v in verdicts if v.status is LagStatus.PARTIALLY_SUPPORTED]
    stale = [v.component for v in verdicts if v.status is LagStatus.APPEARS_STALE]
    parts = [f"Model {model.name!r}:"]
    if supported or partial:
        names = ", ".join(supported + partial)
        parts.append(f"parts of the model remain supported ({names}).")
    for name in stale:
        parts.append(
            f"The {name!r} component appears stale: current evidence "
            "contradicts it and none currently supports it."
        )
    if not (supported or partial or stale):
        parts.append("no current evidence on either side; unresolved.")
    return validate_copy(" ".join(parts))
