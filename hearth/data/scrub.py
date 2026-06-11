#!/usr/bin/env python3
"""
Module: hearth.data.scrub
Purpose: ScrubFinding — the Kelly module output, human-gated (spec v0.3 §2.5).

Every finding cites the JurisdictionPack rule that motivated it
(jurisdiction_basis) and is permanently marked requires_human_review.
Phase 1 runs findings-only (§8, §12): suggested_template is part of the
contract but is never populated until the §9 #3 counsel opinion clears the
generative-language path.

Category note: §2.5 enumerates fee|scope|backstop|default_trap|deadline|
waiver. "integrity" is added for fail-closed refusals (§3.3: unparseable
document → refuse finding, never silence) — none of the six §2.5 categories
describes "this document could not be analyzed". Deviation logged in
BUILD_NOTES.md.

Safety Critical: False
Financially Critical: False (contract definition; the scrubber engine that
  emits these is the financially-critical decider)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

from typing import Literal

from pydantic import Field

from hearth.data.base import HearthModel

FindingCategory = Literal[
    "fee", "scope", "backstop", "default_trap", "deadline", "waiver", "integrity"
]
FindingSeverity = Literal["info", "warn", "flag", "refuse"]

# Severity ordering for sorting/gating; refuse outranks everything.
SEVERITY_RANK: dict[str, int] = {"info": 0, "warn": 1, "flag": 2, "refuse": 3}

# Sentinel jurisdiction_basis for refusals that originate in the engine
# itself (parse failure, pack failure) rather than in any micro-rule.
FAIL_CLOSED_BASIS = "hearth.fail_closed"


class ScrubFinding(HearthModel):
    """One surfaced default with its evidence and exposure (§2.5)."""

    document: str
    clause_ref: str
    category: FindingCategory
    severity: FindingSeverity
    found: str
    default_analysis: str
    exposure_usd: int | None = None
    suggested_template: str | None = None
    # Literal[True]: §2.5 — "always true for template output", and HEARTH
    # never represents any finding as final buyer-specific legal advice.
    requires_human_review: Literal[True] = True
    jurisdiction_basis: str = Field(min_length=1)
