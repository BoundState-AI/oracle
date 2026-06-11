#!/usr/bin/env python3
"""
Module: hearth.core.scrubber.analyzer
Purpose: ClauseAnalyzer protocol — the LLM stage, STUBBED in Phase 1
         (spec v0.3 §3.3, §12 P1-B).

The deterministic template diff (matcher) handles known forms with high
precision; novel documents eventually get LLM clause analysis behind this
protocol. Phase 1 ships NO LLM calls: NullClauseAnalyzer is the only
implementation and always returns no findings.

Trust-boundary constraint for every future implementation (§1.1, §3.3):
any analysis stage that can see BuyerPack or buyer-identifying context
MUST run on local models. A third-party-API analyzer that receives buyer
context is a build-failing boundary violation (§12 P1-D).

Safety Critical: False
Financially Critical: True — analyzer findings drive buyer decisions.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
from typing import Protocol, runtime_checkable

from hearth.core.scrubber.segmentation import Clause
from hearth.data import JurisdictionPack, ScrubFinding

LOGGER = logging.getLogger("hearth.core.scrubber.analyzer")


@runtime_checkable
class ClauseAnalyzer(Protocol):
    """Pluggable clause-analysis stage (LLM in later phases)."""

    def analyze(
        self, clauses: list[Clause], pack: JurisdictionPack
    ) -> list[ScrubFinding]:
        """Return additional findings for the given clauses."""
        ...  # pragma: no cover - protocol definition


class NullClauseAnalyzer:
    """P1 stub: deterministic-only pipeline, no model, no findings."""

    def analyze(
        self, clauses: list[Clause], pack: JurisdictionPack
    ) -> list[ScrubFinding]:
        LOGGER.debug("NullClauseAnalyzer: %d clauses, 0 findings (P1 stub)", len(clauses))
        return []
