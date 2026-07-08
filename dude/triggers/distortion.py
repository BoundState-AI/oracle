#!/usr/bin/env python3
"""
Module: dude.triggers.distortion
Purpose: The bidirectional distortion vocabulary (trigger spec v1 §5,
         rebuilt per v1.1 R3).

Every renderable string lives in the template registry below and passes
the banned-phrase floor (dude.core.loop.validate_copy) at import time.
The block is BIDIRECTIONAL by construction: amplification candidates
(urgency, certainty, action pressure, attention narrowing) are paired
with suppression candidates (minimization, habituation, self-doubt) —
overlap can push a read in either direction. "Need to escape" and
"protector response" are NOT in the renderable vocabulary (R3), and the
mirrored invariant NO_TRIGGER_MATCH != ACTIVATION_UNWARRANTED has vetted
no-match copy.

Render rules: the distortion block renders only at overlap >= moderate,
and never while a crisis is active (R2 — safety outranks the trigger
engine; the only overlap copy in a crisis is the precedence line, below
the resources).

Safety Critical: False
Psychologically Critical: True — this module is the renderable surface
of the trigger engine; a one-directional vocabulary here IS the
dismissal machine.

Never-suppress-error: a banned phrase in any template is an import-time
failure, not a runtime surprise.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging

from dude.core.loop import validate_copy
from dude.triggers.contracts import OverlapLevel

LOGGER = logging.getLogger("dude.triggers.distortion")

# Vocabulary removed from renderable copy by R3. Machine-checked at
# import time against every template in this registry.
NON_RENDERABLE_VOCABULARY: tuple[str, ...] = ("need to escape", "protector response")

BLOCK_HEADER = "WHAT OVERLAP CAN DISTORT - IN EITHER DIRECTION"

# All copy is CONDITIONAL ("can", "may") — candidates, never verdicts.
AMPLIFICATION_TEMPLATES: dict[str, str] = {
    "urgency": (
        "Amplification candidate - urgency: the pressure to act now may "
        "be larger than the evidence window requires."
    ),
    "certainty": (
        "Amplification candidate - certainty: a causal story may feel "
        "more settled than the evidence currently supports."
    ),
    "action_pressure": (
        "Amplification candidate - action pressure: doing something may "
        "feel safer than waiting for more telemetry."
    ),
    "attention_narrowing": (
        "Amplification candidate - attention narrowing: material outside "
        "the matched pattern may be getting less weight than it deserves."
    ),
}

SUPPRESSION_TEMPLATES: dict[str, str] = {
    "minimization": (
        "Suppression candidate - minimization: a real signal can be "
        "downplayed precisely because it resembles a pattern already "
        "survived before."
    ),
    "habituation": (
        "Suppression candidate - habituation: a repeated pattern can "
        "start to read as normal even while the evidence worsens."
    ),
    "self_doubt": (
        "Suppression candidate - self-doubt: knowing this pattern exists "
        "can make an accurate read feel less trustworthy than it is."
    ),
}

# Mirrored invariant copy (R3): NO_TRIGGER_MATCH != ACTIVATION_UNWARRANTED.
NO_MATCH_COPY = (
    "No calibrated pattern matched. That says nothing about whether your "
    "read is right."
)

# v1 §5: always rendered with any overlap.
EVIDENCE_EFFECT_COPY = (
    "Trigger overlap does not reduce the weight of observed evidence."
)

# R2: the only overlap copy allowed while a crisis is active, rendered
# BELOW the crisis resources.
CRISIS_PRECEDENCE_COPY = "Trigger overlap does not reduce this emergency."

# R5: unconfirmed assessments render as possibility, never as fact.
POSSIBLE_OVERLAP_TEMPLATE = (
    "Possible overlap (model-assessed, unconfirmed): {labels}. Confirm or "
    "deny in the calibration lab; unconfirmed matches change nothing."
)

# R8: a family firing on most cases carries little diagnostic signal.
LOW_DIAGNOSTIC_TEMPLATE = (
    "Low diagnostic value: {label} matches most cases on record, so it is "
    "not counted toward high overlap here."
)

OVERLAP_LINE_TEMPLATE = "TRIGGER OVERLAP: {level}"


def renderable_templates() -> tuple[str, ...]:
    """Every string this module can render, for tests and audits."""
    return (
        BLOCK_HEADER,
        *AMPLIFICATION_TEMPLATES.values(),
        *SUPPRESSION_TEMPLATES.values(),
        NO_MATCH_COPY,
        EVIDENCE_EFFECT_COPY,
        CRISIS_PRECEDENCE_COPY,
        POSSIBLE_OVERLAP_TEMPLATE,
        LOW_DIAGNOSTIC_TEMPLATE,
        OVERLAP_LINE_TEMPLATE,
    )


def render_distortion_block(level: OverlapLevel, crisis_active: bool) -> str:
    """The paired amplification/suppression block. Empty below moderate
    overlap (R3) and always empty while a crisis is active (R2)."""
    if crisis_active:
        return ""
    if level not in (OverlapLevel.MODERATE, OverlapLevel.HIGH):
        return ""
    lines = [BLOCK_HEADER]
    lines.extend(AMPLIFICATION_TEMPLATES.values())
    lines.extend(SUPPRESSION_TEMPLATES.values())
    return validate_copy("\n".join(lines))


def render_overlap_line(level: OverlapLevel) -> str:
    return validate_copy(OVERLAP_LINE_TEMPLATE.format(level=level.value))


def render_possible_overlap(labels: list[str]) -> str:
    return validate_copy(
        POSSIBLE_OVERLAP_TEMPLATE.format(labels=", ".join(sorted(labels)))
    )


def render_low_diagnostic(label: str) -> str:
    return validate_copy(LOW_DIAGNOSTIC_TEMPLATE.format(label=label))


def _validate_registry() -> None:
    """Import-time enforcement: banned phrases and the R3-removed
    vocabulary are build failures."""
    for template in renderable_templates():
        validate_copy(template)
        lowered = template.lower()
        hits = [v for v in NON_RENDERABLE_VOCABULARY if v in lowered]
        if hits:
            raise ValueError(
                f"Distortion template contains non-renderable vocabulary "
                f"{hits} (R3)."
            )


_validate_registry()
