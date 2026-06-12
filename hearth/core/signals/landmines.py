#!/usr/bin/env python3
"""
Module: hearth.core.signals.landmines
Purpose: Landmine scan engine — evaluates data_query micro-rules against
         the evidence store (spec v0.3 §2.2, §3.1, §6; §13 P2-D).

This is where the P1-C landmine specs (metro-district mills, radon zone,
wildfire rating, well counts) stop being inert data. For each landmine
rule the engine joins the property's evidence (join-guarded, §2.3),
evaluates the rule's declared thresholds, and emits a PropertyAlert citing
the exact evidence rows. Three honest outcomes per rule — alert, clear,
insufficient_evidence — and the engine itself FAILS CLOSED: unknown
property, blocked join, malformed spec, or any internal error converges to
a refused ScanRun, never a hollow "no alerts".

Threshold vocabulary (detection.thresholds, evaluated against the best
evidence row — highest confidence, then most recent):
  {"severity": s, "gte": n}         numeric value >= n
  {"severity": s, "eq": v}          value == v (numeric or string)
  {"severity": s, "count_gte": n}   integer count >= n
  {"severity": s, "gte_rating": r}  ordinal rating >= r on the CSFS scale

Safety Critical: False
Financially Critical: True — a landmine scan that fails OPEN waves the
  buyer past a metro district or a well pad; never-suppress-error applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hearth.data import (
    SEVERITY_RANK,
    JurisdictionPack,
    MicroRule,
    PropertyAlert,
    PropertyEvidence,
    PropertyIdentity,
)
from hearth.db.evidence_store import EvidenceStore
from hearth.ingest.base import IngestError  # noqa: F401 - re-export convenience

LOGGER = logging.getLogger("hearth.core.signals.landmines")

DATA_QUERY = "data_query"

# CSFS-style ordinal wildfire scale (low → catastrophic exposure).
RATING_ORDER = ("low", "moderate", "high", "very_high")


class ScanSpecError(Exception):
    """A landmine rule's threshold spec is malformed; fail CLOSED."""


@dataclass(frozen=True)
class ScanRun:
    """Outcome of one landmine scan, refusals included."""

    property_uid: str
    identity: PropertyIdentity | None
    alerts: list[PropertyAlert]
    refused: bool
    pack_id: str | None
    contributing_rule_ids: list[str]
    run_date: date
    refusal_reason: str | None = field(default=None)


def scan_property(
    property_uid: str,
    store: EvidenceStore,
    pack: JurisdictionPack,
    *,
    run_date: date | None = None,
) -> ScanRun:
    """Evaluate every effective landmine rule. Never raises: failures refuse."""
    effective_date = run_date or date.today()
    try:
        identity = store.get_identity(property_uid)
        if identity is None:
            raise ScanSpecError(
                f"unknown property_uid {property_uid!r} — ingest the property "
                "before scanning (hearth ingest)"
            )
        rules = _landmine_rules(pack, effective_date)
        if not rules:
            raise ScanSpecError(
                f"pack {pack.pack_id} has no effective landmine rules — "
                "nothing can be asserted about this property"
            )
        # One join-guarded read up front: §2.3 blocks low-confidence joins
        # for the whole scan, not per field.
        all_rows = store.evidence_for(property_uid)
        alerts = [_evaluate_rule(rule, property_uid, all_rows) for rule in rules]
        return ScanRun(
            property_uid=property_uid,
            identity=identity,
            alerts=alerts,
            refused=False,
            pack_id=pack.pack_id,
            contributing_rule_ids=[a.rule_id for a in alerts],
            run_date=effective_date,
        )
    except Exception as exc:
        # Fail-closed boundary, same pattern as the scrubber engine: log
        # the full traceback, surface the failure as a refusal.
        LOGGER.exception("landmine scan failed closed for %s", property_uid)
        return ScanRun(
            property_uid=property_uid,
            identity=None,
            alerts=[],
            refused=True,
            pack_id=pack.pack_id,
            contributing_rule_ids=[],
            run_date=effective_date,
            refusal_reason=str(exc) or exc.__class__.__name__,
        )


def refusal_scan(
    property_ref: str,
    *,
    reason: str,
    pack: JurisdictionPack | None = None,
    run_date: date | None = None,
) -> ScanRun:
    """Canonical fail-closed scan outcome for pre-engine failures (bad pack,
    unusable store, unresolvable property reference)."""
    return ScanRun(
        property_uid=property_ref,
        identity=None,
        alerts=[],
        refused=True,
        pack_id=pack.pack_id if pack is not None else None,
        contributing_rule_ids=[],
        run_date=run_date or date.today(),
        refusal_reason=reason,
    )


def _landmine_rules(pack: JurisdictionPack, run_date: date) -> list[MicroRule]:
    return [
        rule
        for rule in pack.rules
        if rule.category == "landmine"
        and rule.is_effective_on(run_date)
        and isinstance(rule.payload.get("detection"), dict)
        and rule.payload["detection"].get("type") == DATA_QUERY
    ]


