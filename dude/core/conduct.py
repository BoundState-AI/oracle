#!/usr/bin/env python3
"""
Module: dude.core.conduct
Purpose: Course-of-conduct accrual (spec v0.2 I6; review A4).

Rules 2–3 of the v0.1 constitution are false for stalking, harassment,
and coercive control, where the pattern IS the evidence. This engine is
the exception, made structural: repeated same-class EVENTS (incidents,
including silence checkpoints) accrue cumulative weight that is reported
alongside per-run deltas and can escalate a case with no new evidence
*types*. Repetition of thoughts still accrues nothing — the distinction
is events vs analysis requests, enforced by what this module consumes.

Thresholds are deliberately coarse, documented, and recall-leaning:
under-counting a real pattern is the dangerous direction.

Safety Critical: True — this is the chronic-danger pathway (review A3).
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
from collections import defaultdict

from dude.data.case import CumulativePattern
from dude.data.enums import ConfidenceBand
from dude.data.evidence import Event

LOGGER = logging.getLogger("dude.core.conduct")

# Event-count -> cumulative band for "a pattern of conduct exists".
# 1 incident is a data point; 2 is a coincidence candidate; 3–4 is a
# pattern worth treating as plausible; 5+ is supported. Course-of-conduct
# statutes typically require as few as 2 acts — these thresholds must
# never be raised without safety review.
_BAND_THRESHOLDS: tuple[tuple[int, ConfidenceBand], ...] = (
    (5, ConfidenceBand.SUPPORTED),
    (3, ConfidenceBand.PLAUSIBLE),
    (2, ConfidenceBand.WEAKLY_SUPPORTED),
    (1, ConfidenceBand.UNRESOLVED),
)


def accrue(events: list[Event]) -> list[CumulativePattern]:
    """Cumulative-since-case-open pattern accrual over confirmed events.

    Only user-confirmed events count (same discipline as the fingerprint):
    machine-extracted incidents must be confirmed before they accrue —
    otherwise extraction noise could manufacture a pattern."""
    by_class: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.pattern_class and event.user_confirmed:
            by_class[event.pattern_class].append(event)

    patterns: list[CumulativePattern] = []
    for pattern_class, hits in sorted(by_class.items()):
        occurred = sorted(
            (e.occurred_at or e.recorded_at) for e in hits
        )
        band = _band_for(len(hits))
        patterns.append(
            CumulativePattern(
                pattern_class=pattern_class,
                event_count=len(hits),
                first_at=occurred[0],
                last_at=occurred[-1],
                cumulative_band=band,
            )
        )
        if band in (ConfidenceBand.PLAUSIBLE, ConfidenceBand.SUPPORTED):
            LOGGER.warning(
                "Course-of-conduct pattern %r at %s (%d events)",
                pattern_class,
                band.value,
                len(hits),
            )
    return patterns


def _band_for(count: int) -> ConfidenceBand:
    for threshold, band in _BAND_THRESHOLDS:
        if count >= threshold:
            return band
    return ConfidenceBand.UNRESOLVED
