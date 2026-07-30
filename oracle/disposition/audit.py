#!/usr/bin/env python3
"""
Module: oracle.disposition.audit
Purpose: Phase 3 FR-017 audit view — lineage from export row to source/facts/history.

Read-only navigation structure over session + event log + evidence + attestations.
Review decisions are read from the hash-chained event log (unit_attested /
review_decision); review_package.json is no longer used (F6).

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from oracle.disposition.evidence import EvidenceStore
from oracle.disposition.rulepack import RequirementRecord
from oracle.disposition.session import DispositionSession

LOGGER = logging.getLogger("oracle.disposition.audit")

_ATTEST_EVENT_TYPES = frozenset({"unit_attested", "review_decision"})


class AuditLineage(BaseModel):
    """One exported row's full lineage package."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    source_text: str
    locator: dict[str, Any]
    axes: dict[str, Any]
    export_label: Optional[str]
    comment: Optional[str]
    facts: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    review_decisions: list[dict[str, Any]] = Field(default_factory=list)
    open_actions: list[str] = Field(default_factory=list)


def _attestation_events_for_unit(
    session: DispositionSession, unit_id: str
) -> list[dict[str, Any]]:
    """Collect attestation events for a unit from the hash-chained log."""
    decisions: list[dict[str, Any]] = []
    for ev in session.eventlog.iter_events():
        p = ev.payload or {}
        if p.get("event_type") not in _ATTEST_EVENT_TYPES:
            continue
        if p.get("unit_id") != unit_id and ev.unit_id != unit_id:
            continue
        decisions.append(
            {
                "event_id": ev.event_id,
                "timestamp": ev.timestamp,
                "actor": ev.actor,
                "unit_id": p.get("unit_id") or unit_id,
                "decision": p.get("decision"),
                "role": p.get("role"),
                "comment": p.get("comment", ""),
                "accepted_with_tbd": p.get("accepted_with_tbd", False),
                "hash": ev.hash,
            }
        )
    return decisions


def build_lineage(
    unit_id: str,
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    *,
    evidence_store: Optional[EvidenceStore] = None,
) -> AuditLineage:
    if session.state is None:
        raise ValueError("Session not open")
    unit = session.state.units.get(unit_id)
    rec = records.get(unit_id)
    source = rec.shall_text if rec else ""
    locator = (
        rec.locator.model_dump()
        if rec
        else {"standard": "?", "revision": "?", "section": "?", "page": None}
    )
    axes = unit.model_dump() if unit else {}
    try:
        label = unit.export_label().value if unit else None
    except Exception:
        label = None

    facts = [
        f.model_dump(mode="json")
        for f in session.state.facts.values()
        if unit_id in f.unit_ids or not f.unit_ids
    ]
    assumptions = [f for f in facts if f.get("assumed")]

    evidence: list[dict[str, Any]] = []
    if evidence_store is not None:
        evidence = [a.model_dump(mode="json") for a in evidence_store.for_unit(unit_id)]
    elif unit:
        evidence = [e.model_dump(mode="json") for e in unit.evidence_refs]

    events = []
    for ev in session.eventlog.iter_events():
        if ev.unit_id == unit_id or (
            isinstance(ev.payload, dict)
            and (
                ev.payload.get("unit_id") == unit_id
                or (ev.payload.get("unit") or {}).get("unit_id") == unit_id
            )
        ):
            events.append(
                {
                    "event_id": ev.event_id,
                    "timestamp": ev.timestamp,
                    "actor": ev.actor,
                    "payload": ev.payload,
                    "hash": ev.hash,
                }
            )

    decisions = _attestation_events_for_unit(session, unit_id)

    return AuditLineage(
        unit_id=unit_id,
        source_text=source,
        locator=locator,
        axes=axes,
        export_label=label,
        comment=unit.comment if unit else None,
        facts=facts,
        evidence=evidence,
        assumptions=assumptions,
        events=events,
        review_decisions=decisions,
        open_actions=list(unit.open_actions) if unit else [],
    )


def audit_package(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    unit_ids: Optional[list[str]] = None,
    **kwargs: Any,
) -> list[AuditLineage]:
    if session.state is None:
        raise ValueError("Session not open")
    # Drop removed review_package kwarg if callers still pass it
    kwargs.pop("review_package", None)
    ids = unit_ids or sorted(session.state.units.keys())
    return [build_lineage(u, session, records, **kwargs) for u in ids]
