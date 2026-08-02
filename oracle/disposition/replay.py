#!/usr/bin/env python3
"""
Module: oracle.disposition.replay
Purpose: CR3 — the identity-first corpus-replay golden.

Drives a REAL session through the normal gated APIs from an adjudicated
corpus (evidence registration, work packages, actions, elections,
attestations), then compares the ENGINE-DERIVED contract code and
readiness label of every row against the corpus's locked identities.
Tallies are computed for reporting only (Fran ruling 2026-08-02) —
mismatched rows, not mismatched totals, are the failures.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from oracle.disposition.actions import ActionRecord
from oracle.disposition.corpus import (
    CorpusError,
    CorpusRow,
    assert_reconciled,
    load_corpus,
    load_work_packages,
    scan_work_packages,
)
from oracle.disposition.readiness import map_readiness
from oracle.disposition.session import DispositionSession, EvidenceRef, SessionError

LOGGER = logging.getLogger("oracle.disposition.replay")

# §7.1 label -> contract code, as the corpus speaks codes
LABEL_TO_CODE = {
    "Meet": "CW",
    "Meets Intent": "MI",
    "Exception": "EX",
    "N/A": "NA",
    "TBD": "OPEN",
    "Open/Not Met": "OPEN",
}
# readiness enum -> corpus canonical vocabulary
READINESS_TO_CORPUS = {
    "Met": "Met",
    "Not Met with Plan": "Not Met with Plan",
    "TBD Verify": "TBD",
    "External Action": "Program Action",
    "Technical N/A": "Technical N/A",
    "Not Yet Due": "Not Yet Due",
}
_TRUTHY = {"yes", "y", "true", "1"}


class ReplayMismatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    kind: str  # contract | readiness | election | unknown_id
    expected: str
    derived: str


class ReplayReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: int
    replayed: int
    mismatches: list[ReplayMismatch] = Field(default_factory=list)
    comment_refusals: list[str] = Field(default_factory=list)
    contract_tally: dict[str, int] = Field(default_factory=dict)
    readiness_tally: dict[str, int] = Field(default_factory=dict)
    work_packages: int = 0

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _election_kwargs(row: CorpusRow) -> dict[str, Any]:
    """Corpus row -> set_axes kwargs (split axes preferred; gate fields)."""
    kw: dict[str, Any] = {}
    for f in ("applicability", "organization_responsibility", "approval_state"):
        v = getattr(row, f)
        if v:
            kw[f] = v
    if row.obligated_actor:
        kw["obligated_actor"] = row.obligated_actor
    if row.fulfillment_path or row.execution_state:
        # both-or-neither: a half-split row must refuse loudly, never
        # replay on a defaulted axis (Atlas CR High 3)
        if not (row.fulfillment_path and row.execution_state):
            raise ValueError(
                f"{row.requirement_id}: split axes must be elected together "
                f"(fulfillment={row.fulfillment_path!r}, "
                f"execution={row.execution_state!r})"
            )
        kw["fulfillment_path"] = row.fulfillment_path
        kw["execution_state"] = row.execution_state
    elif row.implementation_state:
        kw["implementation_state"] = row.implementation_state
    for f in (
        "scope_citation",
        "intent_statement",
        "alternative_control",
        "control_class",
        "exception_basis",
        "permanent_relief_basis",
        "not_yet_due_justification",
    ):
        v = getattr(row, f)
        if v:
            kw[f] = v
    if row.closure_action_id:
        kw["closure_path_action_id"] = row.closure_action_id
    if row.not_yet_due.strip().lower() in _TRUTHY:
        kw["not_yet_due"] = True
    return kw


def _register_row_evidence(
    session: DispositionSession, row: CorpusRow, actor: str
) -> None:
    for ref in (r.strip() for r in row.evidence_refs.split(";") if r.strip()):
        doc, _, rev = ref.partition("@")
        doc, rev = doc.strip(), (rev.strip() or "-")
        session.register_evidence(
            # unique per row: the registry is last-wins by evidence_id, so
            # a shared default id would unlink earlier rows citing the
            # same document
            evidence_id=f"EV-{row.requirement_id}-{doc}",
            doc_id=doc,
            revision=rev,
            unit_ids=(row.requirement_id,),
            effective_date=row.evidence_date or None,
            approval_date=row.evidence_date or None,
        )
        session.attach_evidence(
            row.requirement_id, EvidenceRef(doc_id=doc, revision=rev), actor
        )


def _record_row_actions(
    session: DispositionSession,
    row: CorpusRow,
    wp_by_id: dict[str, Any],
    recorded: dict[str, list[str]],
) -> None:
    """Actions come from the corpus's action ids; a work package with the
    same id supplies the plan-quality fields. An id with no work package
    stays non-plan — if the row then misses its readiness, that is a
    CORPUS gap surfaced honestly, never papered over here."""
    for aid in row.action_ids:
        recorded.setdefault(aid, []).append(row.requirement_id)


def _flush_actions(
    session: DispositionSession,
    wp_by_id: dict[str, Any],
    recorded: dict[str, list[str]],
    actor: str,
) -> None:
    for aid, uids in recorded.items():
        wp = wp_by_id.get(aid)
        session.record_action(
            ActionRecord(
                action_id=aid,
                title=(wp.title if wp else f"Corpus action {aid}"),
                owner=(wp.owner if wp else ""),
                deliverable=(wp.deliverables if wp else ""),
                exit_criteria=(wp.exit_criteria if wp else ""),
                work_package=(wp.wp_id if wp else ""),
                affected_unit_ids=tuple(uids),
            ),
            actor_name=actor,
        )


def replay_corpus(
    corpus_path: Path | str,
    session_dir: Path | str,
    *,
    actor_name: str = "replay",
) -> ReplayReport:
    """Replay the adjudicated corpus through a real session; compare
    engine-derived labels against the locked row identities."""
    rows = load_corpus(corpus_path)
    # Atlas CR High 3: the acceptance harness enforces the SAME floor the
    # public checker does — coherence + unique identities — before any
    # row touches a session. A row the floor refuses never replays.
    assert_reconciled(rows)
    wps = load_work_packages(corpus_path)
    # Atlas CR Medium 4: the sibling file crosses the same D-3 boundary
    # as the corpus — refuse identifier hits before persistence.
    wp_hits = scan_work_packages(wps)
    if wp_hits:
        raise CorpusError(
            f"work packages carry identifier hits (D-3): {wp_hits[:5]}"
        )
    wp_by_id = {w.wp_id: w for w in wps}

    session = DispositionSession(session_dir)
    session.open(actor_name=actor_name)
    assert session.state is not None
    for wp in wps:
        session.record_work_package(wp, actor_name=actor_name)

    report = ReplayReport(rows=len(rows), replayed=0, work_packages=len(wps))

    # evidence + action collection first: elections gate on both
    recorded_actions: dict[str, list[str]] = {}
    for row in rows:
        if row.requirement_id not in session.state.units:
            report.mismatches.append(
                ReplayMismatch(
                    requirement_id=row.requirement_id,
                    kind="unknown_id",
                    expected="unit in session",
                    derived="absent from pack",
                )
            )
            continue
        _register_row_evidence(session, row, actor_name)
        _record_row_actions(session, row, wp_by_id, recorded_actions)
    _flush_actions(session, wp_by_id, recorded_actions, actor_name)

    for row in rows:
        uid = row.requirement_id
        if uid not in session.state.units:
            continue
        try:
            session.set_axes(uid, actor_name=actor_name, **_election_kwargs(row))
        except (SessionError, ValueError) as e:
            report.mismatches.append(
                ReplayMismatch(
                    requirement_id=uid,
                    kind="election",
                    expected="gated election accepted",
                    derived=str(e)[:140],
                )
            )
            continue
        if row.comment:
            try:
                session.set_axes(
                    uid,
                    actor_name=actor_name,
                    comment=row.comment,
                    comment_status="accepted",
                    election=False,
                )
            except SessionError as e:
                report.comment_refusals.append(f"{uid}: {str(e)[:120]}")
        unit = session.state.units[uid]
        has_tbd = (
            unit.applicability == "tbd"
            or unit.organization_responsibility == "tbd"
            or unit.execution_state == "tbd"
            or unit.approval_state == "tbd"
        )
        session.attest_unit(
            uid,
            actor_name=actor_name,
            role="disposition_author",
            decision="accepted",
            accepted_with_tbd=has_tbd,
        )

        unit = session.state.units[uid]
        derived_code = LABEL_TO_CODE.get(unit.export_label().value, "OPEN")
        if derived_code != row.contract_label:
            report.mismatches.append(
                ReplayMismatch(
                    requirement_id=uid,
                    kind="contract",
                    expected=row.contract_label,
                    derived=derived_code,
                )
            )
        acts = session.actions_for_unit(uid)
        rr = map_readiness(
            unit,
            acts,
            has_qualifying_evidence=session.has_qualifying_meet_evidence(unit),
        )
        derived_ready = READINESS_TO_CORPUS.get(rr.label.value, rr.label.value)
        if derived_ready != row.readiness_label:
            report.mismatches.append(
                ReplayMismatch(
                    requirement_id=uid,
                    kind="readiness",
                    expected=row.readiness_label,
                    derived=derived_ready,
                )
            )
        report.replayed += 1

    report.contract_tally = dict(Counter(r.contract_label for r in rows))
    report.readiness_tally = dict(Counter(r.readiness_label for r in rows))
    LOGGER.info(
        "Replay: %d/%d rows, %d mismatches, %d WPs",
        report.replayed,
        report.rows,
        len(report.mismatches),
        report.work_packages,
    )
    return report
