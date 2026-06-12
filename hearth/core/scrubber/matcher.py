#!/usr/bin/env python3
"""
Module: hearth.core.scrubber.matcher
Purpose: Deterministic template diff — micro-rule detection against clauses
         (spec v0.3 §3.3: high precision on known forms).

Rules are data, the matcher is generic: a rule's payload carries a
`detection` spec and the matcher executes it. No rule logic is hardcoded
here — "no hardcoded triggers" is an integrity rule (§6), so adding a
detection means adding a signed micro-rule, never editing this module.

Detection spec (payload["detection"]):
  {"type": "clause_regex", "all_of": ["<regex>", ...]}
A clause matches when every all_of pattern finds a hit in the clause text
(IGNORECASE/DOTALL). Named groups in any pattern (e.g. (?P<fee_pct>...))
become document-scoped captures used for exposure math.

Other detection types ("data_query" landmine specs, §12 P1-C) are data for
future adapters; executable_rules() filters them out explicitly.

Safety Critical: False
Financially Critical: True — a malformed spec must raise, never skip;
  never-suppress-error pattern applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
import re
from dataclasses import dataclass
from typing import Any

from hearth.core.scrubber.segmentation import Clause
from hearth.data import MicroRule

LOGGER = logging.getLogger("hearth.core.scrubber.matcher")

CLAUSE_REGEX = "clause_regex"

# Deterministic findings may only use §2.5 document categories at sub-refuse
# severity; "integrity"/"refuse" are reserved for the fail-closed path.
ALLOWED_FINDING_CATEGORIES = {"fee", "scope", "backstop", "default_trap", "deadline", "waiver"}
ALLOWED_FINDING_SEVERITIES = {"info", "warn", "flag"}

KNOWN_EXPOSURE_METHODS = {"pct_capture_times_target_price"}


class MatchSpecError(Exception):
    """A rule's detection/finding spec is malformed; fail CLOSED."""


@dataclass(frozen=True)
class RuleMatch:
    """One rule firing on one clause."""

    rule: MicroRule
    clause: Clause
    captures: dict[str, str]


def detection_type(rule: MicroRule) -> str | None:
    detection = rule.payload.get("detection")
    if not isinstance(detection, dict):
        return None
    kind = detection.get("type")
    return kind if isinstance(kind, str) else None


def executable_rules(rules: list[MicroRule]) -> list[MicroRule]:
    """Rules the deterministic stage can execute (clause_regex only in P1)."""
    executable = []
    for rule in rules:
        if detection_type(rule) == CLAUSE_REGEX:
            executable.append(rule)
        else:
            LOGGER.debug(
                "rule %s detection type %r is not executable in the "
                "deterministic stage (data spec for a future adapter)",
                rule.rule_id,
                detection_type(rule),
            )
    return executable


def compile_detection(rule: MicroRule) -> list[re.Pattern[str]]:
    """Compile a clause_regex rule's patterns; MatchSpecError on any defect."""
    detection = rule.payload.get("detection")
    if not isinstance(detection, dict) or detection.get("type") != CLAUSE_REGEX:
        raise MatchSpecError(f"rule {rule.rule_id}: not a clause_regex detection")
    patterns = detection.get("all_of")
    if not isinstance(patterns, list) or not patterns:
        raise MatchSpecError(f"rule {rule.rule_id}: detection.all_of must be a non-empty list")
    compiled = []
    for raw in patterns:
        if not isinstance(raw, str):
            raise MatchSpecError(f"rule {rule.rule_id}: non-string pattern {raw!r}")
        try:
            compiled.append(re.compile(raw, re.IGNORECASE | re.DOTALL))
        except re.error as exc:
            raise MatchSpecError(f"rule {rule.rule_id}: bad regex {raw!r}: {exc}") from exc
    return compiled


def validate_finding_spec(rule: MicroRule) -> dict[str, Any]:
    """Validate the payload.finding block; MatchSpecError on any defect."""
    finding = rule.payload.get("finding")
    if not isinstance(finding, dict):
        raise MatchSpecError(f"rule {rule.rule_id}: payload.finding missing")
    if finding.get("category") not in ALLOWED_FINDING_CATEGORIES:
        raise MatchSpecError(
            f"rule {rule.rule_id}: finding.category {finding.get('category')!r} "
            f"not in {sorted(ALLOWED_FINDING_CATEGORIES)}"
        )
    if finding.get("severity") not in ALLOWED_FINDING_SEVERITIES:
        raise MatchSpecError(
            f"rule {rule.rule_id}: finding.severity {finding.get('severity')!r} "
            f"not in {sorted(ALLOWED_FINDING_SEVERITIES)} "
            "(refuse is reserved for the fail-closed path)"
        )
    analysis = finding.get("default_analysis")
    if not isinstance(analysis, str) or not analysis.strip():
        raise MatchSpecError(f"rule {rule.rule_id}: finding.default_analysis missing")
    exposure = finding.get("exposure")
    if exposure is not None:
        if not isinstance(exposure, dict) or exposure.get("method") not in KNOWN_EXPOSURE_METHODS:
            raise MatchSpecError(
                f"rule {rule.rule_id}: unknown exposure spec {exposure!r}"
            )
        # §13 P2-A: cross-rule capture dependencies must be declared, and a
        # declaration must be a rule id string (existence is checked by the
        # pack loader, which can see the whole pack).
        origin = exposure.get("capture_from_rule")
        if origin is not None and (not isinstance(origin, str) or not origin):
            raise MatchSpecError(
                f"rule {rule.rule_id}: capture_from_rule must be a rule id string"
            )
    return finding


def match_rules(clauses: list[Clause], rules: list[MicroRule]) -> list[RuleMatch]:
    """Run every executable rule over every clause, in document order."""
    matches: list[RuleMatch] = []
    for clause in clauses:
        for rule in rules:
            captures = _match_one(rule, clause)
            if captures is not None:
                LOGGER.debug("rule %s fired on %s", rule.rule_id, clause.ref)
                matches.append(RuleMatch(rule=rule, clause=clause, captures=captures))
    return matches


def _match_one(rule: MicroRule, clause: Clause) -> dict[str, str] | None:
    """Captures dict if every pattern hits the clause, else None."""
    captures: dict[str, str] = {}
    for pattern in compile_detection(rule):
        hit = pattern.search(clause.text)
        if hit is None:
            return None
        for name, value in hit.groupdict().items():
            if value is not None:
                captures.setdefault(name, value)
    return captures


def collect_document_captures(matches: list[RuleMatch]) -> dict[str, str]:
    """Document-scoped captures, first occurrence wins (document order)."""
    captures: dict[str, str] = {}
    for match in matches:
        for name, value in match.captures.items():
            captures.setdefault(name, value)
    return captures
