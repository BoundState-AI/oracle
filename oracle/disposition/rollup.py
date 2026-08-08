#!/usr/bin/env python3
"""
Module: oracle.disposition.rollup
Purpose: Parent roll-up composition vectors and badge derivation per §1.1 + RDW S1R.

A parent requirement with child units is a non-dispositional roll-up row.
It carries a composition vector (counts of children per export-label key)
and derives a single render badge via a total order. Parents are never
disposition targets and are excluded from all counts.

Badge precedence (highest first) — Open/Not Met between EX and MI:
  OPEN > EX > ONM > MI > MIXED > CW > NA

Every child-label combination resolves to exactly one badge.

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

from oracle.disposition.codes import COMPOSITION_KEYS, DispositionCode, ExportLabel
from oracle.disposition.export_map import export_label_composition_key

LOGGER = logging.getLogger("oracle.disposition.rollup")


class Badge(str, Enum):
    """
    Render badge for a parent roll-up row.

    Derived deterministically from child composition. Never assigned
    independently to a unit.
    """

    OPEN = "OPEN"
    EX = "EX"
    ONM = "ONM"  # Open/Not Met
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
    Badge.ONM,
    Badge.MI,
    Badge.MIXED,
    Badge.CW,
    Badge.NA,
]


def _normalize_key(raw: str | DispositionCode | ExportLabel | Badge) -> str:
    if isinstance(raw, DispositionCode):
        return raw.value
    if isinstance(raw, ExportLabel):
        return export_label_composition_key(raw)
    if isinstance(raw, Badge):
        return raw.value
    key = str(raw)
    # Accept full customer labels
    try:
        lab = ExportLabel(key)
        return export_label_composition_key(lab)
    except ValueError:
        pass
    if key == "Open/Not Met" or key == "ONM":
        return "ONM"
    return key


def rollup_badge(composition: dict[str, int]) -> Badge:
    """
    Derive the single render badge for a parent from its composition vector.

    composition: mapping of composition key (CW|MI|EX|NA|OPEN|ONM) to child count.
    Returns exactly one Badge per the S1R total order.

    A parent with zero children (empty or all-zero composition) resolves to NA.
    """
    if composition is None:
        composition = {}

    for k, v in composition.items():
        nk = _normalize_key(k)
        if nk not in COMPOSITION_KEYS:
            raise ValueError(
                f"rollup_badge received unknown code key: {k!r}; "
                f"allowed: {sorted(COMPOSITION_KEYS)}"
            )
        if type(v) is not int or v < 0:
            raise ValueError(
                f"rollup_badge count for {k!r} must be a non-negative int, got {v!r}"
            )

    def _count(key: str) -> int:
        total = 0
        for k, v in (composition or {}).items():
            if _normalize_key(k) == key:
                total += v
        return total

    if _count("OPEN") > 0:
        return Badge.OPEN
    if _count("EX") > 0:
        return Badge.EX
    if _count("ONM") > 0:
        return Badge.ONM
    if _count("MI") > 0:
        return Badge.MI

    cw = _count("CW")
    na = _count("NA")

    if cw > 0 and na > 0:
        return Badge.MIXED
    if cw > 0 and na == 0:
        return Badge.CW
    if na > 0 and cw == 0:
        return Badge.NA

    return Badge.NA


def compose_badge(
    child_codes: Iterable[str | DispositionCode | ExportLabel],
) -> Badge:
    """
    Convenience: given an iterable of child codes/labels, build a composition
    and return the roll-up badge.
    """
    comp: dict[str, int] = {}
    for raw in child_codes:
        key = _normalize_key(raw)
        if key not in COMPOSITION_KEYS:
            raise ValueError(f"Unknown child code in roll-up: {key}")
        comp[key] = comp.get(key, 0) + 1
    return rollup_badge(comp)
