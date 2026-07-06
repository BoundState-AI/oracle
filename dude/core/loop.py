#!/usr/bin/env python3
"""
Module: dude.core.loop
Purpose: Evidence-state messaging and the banned-phrase floor
         (spec v0.2 I2; review A8).

All engine copy describing analysis state comes from the templates in
this module, and every template is validated at import time against the
banned-phrase list: the engine may describe the EVIDENCE STATE, never the
user's psychology. Loop concerns are raised as questions, never verdicts
("is this the same claim, or is the initiator new?") — the user is the
authority on whether their hypothesis is new.

Safety Critical: False
Psychologically Critical: True — this module is the anti-gaslighting
enforcement point; a motive attribution shipped from here reaches every
user at their worst moment.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging

from dude.data.enums import GateMode

LOGGER = logging.getLogger("dude.core.loop")

# Phrases that attribute motive or pathology to the user. Machine-checked:
# validate_copy() runs on every template at import time and is available
# to tests for any user-facing string the engine produces. Additions are
# cheap; removals require review with a WHY comment.
BANNED_PHRASES: tuple[str, ...] = (
    "because uncertainty hurts",
    "you are recomputing",
    "you're recomputing",
    "you are ruminating",
    "you're ruminating",
    "you are just triggered",
    "you're just triggered",
    "you are overreacting",
    "you're overreacting",
    "calm down",
    "being irrational",
    "being paranoid",
    "in your head",
)


class BannedCopyError(Exception):
    """Raised when engine copy attributes motive or pathology."""


def validate_copy(text: str) -> str:
    """Return text unchanged, or raise BannedCopyError. Never softens or
    rewrites — a violation is a defect to fix at the source."""
    lowered = text.lower()
    hits = [p for p in BANNED_PHRASES if p in lowered]
    if hits:
        raise BannedCopyError(f"Engine copy contains banned phrasing: {hits}")
    return text


_MODE_TEMPLATES: dict[GateMode, str] = {
    GateMode.NEW_EVIDENCE: (
        "New evidence since the last analysis. Full re-analysis ran; the "
        "delta report shows which hypotheses moved and why."
    ),
    GateMode.NEW_HYPOTHESIS_REANALYSIS: (
        "The hypothesis set changed with no new evidence. That is learning, "
        "not repetition — the full pipeline ran against the existing "
        "evidence, labeled as a hypothesis-driven re-analysis."
    ),
    GateMode.SCOPE_CHANGE: (
        "The decision scope changed (a deadline or elapsed time moved) with "
        "no new evidence. Continued silence is itself low-resolution data; "
        "the analysis was re-run against the current scope."
    ),
    GateMode.INCOMPLETE_PRIOR_RERUN: (
        "The evidence set is unchanged, but the previous analysis did not "
        "fully run (some passes refused). The incomplete passes were "
        "re-run against the existing evidence."
    ),
    GateMode.NO_NEW_DATA: (
        "The evidence set, hypothesis set, and decision scope are unchanged "
        "since the last analysis. Re-running now would recompute the same "
        "inputs. The prior result and the cumulative view are attached. If "
        "something new exists — an event, a document, a hypothesis — add it "
        "and analysis will re-run."
    ),
}

LOOP_QUESTION_TEMPLATE = (
    "This looks similar to an existing hypothesis: {existing_title!r}. Is it "
    "the same claim, or is something materially different — for example the "
    "direction, the initiator, or the mechanism? If it is different, add it "
    "as a new hypothesis and analysis will re-run."
)


def mode_message(mode: GateMode) -> str:
    """The vetted evidence-state message for a gate mode."""
    return _MODE_TEMPLATES[mode]


def loop_question(existing_title: str) -> str:
    """A loop concern phrased as a question, never a verdict (v0.2 I2)."""
    return validate_copy(LOOP_QUESTION_TEMPLATE.format(existing_title=existing_title))


# Import-time enforcement: a banned phrase in a template is a build
# failure, not a runtime surprise.
for _mode, _template in _MODE_TEMPLATES.items():
    validate_copy(_template)
validate_copy(LOOP_QUESTION_TEMPLATE)
