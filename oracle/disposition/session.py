#!/usr/bin/env python3
"""
Module: oracle.disposition.session
Purpose: Project context, fact ledger, and RDW interview session store.

Persistence reuses EventLog (hash-chained JSONL) + single-writer lock /
temp-rename patterns from store.py. Reload = replay. No mutation of prior
lines. Assumptions are facts with assumed=True and never auto-confirm.

Safety Critical: advisory-only per spec D-1 (session is not the release gate)
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from oracle.disposition.codes import (
    Applicability,
    ApprovalState,
    ExportLabel,
    ImplementationState,
    ObligatedActor,
    OrgResponsibility,
    ProposalBand,
    TBDReason,
)
from oracle.disposition.eventlog import EventLog, EventLogError
from oracle.disposition.export_map import AxisSnapshot, map_axes_to_export_label
from oracle.disposition.models import CapabilityModelEntry
from oracle.disposition.graph import DependencyGraph
from oracle.disposition.rulepack import (
    PackPinError,
    RequirementRecord,
    content_hash_path,
    load_requirement_records,
    prerequisites_of,
)
from oracle.disposition.packs import load_rdw_default_packs

LOGGER = logging.getLogger("oracle.disposition.session")

SESSION_SCHEMA = "disposition-session/v1"
CONFIDENCE = Literal["high", "medium", "low"]
FACT_KIND = Literal["asserted", "inferred", "evidenced"]


class SessionError(Exception):
    """Base session error (fail closed)."""


class SessionLockError(SessionError):
    """Another writer holds the session lock."""


# ---------------------------------------------------------------------------
# Project context (RDW §9.2)
# ---------------------------------------------------------------------------


class Organization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str  # customer | program | producer | supplier | subtier
    name: str
    assumed_ceo: bool = False
    confirmed: bool = False


class PlanPresence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str  # AMCP | EFCP | QMP | PPP | ...
    present: bool
    note: str = ""


class ClassificationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_class: Optional[str] = None
    secondary_class: Optional[str] = None
    fracture_control: Optional[str] = None
    tbd: bool = True
    tbd_reason: Optional[TBDReason] = TBDReason.CLASSIFICATION_UNRESOLVED


class ProjectContext(BaseModel):
    """RDW §9.2 project context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    organizations: tuple[Organization, ...] = ()
    hardware_process: Optional[str] = None  # e.g. cold spray
    hardware_level: Optional[str] = None
    classification: ClassificationState = Field(default_factory=ClassificationState)
    plans: tuple[PlanPresence, ...] = ()
    subtiers: tuple[str, ...] = ()
    capabilities: tuple[CapabilityModelEntry, ...] = ()
    intake_complete: bool = False


def seed_context_appendix_b() -> ProjectContext:
    """Scrubbed RDW Appendix B seed context."""
    return ProjectContext(
        organizations=(
            Organization(role="customer", name="Customer (prime)", assumed_ceo=True, confirmed=False),
            Organization(
                role="producer",
                name="Supplier (cold-spray producer)",
                assumed_ceo=False,
                confirmed=True,
            ),
        ),
        hardware_process="Cold spray",
        hardware_level="Functional subassembly",
        classification=ClassificationState(
            primary_class=None,
            secondary_class=None,
            fracture_control=None,
            tbd=True,
            tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
        ),
        plans=(
            PlanPresence(plan_id="AMCP", present=False, note="Not observed"),
            PlanPresence(plan_id="EFCP", present=False, note="Not present per current knowledge"),
        ),
        subtiers=("Powder", "testing", "heat treatment/HIP", "NDT"),
        capabilities=(),
        intake_complete=False,
    )


