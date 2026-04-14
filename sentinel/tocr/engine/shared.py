"""
Module: Shared Engine Constants
Purpose: Single source of truth for constants and utilities shared across TOCR engines.

BoundState AI 2026
Classification: BoundState Proprietary

__safety_critical__: bool = True

Why this module exists: rule_engine.py and scan_engine.py both compute
urgency signals, cost-overlap signals, and rule applicability filtering
using identical constants and logic.  Centralizing here prevents drift
between the diff-based (RuleEngine) and scan-based (ScanEngine) pipelines.

Spec: BS-SPEC-TOCR-001, Section 2 (Signal Computation)
"""

__safety_critical__: bool = True

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel.tocr.models.config import ContractConfig
    from sentinel.tocr.models.rules import TOCRRule


# ---------------------------------------------------------------------------
# Urgency indicators — FAR 16.505(b)(4) substance check
# ---------------------------------------------------------------------------
# Why these phrases: FAR 16.505(b)(4) requires emergency/sole-source
# justifications to explain (1) why this is urgent, (2) why normal procedures
# cannot be followed, and (3) what harm results from delay.  These phrases
# detect whether the justification addresses substance vs. merely restating
# the scope change.  Curated from 200+ NASA MSFC ESSCA task order reviews.

URGENCY_INDICATORS: list[str] = [
    "urgent", "urgency", "immediate", "immediately", "critical path",
    "safety", "safety concern", "hazard", "risk to",
    "cannot wait", "cannot delay", "time-sensitive", "time sensitive",
    "deadline", "window", "launch window", "test window",
    "hardware at risk", "schedule impact", "schedule pressure",
    "mission impact", "mission critical", "flight hardware",
    "delay would", "delay will", "if delayed", "cannot be delayed",
    "normal procedures cannot", "normal process cannot",
    "standard process would", "standard review would",
    "unacceptable delay", "unacceptable risk",
    "life safety", "crew safety", "loss of",
]

# ---------------------------------------------------------------------------
# Stopwords — English + common ESSCA/NASA contract boilerplate
# ---------------------------------------------------------------------------
# Why two tiers: disclosure_engine uses English-only stopwords because its
# overlap check needs to detect whether a change summary describes the SAME
# change (content words matter).  rule_engine and scan_engine use the expanded
# set because their cost-overlap check compares sub-task descriptions where
# contract boilerplate creates false positives.

ENGLISH_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "for", "of", "in", "to", "is",
    "with", "be", "are", "was", "were", "will", "shall", "by", "at",
    "on", "as", "it", "this", "that", "from", "not", "but", "all",
    "has", "have", "had", "may", "can", "its", "per", "any", "each",
})

CONTRACT_STOPWORDS: frozenset[str] = ENGLISH_STOPWORDS | frozenset({
    "contractor", "provide", "services", "support", "activities",
    "include", "following", "materials", "evaluation", "assessment",
    "required", "engineering", "effort", "task", "work", "perform",
    "shall", "including", "necessary", "processes", "laboratory",
    "office", "design", "analysis", "test", "testing", "development",
})


# ---------------------------------------------------------------------------
# Rule applicability filtering
# ---------------------------------------------------------------------------
# Why shared: RuleEngine and ScanEngine both filter rules against a
# ContractConfig using the same 5-gate check (contract_type, agency,
# local_pack, clause_required, revision_status).  Divergence between
# these two paths would cause the same rule to fire in scan mode but
# not in review mode (or vice versa), which is a correctness bug.

def filter_applicable_rules(
    rules: list[TOCRRule],
    config: ContractConfig,
    suppression_log: list[dict],
) -> list[TOCRRule]:
    """Filter rules by contract config applicability.

    Returns only rules whose applicability criteria match the given config.
    Rejected rules are appended to suppression_log with the reason.
    """
    applicable = []
    for rule in rules:
        app = rule.applicability

        if not config.matches_contract_type(app.contract_type):
            suppression_log.append({
                "rule_id": rule.rule_id,
                "reason": f"Contract type mismatch: {app.contract_type}",
            })
            continue

        if app.agency and not any(config.matches_agency(a) for a in app.agency):
            suppression_log.append({
                "rule_id": rule.rule_id,
                "reason": f"Agency mismatch: {app.agency}",
            })
            continue

        if app.local_pack and not any(config.matches_local_pack(p) for p in app.local_pack):
            suppression_log.append({
                "rule_id": rule.rule_id,
                "reason": f"Local pack mismatch: {app.local_pack}",
            })
            continue

        if app.clause_required and not all(config.has_clause(c) for c in app.clause_required):
            suppression_log.append({
                "rule_id": rule.rule_id,
                "reason": f"Missing required clause: {app.clause_required}",
            })
            continue

        if not config.matches_revision_status(app.revision_status):
            suppression_log.append({
                "rule_id": rule.rule_id,
                "reason": f"Revision status mismatch: {app.revision_status}",
            })
            continue

        applicable.append(rule)

    return applicable


def trigger_matches(rule: TOCRRule, signals: set[str]) -> bool:
    """Check if a rule's trigger conditions are met by the given signal set.

    ALL conditions must be satisfied, then at least one ANY condition
    (if specified).  Rules with no trigger conditions never fire.
    """
    trigger = rule.trigger

    if trigger.all and not all(sig in signals for sig in trigger.all):
        return False

    if trigger.any and not any(sig in signals for sig in trigger.any):
        return False

    # Rules with no conditions are inert — they need at least one gate
    if not trigger.all and not trigger.any:
        return False

    return True
