#!/usr/bin/env python3
"""
Module: oracle.disposition.rollup
Purpose: Parent roll-up composition vectors and badge derivation per §1.1.

A parent requirement with child units is a non-dispositional roll-up row.
It carries a composition vector (counts of children per code) and derives
a single render badge via a total order. Parents are never disposition
targets and are excluded from all counts.

Badge precedence (highest first):
  OPEN > EX > MI > MIXED > CW > NA

Every child-code combination resolves to exactly one badge.

Safety Critical: advisory-only per spec D-1

__safety_critical__: bool = False  # advisory-only per D-1 (S1 is pure data + state)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Iterable

from oracle.disposition.codes import DISPOSITION_CODES, DispositionCode

LOGGER = logging.getLogger("oracle.disposition.rollup")


class Badge(str, Enum):
    """
    Render badge for a parent roll-up row.

    Derived deterministically from child composition. Never assigned
    independently to a unit.
    """

    OPEN = "OPEN"
    EX = "EX"
    MI = "MI"
    MIXED = "MIXED"
    CW = "CW"
    NA = "NA"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Total order: lower index wins (first match wins)
_BADGE_PRECEDENCE: list[Badge] = [
    Badge.OPEN,
    Badge.EX,
    Badge.MI,
    Badge.MIXED,
    Badge.CW,
    Badge.NA,
]

# Map code -> badge when that code alone determines the result
_CODE_TO_BADGE: dict[str, Badge] = {
    DispositionCode.OPEN.value: Badge.OPEN,
    DispositionCode.EX.value: Badge.EX,
    DispositionCode.MI.value: Badge.MI,
    DispositionCode.CW.value: Badge.CW,
    DispositionCode.NA.value: Badge.NA,
}


def rollup_badge(composition: dict[str, int]) -> Badge:
    """
    Derive the single render badge for a parent from its composition vector.

    composition: mapping of code value (CW|MI|EX|NA|OPEN) to child count.
    Returns exactly one Badge per the §1.1 total order.

    A parent with zero children (empty or all-zero composition) resolves to NA
    (vacuously no applicable children). This is an edge case; normal usage
    ensures parents have at least one child.

    Medium #3: defensively rejects unknown keys and negative counts so that
    a malformed vector (e.g., unknown code with negative count) cannot derive
    a false CW (or any other) badge.
    """
    if composition is None:
        composition = {}

    # Validate keys and counts (Medium #3)
    for k, v in composition.items():
        if k not in DISPOSITION_CODES:
            raise ValueError(
                f"rollup_badge received unknown code key: {k!r}; "
                f"allowed: {sorted(DISPOSITION_CODES)}"
            )
        # bool is subclass of int; require exact int (not bool, not subclass)
        if type(v) is not int or v < 0:
            raise ValueError(
                f"rollup_badge count for {k!r} must be a non-negative int, got {v!r}"
            )

    total_children = sum(composition.values()) if composition else 0

    # 1. Any OPEN child → OPEN
    if composition and composition.get(DispositionCode.OPEN.value, 0) > 0:
        return Badge.OPEN

    # 2. Any EX child → EX
    if composition and composition.get(DispositionCode.EX.value, 0) > 0:
        return Badge.EX

    # 3. Any MI child → MI
    if composition and composition.get(DispositionCode.MI.value, 0) > 0:
        return Badge.MI

    cw = (composition or {}).get(DispositionCode.CW.value, 0)
    na = (composition or {}).get(DispositionCode.NA.value, 0)

    # 4. Mix of CW and NA → MIXED
    if cw > 0 and na > 0:
        return Badge.MIXED

    # 5. All CW → CW
    if cw > 0 and na == 0:
        return Badge.CW

    # 6. All NA → NA
    if na > 0 and cw == 0:
        return Badge.NA

    # Terminal return for vacuous (zero-total) and any other undecided case.
    # This is the single fallback and is reached for {} / all-zero compositions.
    return Badge.NA


def compose_badge(child_codes: Iterable[str | DispositionCode]) -> Badge:
    """
    Convenience: given an iterable of child codes, build a composition and
    return the roll-up badge.

    This is the function the truth-table test will call exhaustively.
    """
    comp: dict[str, int] = {}
    for raw in child_codes:
        code = raw.value if isinstance(raw, DispositionCode) else str(raw)
        if code not in DISPOSITION_CODES:
            # Accept only valid codes; unknown should have been rejected upstream
            raise ValueError(f"Unknown child code in roll-up: {code}")
        comp[code] = comp.get(code, 0) + 1
    return rollup_badge(comp)