# ---------------------------------------------------------------------------
# Facts + evidence refs
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """v0 typed reference only — no file storage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    revision: str
    date: Optional[str] = None
    note: str = ""


class Fact(BaseModel):
    """Asserted/inferred/evidenced fact with supersession chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    key: str  # stable key e.g. classification.primary
    statement: str
    kind: FACT_KIND = "asserted"
    author: str
    timestamp: str
    source: str = "interview"
    confidence: CONFIDENCE = "medium"
    assumed: bool = False
    owner: Optional[str] = None  # required when assumed=True
    supersedes: Optional[str] = None
    confirmed: bool = False  # assumptions never silently become True
    unit_ids: tuple[str, ...] = ()  # affected requirements

    @field_validator("owner")
    @classmethod
    def _assumed_needs_owner(cls, v: Optional[str], info) -> Optional[str]:
        return v


class UnitAxesState(BaseModel):
    """Per-unit axis election state (session-level, not release package)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    applicability: Applicability = "tbd"
    obligated_actor: Optional[ObligatedActor] = None
    organization_responsibility: OrgResponsibility = "tbd"
    implementation_state: ImplementationState = "tbd"
    approval_state: ApprovalState = "tbd"
    applicability_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    org_responsibility_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    implementation_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    approval_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    scope_citation: Optional[str] = None  # required for N/A (FR-009)
    accepted_with_tbd: bool = False  # review coherence election
    review_state: Literal[
        "not_reviewed", "proposed", "in_review", "accepted", "rejected", "superseded"
    ] = "proposed"
    comment: Optional[str] = None
    comment_status: Literal["proposed", "accepted", "edited"] = "proposed"
    evidence_refs: tuple[EvidenceRef, ...] = ()
    open_actions: tuple[str, ...] = ()
    actor_name: Optional[str] = None

    def snapshot(self) -> AxisSnapshot:
        return AxisSnapshot(
            applicability=self.applicability,
            obligated_actor=self.obligated_actor,
            organization_responsibility=self.organization_responsibility,
            implementation_state=self.implementation_state,
            approval_state=self.approval_state,
            applicability_tbd_reason=self.applicability_tbd_reason
            if self.applicability == "tbd"
            else None,
            org_responsibility_tbd_reason=self.org_responsibility_tbd_reason
            if self.organization_responsibility == "tbd"
            else None,
            implementation_tbd_reason=self.implementation_tbd_reason
            if self.implementation_state == "tbd"
            else None,
            approval_tbd_reason=self.approval_tbd_reason
            if self.approval_state == "tbd"
            else None,
        )

    def export_label(self) -> ExportLabel:
        return map_axes_to_export_label(self.snapshot())


class SessionState(BaseModel):
    """In-memory session reconstructed by replaying the event log."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    pack_id: str
    pack_hash: str
    actor_name: str
    context: ProjectContext = Field(default_factory=seed_context_appendix_b)
    facts: dict[str, Fact] = Field(default_factory=dict)  # key -> head fact
    facts_by_id: dict[str, Fact] = Field(default_factory=dict)
    units: dict[str, UnitAxesState] = Field(default_factory=dict)
    paired_answers: dict[str, str] = Field(default_factory=dict)  # question_key -> answer
    exports: list[dict[str, Any]] = Field(default_factory=list)
    needs_rereview: list[str] = Field(default_factory=list)  # durable via event replay
    rereview_diffs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    schema_version: str = SESSION_SCHEMA


# ---------------------------------------------------------------------------
# Session store (extends EventLog; no parallel persistence)
# ---------------------------------------------------------------------------