def _evaluate_rule(
    rule: MicroRule, property_uid: str, all_rows: list[PropertyEvidence]
) -> PropertyAlert:
    detection = rule.payload["detection"]
    query_field = detection.get("query_field")
    if not isinstance(query_field, str) or not query_field:
        raise ScanSpecError(f"rule {rule.rule_id}: detection.query_field missing")
    summary = str(rule.payload.get("summary", rule.rule_id))
    analysis = str(rule.payload.get("analysis", ""))

    rows = [row for row in all_rows if row.field == query_field]
    if not rows:
        return PropertyAlert(
            property_uid=property_uid,
            rule_id=rule.rule_id,
            status="insufficient_evidence",
            severity=None,
            summary=summary,
            analysis=(
                f"No evidence rows for '{query_field}'. This rule could not "
                "be evaluated — obtain the data (adapter or buyer-supplied "
                "entry) before treating it as clear (§3.1: never assume past "
                "the data)."
            ),
            evidence=[],
        )

    # Newest row wins ties on (confidence, retrieved): a same-day
    # correction must beat the stale entry it corrects (P3 review m3).
    best = max(
        enumerate(rows),
        key=lambda pair: (pair[1].confidence, pair[1].retrieved, pair[0]),
    )[1]
    severity = _strongest_matching_severity(rule, detection, best.value)
    if severity is None:
        return PropertyAlert(
            property_uid=property_uid,
            rule_id=rule.rule_id,
            status="clear",
            severity=None,
            summary=summary,
            analysis=(
                f"'{query_field}' = {best.value!r} is below every declared "
                f"threshold. Basis: {analysis}"
            ),
            evidence=[best],
        )
    return PropertyAlert(
        property_uid=property_uid,
        rule_id=rule.rule_id,
        status="alert",
        severity=severity,
        summary=summary,
        analysis=analysis,
        evidence=[best],
    )


def _strongest_matching_severity(
    rule: MicroRule, detection: dict[str, Any], value: int | float | str
) -> str | None:
    thresholds = detection.get("thresholds")
    if not isinstance(thresholds, list) or not thresholds:
        raise ScanSpecError(f"rule {rule.rule_id}: detection.thresholds missing")
    matched: list[str] = []
    for threshold in thresholds:
        if not isinstance(threshold, dict) or "severity" not in threshold:
            raise ScanSpecError(
                f"rule {rule.rule_id}: malformed threshold {threshold!r}"
            )
        if _matches(rule, threshold, value):
            matched.append(str(threshold["severity"]))
    if not matched:
        return None
    return max(matched, key=lambda s: SEVERITY_RANK.get(s, -1))


def _matches(rule: MicroRule, threshold: dict[str, Any], value) -> bool:
    if "gte" in threshold:
        return _as_number(rule, value) >= _as_number(rule, threshold["gte"])
    if "count_gte" in threshold:
        return _as_number(rule, value) >= _as_number(rule, threshold["count_gte"])
    if "eq_any" in threshold:
        options = threshold["eq_any"]
        if not isinstance(options, list) or not options:
            raise ScanSpecError(f"rule {rule.rule_id}: eq_any must be a non-empty list")
        cleaned = _normalize_label(value)
        return any(cleaned == _normalize_label(option) for option in options)
    if "eq" in threshold:
        expected = threshold["eq"]
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            return _as_number(rule, value) == float(expected)
        return str(value).strip().lower() == str(expected).strip().lower()
    if "gte_rating" in threshold:
        return _rating_index(rule, value) >= _rating_index(rule, threshold["gte_rating"])
    raise ScanSpecError(
        f"rule {rule.rule_id}: threshold has no known comparator: {threshold!r}"
    )


def _normalize_label(value) -> str:
    """Buyer-typed labels arrive as 'Zone AE', 'X (shaded)', 'x500'…;
    normalize before comparing so a real transcription never silently
    clears a flood flag (P3 review M2)."""
    text = str(value).strip().lower()
    if text.startswith("zone "):
        text = text[len("zone "):]
    return text.replace("(", "").replace(")", "").replace("-", " ").replace("  ", " ").strip()


def _as_number(rule: MicroRule, value) -> float:
    if isinstance(value, bool):
        # bool would coerce to 0/1 and silently satisfy numeric thresholds.
        raise ScanSpecError(f"rule {rule.rule_id}: boolean is not a numeric value")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ScanSpecError(
            f"rule {rule.rule_id}: expected numeric value, got {value!r}"
        ) from exc


def _rating_index(rule: MicroRule, value) -> int:
    rating = str(value).strip().lower().replace(" ", "_")
    if rating not in RATING_ORDER:
        raise ScanSpecError(
            f"rule {rule.rule_id}: unknown rating {value!r} "
            f"(known: {', '.join(RATING_ORDER)})"
        )
    return RATING_ORDER.index(rating)
