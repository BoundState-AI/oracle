#!/usr/bin/env python3
"""
Module: dude.core.safety
Purpose: The deterministic safety floor (spec v0.2 §5, invariant I1).

This is the layer beneath any future LLM safety judgment. It runs on
every capture and at the top of every analysis run — before the
no-new-data gate, before extraction, before anything can throw. It is
pattern-based and tuned for recall: a false positive surfaces crisis
resources, which is an acceptable cost; a false negative combined with a
hold recommendation is the company-ending failure the ORACLE review
called A2.

While a crisis flag is active downstream: hold/wait recommendations are
suppressed and the action generator's high-risk option is suppressed.
Chronic categories (stalking_pattern, coercive_control) additionally feed
course-of-conduct accrual (dude.core.conduct) — the chronic-danger
pathway, distinct from the acute bypass.

Safety Critical: True
Psychologically Critical: True

Never-suppress-error: any failure in this module is logged in full and
re-raised — a safety scan that fails OPEN is the cardinal failure mode.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import logging
import re

from dude.data.enums import SafetyCategory
from dude.data.safety import CrisisResource, SafetyFlag, SafetyScanResult

LOGGER = logging.getLogger("dude.core.safety")

# Resources surfaced verbatim on any crisis flag (spec v0.2 §5). US-scoped
# for Phase 1 single-tenant dogfood; jurisdiction-aware resolution is a
# later phase and widening this list requires safety review.
CRISIS_RESOURCES: tuple[CrisisResource, ...] = (
    CrisisResource(
        name="988 Suicide & Crisis Lifeline",
        contact="Call or text 988",
        note="24/7, free, confidential",
    ),
    CrisisResource(
        name="Crisis Text Line",
        contact="Text HOME to 741741",
        note="24/7 text support",
    ),
    CrisisResource(
        name="National Domestic Violence Hotline",
        contact="1-800-799-7233",
        note="24/7; also thehotline.org chat",
    ),
    CrisisResource(
        name="Emergency services",
        contact="Call 911",
        note="If there is immediate physical danger, call now.",
    ),
)

CRISIS_MESSAGE = (
    "This may require immediate real-world help. Do not wait for more "
    "certainty, and do not wait for further analysis from this tool."
)

# Acute categories flip `crisis` and bypass every gate. Chronic categories
# flag without flipping crisis (they feed conduct accrual instead), unless
# they co-occur with an acute pattern.
_ACUTE = frozenset(
    {
        SafetyCategory.SELF_HARM,
        SafetyCategory.VIOLENCE_THREAT,
        SafetyCategory.CHILD_DANGER,
        SafetyCategory.MEDICAL_EMERGENCY,
    }
)

# Pattern table: (category, pattern_name, compiled regex). Recall-tuned:
# broad stems, case-insensitive. Adding a pattern is cheap; removing one
# requires safety review with a WHY comment in the diff.
_P = re.compile
_PATTERNS: tuple[tuple[SafetyCategory, str, re.Pattern[str]], ...] = (
    (
        SafetyCategory.SELF_HARM,
        "suicidal_ideation",
        _P(
            r"\b(kill(ing)? myself|end (it all|my life)|suicid\w*|"
            r"don'?t want to (live|be alive|wake up)|self[- ]harm\w*|"
            r"hurt(ing)? myself|no reason to (live|go on)|"
            r"better off (dead|without me))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.VIOLENCE_THREAT,
        "threat_language",
        _P(
            r"\b(threat\w* (to|of) (kill|hurt|harm)|going to (kill|hurt|shoot|stab)|"
            r"said (he|she|they)('| wou)?ll (kill|hurt|harm)|"
            r"make (me|you|sure .{0,40}) regret|"
            r"(hit|choked?|strangl\w*|beat(en)?) me|"
            r"afraid (he|she|they) will (hurt|kill))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.CHILD_DANGER,
        "child_danger",
        _P(
            r"\b((my|the) (kids?|children|boys?|girls?|son|daughter) "
            r"(is|are|isn'?t|aren'?t) (not )?safe|"
            r"(hurt|hit|touch\w*|abus\w*) (my|the) "
            r"(kids?|children|boys?|girls?|son|daughter))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.MEDICAL_EMERGENCY,
        "acute_symptoms",
        _P(
            r"\b(chest pain|can'?t breathe|trouble breathing|"
            r"(losing|lost) consciousness|passed out|overdos\w*|"
            r"stroke|seizure|bleeding (badly|a lot|won'?t stop))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.STALKING_PATTERN,
        "stalking",
        _P(
            r"\b(stalk\w*|follow(ing|ed) me|show(s|ing|ed)? up (at|outside) my|"
            r"track(ing|ed|er) (me|my (phone|car|location))|"
            r"watch(ing|es) my (house|home|apartment))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.COERCIVE_CONTROL,
        "coercive_control",
        _P(
            r"\b(won'?t let me (leave|see|talk|work|go)|"
            r"controls? (my|the) (money|phone|car|accounts?)|"
            r"isolat(es?|ed|ing) me|threatens? (to leave|divorce|custody|"
            r"to take the (kids|children))|"
            r"checks? my (phone|email|messages)|"
            r"if i leave,? (he|she|they))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.LEGAL_DEADLINE,
        "legal_deadline",
        _P(
            r"\b(statute of limitations|court (date|deadline)|"
            r"respond (by|before|within)|filing deadline|"
            r"deadline (is|of|to file)|days? (left )?to (file|respond|appeal))\b",
            re.IGNORECASE,
        ),
    ),
)

# How much surrounding text to keep with a match so the flag is auditable
# without storing the entire capture in the safety stream.
_EXCERPT_RADIUS = 40


def scan(text: str) -> SafetyScanResult:
    """Scan text against the pattern floor. Deterministic; never raises on
    content (only on programming errors, which propagate — fail closed is
    the caller persisting a refusal, not this module guessing)."""
    flags: list[SafetyFlag] = []
    for category, name, pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            flags.append(
                SafetyFlag(
                    category=category,
                    matched_excerpt=_excerpt(text, match.start(), match.end()),
                    pattern_name=name,
                )
            )
    crisis = any(f.category in _ACUTE for f in flags)
    if flags:
        LOGGER.warning(
            "Safety floor hit: categories=%s crisis=%s",
            sorted({f.category.value for f in flags}),
            crisis,
        )
    return SafetyScanResult(
        flags=flags,
        crisis=crisis,
        resources=list(CRISIS_RESOURCES) if crisis else [],
        user_facing_message=CRISIS_MESSAGE if crisis else "",
    )


def _excerpt(text: str, start: int, end: int) -> str:
    lo = max(0, start - _EXCERPT_RADIUS)
    hi = min(len(text), end + _EXCERPT_RADIUS)
    return text[lo:hi]