class DispositionSession:
    """
    Append-only session backed by EventLog under a session root.

    Layout:
      <root>/
        session.json     # header (id, pack pin)
        events.jsonl     # hash-chained EventLog
        .writer.lock
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.root / ".writer.lock"
        self._header_path = self.root / "session.json"
        self.eventlog = EventLog(self.root / "events.jsonl")
        self.state: Optional[SessionState] = None

    @contextmanager
    def _exclusive_lock(self, timeout_s: float = 30.0) -> Iterator[None]:
        start = time.time()
        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                break
            except FileExistsError:
                if time.time() - start > timeout_s:
                    raise SessionLockError(f"Could not acquire lock at {self._lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                self._lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _atomic_write_json(self, path: Path, obj: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix="session-", suffix=".json", dir=str(path.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp:
                json.dump(obj, tmp, sort_keys=True, indent=2)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _load_records(
        self,
        pack_path: Path | str | None,
        *,
        expected_hash: Optional[str] = None,
        repin: bool = False,
        multi_pack: bool = True,
    ) -> tuple[list, str, dict[str, str]]:
        """Load single pack or default 6030+6033 multi-pack. Returns recs, pin, hashes."""
        if pack_path is not None:
            recs, digest = load_requirement_records(
                pack_path, expected_hash=expected_hash, repin=repin
            )
            return recs, digest, {recs[0].rule_pack_id if recs else "pack": digest}
        if multi_pack:
            recs, hashes = load_rdw_default_packs(repin=True)
            # Composite pin over sorted pack hashes
            material = "|".join(f"{k}={v}" for k, v in sorted(hashes.items()))
            import hashlib as _hl

            digest = f"sha256:{_hl.sha256(material.encode()).hexdigest()}"
            if expected_hash is not None and expected_hash != digest and not repin:
                raise PackPinError(
                    f"Multi-pack pin mismatch: session={expected_hash} now={digest}"
                )
            return recs, digest, hashes
        recs, digest = load_requirement_records(
            None, expected_hash=expected_hash, repin=repin
        )
        return recs, digest, {"default": digest}

    def open(
        self,
        *,
        actor_name: str,
        pack_path: Path | str | None = None,
        repin: bool = False,
        seed_context: bool = True,
        multi_pack: bool = True,
    ) -> SessionState:
        """Create a new session or refuse if header already pins a different pack."""
        # M1: do not call resume() under the lock (non-reentrant)
        if self._header_path.exists():
            return self.resume(
                actor_name=actor_name,
                repin=repin,
                multi_pack=multi_pack,
                pack_path=pack_path,
            )

        with self._exclusive_lock():
            if self._header_path.exists():
                raise SessionError(
                    "Session was created concurrently; call resume() instead of open()"
                )

            records, digest, pack_hashes = self._load_records(
                pack_path, repin=repin, multi_pack=multi_pack
            )
            session_id = f"sess-{uuid.uuid4().hex[:12]}"
            pack_id = "+".join(sorted(pack_hashes.keys())) if pack_hashes else "unknown"
            header = {
                "session_id": session_id,
                "pack_id": pack_id,
                "pack_hash": digest,
                "pack_hashes": pack_hashes,
                "schema_version": SESSION_SCHEMA,
                "created_at": _utcnow(),
                "actor_name": actor_name,
            }
            self._atomic_write_json(self._header_path, header)
            state = SessionState(
                session_id=session_id,
                pack_id=pack_id,
                pack_hash=digest,
                actor_name=actor_name,
                context=seed_context_appendix_b() if seed_context else ProjectContext(),
            )
            # Seed unit rows from pack (axes TBD)
            for rec in records:
                state.units[rec.requirement_id] = UnitAxesState(
                    unit_id=rec.requirement_id,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    organization_responsibility="tbd",
                    org_responsibility_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    implementation_state="tbd",
                    implementation_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    approval_state="tbd",
                    approval_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                )
            self.eventlog.append(
                actor=actor_name,
                payload={
                    "event_type": "session_opened",
                    "session_id": session_id,
                    "pack_id": pack_id,
                    "pack_hash": digest,
                    "pack_hashes": pack_hashes,
                    "unit_count": len(state.units),
                },
            )
            self.state = state
            self._graph = DependencyGraph.from_seeds()
            return state

    def resume(
        self,
        *,
        actor_name: str,
        repin: bool = False,
        pack_path: Path | str | None = None,
        multi_pack: Optional[bool] = None,
    ) -> SessionState:
        """Reload = replay event log; verify pack pin (default: no silent repin)."""
        with self._exclusive_lock():
            if not self._header_path.exists():
                raise SessionError(f"No session header at {self._header_path}")
            header = json.loads(self._header_path.read_text(encoding="utf-8"))
            try:
                self.eventlog.verify()
            except EventLogError:
                raise

            # H2: auto-detect multi vs single pin from header
            has_multi = bool(header.get("pack_hashes")) and len(
                header.get("pack_hashes") or {}
            ) > 1
            if multi_pack is None:
                multi_pack = has_multi and pack_path is None
            # Single-pack sessions: multi_pack must stay False unless repin rebuilds
            if pack_path is None and not has_multi and not repin:
                multi_pack = False

            try:
                records, digest, pack_hashes = self._load_records(
                    pack_path,
                    expected_hash=None if repin else header.get("pack_hash"),
                    repin=repin,
                    multi_pack=bool(multi_pack) and pack_path is None,
                )
            except PackPinError:
                # Compat: retry single-pack pin when composite fails (H2)
                if pack_path is None and not repin:
                    records, digest, pack_hashes = self._load_records(
                        None,
                        expected_hash=header.get("pack_hash"),
                        repin=False,
                        multi_pack=False,
                    )
                else:
                    raise
            if repin and digest != header["pack_hash"]:
                header["pack_hash"] = digest
                header["pack_hashes"] = pack_hashes
                self._atomic_write_json(self._header_path, header)
                self.eventlog.append(
                    actor=actor_name,
                    payload={
                        "event_type": "pack_repinned",
                        "pack_hash": digest,
                    },
                )

            state = SessionState(
                session_id=header["session_id"],
                pack_id=header["pack_id"],
                pack_hash=header["pack_hash"],
                actor_name=actor_name or header.get("actor_name", "unknown"),
            )
            for rec in records:
                state.units[rec.requirement_id] = UnitAxesState(
                    unit_id=rec.requirement_id,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    organization_responsibility="tbd",
                    org_responsibility_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    implementation_state="tbd",
                    implementation_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    approval_state="tbd",
                    approval_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                )
            self._replay_into(state)
            self.state = state
            self._graph = DependencyGraph.from_seeds()
            return state

    def _replay_into(self, state: SessionState) -> None:
        for ev in self.eventlog.iter_events():
            p = ev.payload or {}
            et = p.get("event_type")
            if et == "fact_asserted":
                fact = Fact.model_validate(p["fact"])
                state.facts_by_id[fact.fact_id] = fact
                state.facts[fact.key] = fact
            elif et == "fact_superseded":
                fact = Fact.model_validate(p["fact"])
                state.facts_by_id[fact.fact_id] = fact
                state.facts[fact.key] = fact
            elif et == "axis_set":
                unit = UnitAxesState.model_validate(p["unit"])
                state.units[unit.unit_id] = unit
            elif et == "election":
                unit = UnitAxesState.model_validate(p["unit"])
                state.units[unit.unit_id] = unit
            elif et == "evidence_ref_attached":
                uid = p["unit_id"]
                ref = EvidenceRef.model_validate(p["evidence_ref"])
                cur = state.units.get(uid)
                if cur:
                    state.units[uid] = cur.model_copy(
                        update={"evidence_refs": cur.evidence_refs + (ref,)}
                    )
            elif et == "paired_answer":
                state.paired_answers[p["question_key"]] = p["answer"]
            elif et == "context_updated":
                state.context = ProjectContext.model_validate(p["context"])
            elif et == "export_produced":
                # M3: store only the export meta slice, not whole payload envelope
                meta = {
                    k: v
                    for k, v in p.items()
                    if k not in ("event_type", "_schema")
                }
                state.exports.append(meta)
            elif et == "propagation_rereview":
                affected = list(p.get("affected_units") or [])
                for u in affected:
                    if u not in state.needs_rereview:
                        state.needs_rereview.append(u)
                if p.get("diffs"):
                    state.rereview_diffs.update(p["diffs"])
            elif et == "rereview_cleared":
                uid = p.get("unit_id")
                if uid and uid in state.needs_rereview:
                    state.needs_rereview = [x for x in state.needs_rereview if x != uid]
                if uid and uid in state.rereview_diffs:
                    del state.rereview_diffs[uid]
            elif et == "review_decision":
                # Axes review_state on unit when present
                uid = p.get("unit_id")
                if uid and uid in state.units:
                    dec = p.get("decision")
                    if dec in (
                        "accepted",
                        "rejected",
                        "superseded",
                        "in_review",
                        "proposed",
                    ):
                        state.units[uid] = state.units[uid].model_copy(
                            update={"review_state": dec}
                        )
            # session_opened / pack_repinned: no state delta beyond header

    def assert_fact(
        self,
        *,
        key: str,
        statement: str,
        author: str,
        kind: FACT_KIND = "asserted",
        confidence: CONFIDENCE = "medium",
        assumed: bool = False,
        owner: Optional[str] = None,
        source: str = "interview",
        unit_ids: tuple[str, ...] = (),
        confirm_assumption: bool = False,
    ) -> Fact:
        """Assert a fact. Assumptions never silently become confirmed."""
        if self.state is None:
            raise SessionError("Session not open")
        if assumed and not owner:
            raise SessionError("Assumptions require an owner")
        prior = self.state.facts.get(key)
        if prior and prior.assumed and not assumed and not confirm_assumption:
            raise SessionError(
                f"Fact {key!r} is an assumption; refusing silent confirmation "
                "(pass confirm_assumption=True for explicit promotion)"
            )
        # H1: inferred facts never auto-confirm; require human acceptance
        if kind == "inferred" and not confirm_assumption and not assumed:
            raise SessionError(
                f"Inferred fact {key!r} requires confirm_assumption=True "
                "(human acceptance) before it is treated as confirmed"
            )
        confirmed = False
        if assumed:
            confirmed = False
        elif kind == "inferred":
            confirmed = bool(confirm_assumption)
        else:
            confirmed = bool(
                confirm_assumption or not (prior and prior.assumed)
            ) and not assumed

        prior_snapshot = prior.model_dump(mode="json") if prior else None
        fact = Fact(
            fact_id=f"fact-{uuid.uuid4().hex[:10]}",
            key=key,
            statement=statement,
            kind=kind,
            author=author,
            timestamp=_utcnow(),
            source=source,
            confidence=confidence,
            assumed=assumed,
            owner=owner,
            supersedes=prior.fact_id if prior else None,
            confirmed=confirmed,
            unit_ids=unit_ids,
        )
        et = "fact_superseded" if prior else "fact_asserted"
        with self._exclusive_lock():
            self.eventlog.append(
                actor=author,
                unit_id=unit_ids[0] if unit_ids else None,
                payload={"event_type": et, "fact": fact.model_dump(mode="json")},
            )
            self.state.facts[key] = fact
            self.state.facts_by_id[fact.fact_id] = fact
            # §10.2: only confirmed (non-assumed) facts propagate
            if fact.confirmed and not fact.assumed:
                graph = getattr(self, "_graph", None) or DependencyGraph.from_seeds()
                self._graph = graph
                affected = graph.propagate_from_fact(key, committed=True)
                diffs: dict[str, Any] = {}
                for uid in affected:
                    u = self.state.units.get(uid)
                    diffs[uid] = {
                        "before": u.model_dump(mode="json") if u else None,
                        "trigger_fact": key,
                        "prior_fact": prior_snapshot,
                        "new_fact": fact.model_dump(mode="json"),
                    }
                    if uid not in self.state.needs_rereview:
                        self.state.needs_rereview.append(uid)
                    self.state.rereview_diffs[uid] = diffs[uid]
                if affected:
                    self.eventlog.append(
                        actor=author,
                        payload={
                            "event_type": "propagation_rereview",
                            "fact_key": key,
                            "affected_units": affected,
                            "diffs": diffs,
                        },
                    )
        return fact

    def units_needing_rereview(self) -> list[str]:
        if self.state is None:
            return []
        return list(self.state.needs_rereview)

    def clear_rereview(self, unit_id: str, *, actor_name: str) -> None:
        """Clear re-review flag only via logged event (H1)."""
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                unit_id=unit_id,
                payload={"event_type": "rereview_cleared", "unit_id": unit_id},
            )
            self.state.needs_rereview = [
                x for x in self.state.needs_rereview if x != unit_id
            ]
            self.state.rereview_diffs.pop(unit_id, None)

    def set_axes(
        self,
        unit_id: str,
        *,
        actor_name: str,
        election: bool = True,
        enforce_decision: bool = True,
        **axis_fields: Any,
    ) -> UnitAxesState:
        """
        Set axes. When election=True (default), refuse labels blocked by the
        decision engine (C1). §13.2 runs on any stored comment text.
        """
        if self.state is None:
            raise SessionError("Session not open")
        from oracle.disposition.comments import prohibited_language_hits
        from oracle.disposition.decision import evaluate_unit
        from oracle.disposition.graph import DependencyGraph

        cur = self.state.units.get(unit_id)
        if cur is None:
            cur = UnitAxesState(unit_id=unit_id)
        data = cur.model_dump()
        data.update({k: v for k, v in axis_fields.items() if v is not None})
        data["actor_name"] = actor_name
        for axis, reason in (
            ("applicability", "applicability_tbd_reason"),
            ("organization_responsibility", "org_responsibility_tbd_reason"),
            ("implementation_state", "implementation_tbd_reason"),
            ("approval_state", "approval_tbd_reason"),
        ):
            if data.get(axis) != "tbd":
                data[reason] = None
        unit = UnitAxesState.model_validate(data)

        # C1: §13.2 on stored comments (including edited)
        if unit.comment:
            hits = prohibited_language_hits(unit.comment)
            if hits:
                raise SessionError(
                    f"Comment fails §13.2 prohibited-language check: {hits}"
                )

        # Validate axis mapping
        try:
            label = unit.export_label()
        except Exception as e:
            raise SessionError(f"Axes do not map under §7.1: {e}") from e

        # C1: elections refuse decision-engine blocks
        if election and enforce_decision:
            graph = getattr(self, "_graph", None) or DependencyGraph.from_seeds()
            has_ev = bool(unit.evidence_refs)
            decision = evaluate_unit(
                unit,
                facts=self.state.facts,
                graph=graph,
                has_scope_rationale=bool(unit.scope_citation),
                has_evidence_for_meet=has_ev,
            )
            if label.value in decision.blocked:
                raise SessionError(
                    f"Election refused: export label {label.value!r} is blocked "
                    f"({decision.blocked[label.value]})"
                )
            # Also refuse if Meet/NA mapped but blocked even when checking intent
            if (
                label.value == "Meet"
                and unit.applicability == "yes"
                and not has_ev
            ):
                raise SessionError(
                    "Election refused: Meet requires qualifying evidence (hard gate)"
                )

        et = "election" if election else "axis_set"
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                unit_id=unit_id,
                payload={"event_type": et, "unit": unit.model_dump(mode="json")},
            )
            self.state.units[unit_id] = unit
        return unit

    def record_review_decision(
        self,
        unit_id: str,
        *,
        decision: str,
        reviewer: str,
        role: str,
        comment: str = "",
        accepted_with_tbd: bool = False,
    ) -> None:
        """Append review decision to the hash-chained event log (C3)."""
        if self.state is None:
            raise SessionError("Session not open")
        unit = self.state.units.get(unit_id)
        if unit is None:
            raise SessionError(f"Unknown unit {unit_id}")
        # Review coherence: accepted requires non-TBD or accepted_with_tbd
        if decision == "accepted":
            has_tbd = (
                unit.applicability == "tbd"
                or unit.organization_responsibility == "tbd"
                or unit.implementation_state == "tbd"
                or unit.approval_state == "tbd"
            )
            if has_tbd and not (accepted_with_tbd or unit.accepted_with_tbd):
                raise SessionError(
                    "review_coherence: accepted requires non-TBD axes or "
                    "accepted_with_tbd election"
                )
        with self._exclusive_lock():
            self.eventlog.append(
                actor=reviewer,
                unit_id=unit_id,
                payload={
                    "event_type": "review_decision",
                    "unit_id": unit_id,
                    "decision": decision,
                    "role": role,
                    "comment": comment,
                    "accepted_with_tbd": accepted_with_tbd,
                },
            )
            updates: dict[str, Any] = {"review_state": decision}
            if accepted_with_tbd:
                updates["accepted_with_tbd"] = True
            self.state.units[unit_id] = unit.model_copy(update=updates)

    def record_paired_answer(self, question_key: str, answer: str, actor_name: str) -> None:
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                payload={
                    "event_type": "paired_answer",
                    "question_key": question_key,
                    "answer": answer,
                },
            )
            self.state.paired_answers[question_key] = answer

    def update_context(self, context: ProjectContext, actor_name: str) -> None:
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                payload={
                    "event_type": "context_updated",
                    "context": context.model_dump(mode="json"),
                },
            )
            self.state.context = context

    def attach_evidence(
        self, unit_id: str, ref: EvidenceRef, actor_name: str
    ) -> UnitAxesState:
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                unit_id=unit_id,
                payload={
                    "event_type": "evidence_ref_attached",
                    "unit_id": unit_id,
                    "evidence_ref": ref.model_dump(mode="json"),
                },
            )
            cur = self.state.units.get(unit_id) or UnitAxesState(unit_id=unit_id)
            new = cur.model_copy(update={"evidence_refs": cur.evidence_refs + (ref,)})
            self.state.units[unit_id] = new
            return new

    def record_export(self, meta: dict[str, Any], actor_name: str) -> None:
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                payload={"event_type": "export_produced", **meta},
            )
            self.state.exports.append(meta)

    def fact_for(self, key: str) -> Optional[Fact]:
        if self.state is None:
            return None
        return self.state.facts.get(key)

    def blocked_by(self, unit_id: str) -> list[str]:
        """Dependency prereqs that lack confirming facts."""
        blockers: list[str] = []
        for pre in prerequisites_of(unit_id):
            # Classification chain
            if pre.startswith("AMR-") and self.fact_for("classification.primary") is None:
                blockers.append(f"prerequisite {pre} / classification.primary unresolved")
            if pre == "AMR-14" and self.fact_for("plan.EFCP") is None:
                blockers.append("EFCP / 6033 matrix not present (plan.EFCP)")
            if pre == "AMR-2" and self.fact_for("plan.AMCP") is None:
                blockers.append("AMCP not observed (plan.AMCP)")
        return blockers


def why_not_meet(unit: UnitAxesState, session: DispositionSession) -> list[str]:
    """Deterministic blockers preventing Meet (export label)."""
    reasons: list[str] = []
    if unit.applicability == "tbd":
        reasons.append(
            f"applicability is TBD ({unit.applicability_tbd_reason})"
        )
    elif unit.applicability == "no":
        reasons.append("applicability is No (N/A path, not Meet)")
    if unit.implementation_state != "meets_as_written":
        reasons.append(
            f"implementation_state is {unit.implementation_state!r}, not meets_as_written"
        )
    if unit.approval_state not in ("not_required", "approved"):
        reasons.append(
            f"approval_state is {unit.approval_state!r} (Meet requires not_required or approved)"
        )
    for b in session.blocked_by(unit.unit_id):
        reasons.append(f"dependency: {b}")
    return reasons


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
