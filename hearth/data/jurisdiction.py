#!/usr/bin/env python3
"""
Module: hearth.data.jurisdiction
Purpose: JurisdictionPack — the local's rules, serialized (spec v0.3 §2.2).

A pack is a set of versioned, individually-signed micro-rules, each with
provenance and an effective-date window. Experts act as reviewers, not
authors. Rules without licensee/attorney review carry status "provisional"
and render under a provisional banner (§8); auto-invalidation flips rules
back to provisional when a monitored source changes (§2.2), which is why
status lives on each rule as well as on pack governance.

Safety Critical: False
Financially Critical: False (contract definition; consumers carry the risk)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

from collections import Counter
from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from hearth.data.base import HearthModel

RuleCategory = Literal["contract_deadline", "landmine", "commission_norm", "form"]
ReviewStatus = Literal["provisional", "reviewed", "deprecated"]


class AuthorityReview(HearthModel):
    """Human licensee/attorney sign-off on one rule (§2.2)."""

    reviewer: str
    license: str
    date: date


class MicroRule(HearthModel):
    """One versioned, signed micro-rule (§2.2)."""

    rule_id: str = Field(min_length=1)
    category: RuleCategory
    status: ReviewStatus = "provisional"
    effective_from: date
    effective_to: date | None = None
    source: str = Field(min_length=1)
    authority_review: AuthorityReview | None = None
    signature: str = Field(min_length=1)
    # payload is the one deliberately open surface in the schema: its shape
    # is category-specific (detection specs, deadline levers, landmine
    # thresholds) and consumers validate the parts they execute (§2.2).
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _reviewed_requires_authority(self) -> "MicroRule":
        # WHY: "reviewed" is a human attestation (§2.2/§8); a reviewed rule
        # with no named reviewer would let provisional content masquerade
        # as validated. Fail at parse time, not at render time.
        if self.status == "reviewed" and self.authority_review is None:
            raise ValueError(
                f"rule {self.rule_id}: status 'reviewed' requires authority_review"
            )
        return self

    def is_effective_on(self, day: date) -> bool:
        """True if `day` falls inside the rule's effective window."""
        if day < self.effective_from:
            return False
        return self.effective_to is None or day <= self.effective_to


class Jurisdiction(HearthModel):
    """Which law applies (§2.2 jurisdiction block)."""

    state: str = Field(min_length=2, max_length=2)
    county: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Governance(HearthModel):
    """Named accountability for pack freshness (§2.2 governance block)."""

    owner: str = Field(min_length=1)
    monitored_sources: list[str]
    update_sla_days: int = Field(gt=0)
    status: ReviewStatus


class JurisdictionPack(HearthModel):
    """Versioned micro-rule library for one jurisdiction (§2.2)."""

    jurisdiction: Jurisdiction
    governance: Governance
    rules: list[MicroRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _rule_ids_unique(self) -> "JurisdictionPack":
        # WHY: rule_id is the citation key for findings, audit trails and
        # renderer lookups; a duplicate would let two different rules
        # silently share one identity. Fail at parse time.
        counts = Counter(rule.rule_id for rule in self.rules)
        duplicates = sorted(rule_id for rule_id, n in counts.items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate rule_ids in pack: {duplicates}")
        return self

    @property
    def pack_id(self) -> str:
        """Stable citation handle, e.g. 'CO-Larimer@2026.06'."""
        j = self.jurisdiction
        return f"{j.state}-{j.county}@{j.version}"
