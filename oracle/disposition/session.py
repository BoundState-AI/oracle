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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from oracle.disposition.codes import (
    Applicability,
    ApprovalState,
    ExecutionState,
    ExportLabel,
    FulfillmentPath,
    ImplementationState,
    ObligatedActor,
    OrgResponsibility,
    ProposalBand,
    TBDReason,
    legacy_from_split,
    split_from_legacy,
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

    @field_validator("doc_id", "revision", mode="before")
    @classmethod
    def _strip_identity(cls, v: object) -> object:
        # N7: registry matching is exact on (doc_id, revision) — whitespace
        # drift at attachment silently demoted registered evidence. Case is
        # left alone (revision identifiers may be case-sensitive).
        return v.strip() if isinstance(v, str) else v


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
    # Model split (Fran P0): the contract ELECTION and the execution FACT.
    # implementation_state is a derived legacy view; every derivation reads
    # these. split_elected marks a unit whose split axes were set directly
    # (legacy writes re-derive; split writes back-derive the legacy view).
    fulfillment_path: FulfillmentPath = "tbd"
    execution_state: ExecutionState = "tbd"
    split_elected: bool = False
    applicability_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    org_responsibility_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    implementation_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    approval_tbd_reason: Optional[TBDReason] = TBDReason.EVIDENCE_ABSENT
    scope_citation: Optional[str] = None  # required for N/A (FR-009); whitespace rejected
    accepted_with_tbd: bool = False  # review coherence election
    review_state: Literal[
        "not_reviewed", "proposed", "in_review", "accepted", "rejected", "superseded"
    ] = "proposed"
    comment: Optional[str] = None
    comment_status: Literal["proposed", "accepted", "edited"] = "proposed"
    evidence_refs: tuple[EvidenceRef, ...] = ()
    open_actions: tuple[str, ...] = ()  # legacy strings; prefer SessionState.actions
    actor_name: Optional[str] = None
    # Stage A — Not Yet Due marker (justification required when True)
    not_yet_due: bool = False
    not_yet_due_justification: Optional[str] = None
    # Stage A — Exception closure fields
    exception_basis: Optional[str] = None
    permanent_relief_basis: Optional[str] = None
    closure_path_action_id: Optional[str] = None
    # FR3 — Meets Intent fields (mirror DispositionUnit; gated at election)
    intent_statement: Optional[str] = None
    alternative_control: Optional[str] = None
    control_class: Optional[Literal["integral", "disclosed"]] = None

    @model_validator(mode="before")
    @classmethod
    def _model_split_conversion(cls, data: Any) -> Any:
        """Single conversion point between the legacy axis and the split.

        Legacy inputs (old event payloads, old tests) lack the split axes —
        derive them with the validated migration table. Split inputs may
        omit implementation_state — back-derive the legacy view. Callers
        that drop one side force the re-derivation (set_axes does this)."""
        if not isinstance(data, dict):
            return data
        ful = data.get("fulfillment_path")
        execu = data.get("execution_state")
        if ful is None or execu is None:
            d_ful, d_exec = split_from_legacy(
                data.get("implementation_state") or "tbd",
                data.get("applicability") or "tbd",
                data.get("approval_state") or "tbd",
            )
            data["fulfillment_path"] = ful or d_ful
            data["execution_state"] = execu or d_exec
        if data.get("implementation_state") is None:
            data["implementation_state"] = legacy_from_split(
                data["fulfillment_path"], data["execution_state"]
            )
        return data

    @field_validator("scope_citation", mode="before")
    @classmethod
    def _strip_scope_citation(cls, v: Any) -> Optional[str]:
        """F4: strip; whitespace-only is absent/rejected (not a real citation)."""
        if v is None:
            return None
        if not isinstance(v, str):
            v = str(v)
        stripped = v.strip()
        if len(stripped) == 0:
            raise ValueError(
                "scope_citation must be a non-blank string (whitespace-only rejected)"
            )
        return stripped

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
            if self.execution_state == "tbd"
            else None,
            approval_tbd_reason=self.approval_tbd_reason
            if self.approval_state == "tbd"
            else None,
            fulfillment_path=self.fulfillment_path,
            execution_state=self.execution_state,
            split_elected=self.split_elected,
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
    # N9: which units each paired answer applied to (self-describing pairs)
    paired_units: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    exports: list[dict[str, Any]] = Field(default_factory=list)
    needs_rereview: list[str] = Field(default_factory=list)  # durable via event replay
    rereview_diffs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Stage A
    actions: dict[str, Any] = Field(default_factory=dict)  # action_id -> ActionRecord
    # CR1 — wp_id -> WorkPackageRecord
    work_packages: dict[str, Any] = Field(default_factory=dict)
    raw_answers: list[dict[str, Any]] = Field(default_factory=list)
    advisor_outputs: list[dict[str, Any]] = Field(default_factory=list)
    # FR5 — library reuse: suggestions are never auto-applied
    library_suggestions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    library_action_patterns: list[dict[str, Any]] = Field(default_factory=list)
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
        # N3: the exact records this session pinned at open/resume —
        # renderers must use THESE, never re-load a (different) default set.
        self.loaded_records: list = []

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
        allow_builtin: bool = False,
    ) -> tuple[list, str, dict[str, str]]:
        """Load single pack or default 6030+6033 multi-pack. Returns recs, pin, hashes."""
        if pack_path is not None:
            recs, digest = load_requirement_records(
                pack_path, expected_hash=expected_hash, repin=repin
            )
            return recs, digest, {recs[0].rule_pack_id if recs else "pack": digest}
        if multi_pack:
            recs, hashes = load_rdw_default_packs(
                repin=True, allow_builtin=allow_builtin
            )
            # Composite pin over sorted pack hashes
            material = "|".join(f"{k}={v}" for k, v in sorted(hashes.items()))
            import hashlib as _hl

            digest = f"sha256:{_hl.sha256(material.encode()).hexdigest()}"
            if expected_hash is not None and expected_hash != digest and not repin:
                raise PackPinError(
                    f"Multi-pack pin mismatch: session={expected_hash} now={digest}"
                )
            return recs, digest, hashes
        # AR4: the single-pack DEFAULT is the known-corrupt builtin — the FR7
        # fail-closed rule applies here too, not just in the multi-pack loader.
        if not allow_builtin:
            raise PackPinError(
                "Default single-pack load targets the known-corrupt builtin "
                "6030 pack. Pass allow_builtin=True explicitly (FR7/AR4) or "
                "use the curated multi-pack default."
            )
        LOGGER.warning(
            "allow_builtin=True: loading the KNOWN-CORRUPT builtin 6030 pack "
            "as the single-pack default"
        )
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
        allow_builtin: bool = False,
    ) -> SessionState:
        """Create a new session or refuse if header already pins a different pack."""
        # M1: do not call resume() under the lock (non-reentrant)
        if self._header_path.exists():
            return self.resume(
                actor_name=actor_name,
                repin=repin,
                multi_pack=multi_pack,
                pack_path=pack_path,
                allow_builtin=allow_builtin,
            )

        with self._exclusive_lock():
            if self._header_path.exists():
                raise SessionError(
                    "Session was created concurrently; call resume() instead of open()"
                )

            records, digest, pack_hashes = self._load_records(
                pack_path,
                repin=repin,
                multi_pack=multi_pack,
                allow_builtin=allow_builtin,
            )
            self.loaded_records = records
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
        allow_builtin: bool = False,
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
                    allow_builtin=allow_builtin,
                )
            except PackPinError:
                # Compat: retry single-pack pin when composite fails (H2).
                # AR4: the retry targets the builtin, so the same explicit
                # opt-in is required — legacy builtin-pinned sessions must
                # not resume silently onto the corrupt pack.
                if pack_path is None and not repin and allow_builtin:
                    records, digest, pack_hashes = self._load_records(
                        None,
                        expected_hash=header.get("pack_hash"),
                        repin=False,
                        multi_pack=False,
                        allow_builtin=True,
                    )
                else:
                    raise
            self.loaded_records = records
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

    def evidence_store(self, *, create: bool = False) -> Optional[Any]:
        """Return EvidenceStore when <session>/evidence registry exists; else None.

        create=True initializes the registry (M3: citations register at the
        moment of the claim instead of floating unverified)."""
        from oracle.disposition.evidence import EvidenceStore

        root = self.root / "evidence"
        registry = root / "registry.jsonl"
        if create or (root.is_dir() and registry.is_file()):
            return EvidenceStore(root)
        return None

    def register_evidence(
        self,
        *,
        doc_id: str,
        revision: str,
        unit_ids: tuple[str, ...] = (),
        effective_date: Optional[str] = None,
        approval_date: Optional[str] = None,
        evidence_id: Optional[str] = None,
    ) -> Any:
        """M3 convenience: create the registry on demand and register."""
        store = self.evidence_store(create=True)
        return store.register(
            evidence_id=evidence_id or f"EV-{doc_id}-{revision}",
            doc_id=doc_id,
            revision=revision,
            unit_ids=tuple(unit_ids),
            effective_date=effective_date,
            approval_date=approval_date,
        )

    def has_qualifying_meet_evidence(self, unit: UnitAxesState) -> bool:
        """
        F2 Meet evidence floor.

        With a session evidence registry: require unit_has_qualifying_meet_evidence
        and at least one cited EvidenceRef matching a registered (doc_id, revision)
        that passes evidence_supports_meet. Without registry: bool(evidence_refs)
        with a warning that refs are unverified (v0 posture).
        """
        from oracle.disposition.evidence import evidence_supports_meet

        store = self.evidence_store()
        if store is None:
            # M3 (Fran P1): a typed citation without a registry entry is a
            # CLAIM, not qualifying evidence — fail closed. Warn once.
            flag = "_warned_unverified_evidence"
            if unit.evidence_refs and not getattr(self, flag, False):
                LOGGER.warning(
                    "Evidence refs do NOT qualify: no evidence registry at "
                    "%s/evidence (M3 fail-closed; use register_evidence)",
                    self.root,
                )
                setattr(self, flag, True)
            return False
        # Atlas M3-1: the CITED and UNIT-LINKED predicates must be satisfied
        # by the SAME artifact — a qualifying-but-uncited artifact plus a
        # cited-but-other-unit artifact must never combine into a pass.
        linked = {
            (a.doc_id, a.revision): a for a in store.for_unit(unit.unit_id)
        }
        for ref in unit.evidence_refs:
            art = linked.get((ref.doc_id, ref.revision))
            if art is not None and evidence_supports_meet(art).ok:
                return True
        return False

    def _apply_fact_propagation(
        self,
        state: SessionState,
        fact: Fact,
        *,
        prior_snapshot: Optional[dict[str, Any]] = None,
        graph: Optional[DependencyGraph] = None,
    ) -> list[str]:
        """
        §10.2 / F1 / F3: recompute re-review from a confirmed fact.

        Marks dependents for re-review; accepted units transition to superseded.
        Same code path for live assert_fact and replay (deterministic).
        """
        if not (fact.confirmed and not fact.assumed):
            return []
        graph = graph or getattr(self, "_graph", None) or DependencyGraph.from_seeds()
        self._graph = graph
        affected = graph.propagate_from_fact(fact.key, committed=True)
        for uid in affected:
            u = state.units.get(uid)
            diffs = {
                "before": u.model_dump(mode="json") if u else None,
                "trigger_fact": fact.key,
                "prior_fact": prior_snapshot,
                "new_fact": fact.model_dump(mode="json"),
            }
            if uid not in state.needs_rereview:
                state.needs_rereview.append(uid)
            state.rereview_diffs[uid] = diffs
            # F1: prior acceptance no longer stands
            if u is not None and u.review_state == "accepted":
                state.units[uid] = u.model_copy(update={"review_state": "superseded"})
                diffs["review_transition"] = "accepted→superseded"
                state.rereview_diffs[uid] = diffs
        return affected

    def _replay_into(self, state: SessionState) -> None:
        """
        Rebuild state by replaying the event log.

        F3: on each confirmed fact event, recompute propagation (graph over
        confirmed facts) so re-review survives a crash between fact append and
        the audit-only propagation_rereview event. rereview_cleared applied in
        order. propagation_rereview is ignored on replay.
        """
        graph = DependencyGraph.from_seeds()
        self._graph = graph
        for ev in self.eventlog.iter_events():
            p = ev.payload or {}
            et = p.get("event_type")
            if et == "fact_asserted" or et == "fact_superseded":
                fact = Fact.model_validate(p["fact"])
                prior = state.facts.get(fact.key)
                prior_snapshot = prior.model_dump(mode="json") if prior else None
                state.facts_by_id[fact.fact_id] = fact
                state.facts[fact.key] = fact
                # F3: recompute propagation; do not depend on propagation_rereview
                self._apply_fact_propagation(
                    state, fact, prior_snapshot=prior_snapshot, graph=graph
                )
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
                # N9: legacy events lack unit_ids — default to the classic pair
                state.paired_units[p["question_key"]] = tuple(
                    p.get("unit_ids") or ("AMR-21", "AMR-82")
                )
            elif et == "answer_recorded":
                state.raw_answers.append(
                    {
                        "unit_id": p.get("unit_id"),
                        "question_key": p.get("question_key"),
                        "raw": p.get("raw"),
                        "actor": p.get("actor") or ev.actor,
                        "timestamp": ev.timestamp,
                    }
                )
            elif et == "action_recorded":
                from oracle.disposition.actions import ActionRecord

                act = ActionRecord.model_validate(p["action"])
                state.actions[act.action_id] = act
                if act.supersedes and act.supersedes in state.actions:
                    prior = state.actions[act.supersedes]
                    state.actions[act.supersedes] = prior.model_copy(
                        update={"status": "superseded"}
                    )
            elif et == "work_package_recorded":
                from oracle.disposition.workpackage import WorkPackageRecord

                wp = WorkPackageRecord.model_validate(p["work_package"])
                # same order as live recording: supersession FIRST, then
                # store — replay and resume must agree (Atlas CR Medium 5)
                if wp.supersedes and wp.supersedes in state.work_packages:
                    prior = state.work_packages[wp.supersedes]
                    state.work_packages[wp.supersedes] = prior.model_copy(
                        update={"status": "superseded"}
                    )
                state.work_packages[wp.wp_id] = wp
            elif et == "advisor_output":
                state.advisor_outputs.append(
                    {k: v for k, v in p.items() if k not in ("event_type", "_schema")}
                )
            elif et == "library_imported":
                for dsp in p.get("dispositions") or []:
                    rid = dsp.get("requirement_id")
                    if rid:
                        state.library_suggestions[rid] = dsp
                for pat in p.get("action_patterns") or []:
                    state.library_action_patterns.append(pat)
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
                # F3: audit-only — replay must not depend on this event
                continue
            elif et == "rereview_cleared":
                uid = p.get("unit_id")
                if uid and uid in state.needs_rereview:
                    state.needs_rereview = [x for x in state.needs_rereview if x != uid]
                if uid and uid in state.rereview_diffs:
                    del state.rereview_diffs[uid]
            elif et in ("review_decision", "unit_attested"):
                # F6/A7: restore review_state and accepted_with_tbd
                uid = p.get("unit_id")
                if uid and uid in state.units:
                    dec = p.get("decision")
                    updates: dict[str, Any] = {}
                    if dec in (
                        "accepted",
                        "rejected",
                        "superseded",
                        "in_review",
                        "proposed",
                    ):
                        updates["review_state"] = dec
                    if "accepted_with_tbd" in p:
                        updates["accepted_with_tbd"] = bool(p["accepted_with_tbd"])
                    if updates:
                        state.units[uid] = state.units[uid].model_copy(update=updates)
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
            # §10.2 / F1 / F3: confirmed facts propagate via shared path;
            # propagation_rereview is audit-only (replay recomputes from fact event)
            affected = self._apply_fact_propagation(
                self.state, fact, prior_snapshot=prior_snapshot
            )
            if affected:
                diffs = {
                    uid: self.state.rereview_diffs.get(uid, {}) for uid in affected
                }
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
        _defer: Optional[list] = None,
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
        # Provenance is DERIVED, never caller-asserted (Atlas CR High 1):
        # a forged split_elected would unlock the split-only allowances
        # (CW-by-policy, external exceptions) without a real election.
        if "split_elected" in axis_fields:
            raise SessionError(
                "split_elected is derived from the election shape and is "
                "never caller-settable"
            )
        data = cur.model_dump()
        data.update({k: v for k, v in axis_fields.items() if v is not None})
        data["actor_name"] = actor_name
        data["unit_id"] = unit_id

        # Model split write rules (single source of coherence):
        #   split write  -> split axes govern; legacy view back-derived
        #   legacy write -> unit becomes legacy-driven; split re-derived
        #   other axes on a legacy-driven unit -> split re-derived (the
        #     migration depends on applicability/approval)
        touches_split = (
            "fulfillment_path" in axis_fields or "execution_state" in axis_fields
        )
        touches_legacy = "implementation_state" in axis_fields
        if touches_split:
            data["split_elected"] = True
            data.pop("implementation_state", None)
        elif touches_legacy or not data.get("split_elected"):
            if touches_legacy:
                data["split_elected"] = False
            data.pop("fulfillment_path", None)
            data.pop("execution_state", None)

        for axis, reason in (
            ("applicability", "applicability_tbd_reason"),
            ("organization_responsibility", "org_responsibility_tbd_reason"),
            ("approval_state", "approval_tbd_reason"),
        ):
            if data.get(axis) != "tbd":
                data[reason] = None
        # The implementation TBD reason belongs to EXECUTION under the
        # split (the legacy view can read meets_as_written while execution
        # is TBD — a CW commitment). Key it to the effective execution.
        eff_exec = data.get("execution_state")
        if eff_exec is None:
            eff_exec = split_from_legacy(
                data.get("implementation_state") or "tbd",
                data.get("applicability") or "tbd",
                data.get("approval_state") or "tbd",
            )[1]
        if eff_exec != "tbd":
            data["implementation_tbd_reason"] = None
        elif data.get("implementation_tbd_reason") is None:
            data["implementation_tbd_reason"] = TBDReason.EVIDENCE_ABSENT
        unit = UnitAxesState.model_validate(data)

        # C1: §13.2 on stored comments (including edited). N4: only the
        # comment being SET in this call refuses — re-checking a carried
        # legacy comment wedged every axis update on pre-fix sessions.
        # A carried violation is surfaced as a warning until repaired via
        # a comment update (which IS checked).
        if unit.comment:
            hits = prohibited_language_hits(unit.comment)
            if hits and "comment" in axis_fields:
                raise SessionError(
                    f"Comment fails §13.2 prohibited-language check: {hits}"
                )
            if hits:
                LOGGER.warning(
                    "Unit %s carries a pre-existing §13.2 violation %s — "
                    "repair the comment; axis updates proceed",
                    unit_id,
                    hits,
                )

        # Stage A: not_yet_due requires justification
        if unit.not_yet_due and not (unit.not_yet_due_justification or "").strip():
            raise SessionError(
                "not_yet_due requires not_yet_due_justification"
            )
        # AR2: Not Yet Due is only coherent while execution has not begun
        # (a CW commitment may carry NYD — Fran's corpus has exactly that —
        # but concrete execution progress contradicts it). An explicit
        # contradiction refuses; a stale carried marker clears so a later
        # Meet/Not-Met election cannot produce two contradictory views.
        if unit.not_yet_due and unit.execution_state not in ("tbd", "not_started"):
            if axis_fields.get("not_yet_due") is True:
                raise SessionError(
                    "not_yet_due requires execution not started "
                    f"(got execution_state={unit.execution_state!r})"
                )
            unit = unit.model_copy(update={"not_yet_due": False})

        # Validate axis mapping
        try:
            label = unit.export_label()
        except Exception as e:
            raise SessionError(f"Axes do not map under §7.1: {e}") from e

        # C1: elections refuse decision-engine blocks
        if election and enforce_decision:
            graph = getattr(self, "_graph", None) or DependencyGraph.from_seeds()
            # F2: qualifying evidence when registry present; else bool(refs)+warn
            has_ev = self.has_qualifying_meet_evidence(unit)
            # F4: stripped-empty scope_citation is absent
            has_scope = bool(unit.scope_citation)
            decision = evaluate_unit(
                unit,
                facts=self.state.facts,
                graph=graph,
                has_scope_rationale=has_scope,
                has_evidence_for_meet=has_ev,
            )
            if label.value in decision.blocked:
                raise SessionError(
                    f"Election refused: export label {label.value!r} is blocked "
                    f"({decision.blocked[label.value]})"
                )
            # Model split: the hard evidence gate protects the execution
            # CLAIM, not the commitment — CW with execution not started is
            # AMR-106 (readiness carries the gap). Label-INDEPENDENT: an
            # unevidenced evidenced/verified claim refuses on MI/EX/Open
            # paths too (Atlas model-split High 2). Legacy meets_as_written
            # converts to execution=evidenced, so pre-split refusals hold.
            if (
                unit.applicability == "yes"
                and unit.execution_state in ("evidenced", "verified")
                and not has_ev
            ):
                raise SessionError(
                    "Election refused: evidenced/verified execution requires "
                    "qualifying evidence (hard gate)"
                )
            # Stage A: Exception closure gates
            if label.value == "Exception":
                if not (unit.exception_basis or "").strip():
                    raise SessionError(
                        "Election refused: Exception requires exception_basis"
                    )
                has_closure = bool(
                    (unit.closure_path_action_id or "").strip()
                    or (unit.permanent_relief_basis or "").strip()
                )
                if not has_closure:
                    raise SessionError(
                        "Election refused: Exception requires closure_path_action_id "
                        "or permanent_relief_basis"
                    )
            # FR3: Meets Intent requires intent + alternative control + class
            if label.value == "Meets Intent":
                missing = [
                    name
                    for name, val in (
                        ("intent_statement", unit.intent_statement),
                        ("alternative_control", unit.alternative_control),
                        ("control_class", unit.control_class),
                    )
                    if not (str(val or "")).strip()
                ]
                if missing:
                    raise SessionError(
                        "Election refused: Meets Intent requires "
                        + ", ".join(missing)
                    )

        # Re-open path: re-election on rejected/superseded returns to proposed
        if election and unit.review_state in ("rejected", "superseded"):
            unit = unit.model_copy(update={"review_state": "proposed"})

        et = "election" if election else "axis_set"
        payload = {"event_type": et, "unit": unit.model_dump(mode="json")}
        # N5: deferred mode — full validation ran above, but persistence is
        # the caller's (single atomic batch), so a multi-unit operation can
        # never persist a prefix of its elections.
        if _defer is not None:
            _defer.append(
                {
                    "actor": actor_name,
                    "unit_id": unit_id,
                    "payload": payload,
                    "unit": unit,
                }
            )
            return unit
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                unit_id=unit_id,
                payload=payload,
            )
            self.state.units[unit_id] = unit
        return unit

    def attest_unit(
        self,
        unit_id: str,
        *,
        actor_name: str,
        role: str,
        decision: str,
        accepted_with_tbd: bool = False,
        comment: str = "",
    ) -> UnitAxesState:
        """
        Single-operator attestation (F6). Role is recorded, not enforced.

        decision: accepted | rejected | proposed (re-open only).
        Transition legality enforced; accepted → superseded only via F1 propagation.
        """
        from oracle.disposition.review import LEGAL_ATTEST_TRANSITIONS

        if self.state is None:
            raise SessionError("Session not open")
        unit = self.state.units.get(unit_id)
        if unit is None:
            raise SessionError(f"Unknown unit {unit_id}")
        if decision not in ("accepted", "rejected", "proposed"):
            raise SessionError(
                f"attest decision must be accepted|rejected|proposed, got {decision!r}"
            )
        current = unit.review_state
        if (current, decision) not in LEGAL_ATTEST_TRANSITIONS:
            raise SessionError(
                f"illegal review transition {current!r} → {decision!r} "
                f"(accepted → superseded only via fact propagation; "
                f"never accepted → proposed directly)"
            )
        # Review coherence: accepted requires non-TBD or accepted_with_tbd.
        # Model split: EXECUTION is the axis that can be TBD while the
        # legacy view reads meets_as_written (CW commitment, execution
        # unresolved) — the gate must read the split axis, never the view.
        if decision == "accepted":
            has_tbd = (
                unit.applicability == "tbd"
                or unit.organization_responsibility == "tbd"
                or unit.execution_state == "tbd"
                or unit.approval_state == "tbd"
            )
            if has_tbd and not (accepted_with_tbd or unit.accepted_with_tbd):
                raise SessionError(
                    "review_coherence: accepted requires non-TBD axes or "
                    "accepted_with_tbd election"
                )
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                unit_id=unit_id,
                payload={
                    "event_type": "unit_attested",
                    "unit_id": unit_id,
                    "decision": decision,
                    "role": role,
                    "comment": comment,
                    "accepted_with_tbd": bool(accepted_with_tbd),
                    "actor_name": actor_name,
                },
            )
            updates: dict[str, Any] = {
                "review_state": decision,
                "accepted_with_tbd": bool(
                    accepted_with_tbd or (decision == "accepted" and unit.accepted_with_tbd)
                )
                if decision == "accepted"
                else unit.accepted_with_tbd,
            }
            if decision == "accepted" and accepted_with_tbd:
                updates["accepted_with_tbd"] = True
            elif decision == "proposed":
                # re-open clears prior TBD election for a clean re-attestation
                updates["accepted_with_tbd"] = False
            new_unit = unit.model_copy(update=updates)
            self.state.units[unit_id] = new_unit
            return new_unit

    def record_review_decision(
        self,
        unit_id: str,
        *,
        decision: str,
        reviewer: str,
        role: str,
        comment: str = "",
        accepted_with_tbd: bool = False,
    ) -> UnitAxesState:
        """Deprecated alias for attest_unit (compat for older callers)."""
        return self.attest_unit(
            unit_id,
            actor_name=reviewer,
            role=role,
            decision=decision,
            accepted_with_tbd=accepted_with_tbd,
            comment=comment,
        )

    def record_paired_answer(
        self,
        question_key: str,
        answer: str,
        actor_name: str,
        *,
        unit_ids: tuple[str, ...] = ("AMR-21", "AMR-82"),
    ) -> None:
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                payload={
                    "event_type": "paired_answer",
                    "question_key": question_key,
                    "answer": answer,
                    "unit_ids": list(unit_ids),
                },
            )
            self.state.paired_answers[question_key] = answer
            self.state.paired_units[question_key] = tuple(unit_ids)

    def apply_paired_answer(
        self,
        question_key: str,
        answer: str,
        actor_name: str,
        *,
        paired_unit_ids: tuple[str, ...] = ("AMR-21", "AMR-82"),
        scope_citation: Optional[str] = None,
    ) -> None:
        """FR5/case 19: apply a paired answer to every paired unit, then record it.

        AR5: a paired "no" elects N/A ONLY with an operator-provided positive
        scope citation — the answer itself is never laundered into one; without
        a citation the units land TBD(scope_decision_not_made).
        AR10: elections happen FIRST; the paired answer is recorded only after
        they all succeed, so a crash can never suppress the question while
        leaving its effects unapplied.
        """
        if self.state is None:
            raise SessionError("Session not open")
        ans = (answer or "").strip().lower()
        # N5: validate every election first (deferred), then persist ALL of
        # them + the paired record as ONE atomic eventlog batch — a crash can
        # never leave the pair divergent or the answer half-applied.
        deferred: list = []
        applied_ids: list[str] = []
        for pid in paired_unit_ids:
            if pid not in self.state.units:
                continue
            applied_ids.append(pid)
            if ans in ("yes", "y"):
                self.set_axes(
                    pid,
                    actor_name=actor_name,
                    applicability="yes",
                    applicability_tbd_reason=None,
                    _defer=deferred,
                )
            elif ans in ("no", "n") and (scope_citation or "").strip():
                self.set_axes(
                    pid,
                    actor_name=actor_name,
                    applicability="no",
                    implementation_state="not_reached",
                    organization_responsibility="external",
                    scope_citation=scope_citation,
                    _defer=deferred,
                )
            elif ans in ("no", "n"):
                self.set_axes(
                    pid,
                    actor_name=actor_name,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.SCOPE_DECISION_NOT_MADE,
                    enforce_decision=False,
                    _defer=deferred,
                )
            else:
                self.set_axes(
                    pid,
                    actor_name=actor_name,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    enforce_decision=False,
                    _defer=deferred,
                )
        # AR10 ordering preserved inside the batch: elections precede the
        # record. N9: the record names the units it applied to.
        items = [
            {"actor": d["actor"], "unit_id": d["unit_id"], "payload": d["payload"]}
            for d in deferred
        ]
        items.append(
            {
                "actor": actor_name,
                "payload": {
                    "event_type": "paired_answer",
                    "question_key": question_key,
                    "answer": answer,
                    "unit_ids": applied_ids,
                },
            }
        )
        with self._exclusive_lock():
            self.eventlog.append_many(items)
            for d in deferred:
                self.state.units[d["unit_id"]] = d["unit"]
            self.state.paired_answers[question_key] = answer
            self.state.paired_units[question_key] = tuple(applied_ids)

    def record_library_import(
        self,
        *,
        source_session_id: str,
        dispositions: list[dict[str, Any]],
        action_patterns: list[dict[str, Any]],
        actor_name: str,
    ) -> None:
        """FR5: store imported dispositions/actions as SUGGESTIONS (event-logged).

        Suggestions are shown by the walk with provenance and require normal
        gated election + attestation — never auto-applied.
        """
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                payload={
                    "event_type": "library_imported",
                    "source_session_id": source_session_id,
                    "dispositions": dispositions,
                    "action_patterns": action_patterns,
                },
            )
            for dsp in dispositions:
                rid = dsp.get("requirement_id")
                if rid:
                    self.state.library_suggestions[rid] = dsp
            self.state.library_action_patterns.extend(action_patterns)

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

    def record_answer(
        self,
        unit_id: str,
        question_key: str,
        raw: str,
        *,
        actor_name: str,
    ) -> None:
        """Stage A: store every interview answer verbatim before axis mapping."""
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                unit_id=unit_id,
                payload={
                    "event_type": "answer_recorded",
                    "unit_id": unit_id,
                    "question_key": question_key,
                    "raw": raw,
                    "actor": actor_name,
                },
            )
            self.state.raw_answers.append(
                {
                    "unit_id": unit_id,
                    "question_key": question_key,
                    "raw": raw,
                    "actor": actor_name,
                    "timestamp": _utcnow(),
                }
            )

    def record_action(
        self,
        action: Any,
        *,
        actor_name: str,
    ) -> Any:
        """Stage A: append ActionRecord (supersedes prior by action_id chain)."""
        from oracle.disposition.actions import ActionRecord

        if self.state is None:
            raise SessionError("Session not open")
        if not isinstance(action, ActionRecord):
            action = ActionRecord.model_validate(action)
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                unit_id=action.affected_unit_ids[0] if action.affected_unit_ids else None,
                payload={
                    "event_type": "action_recorded",
                    "action": action.model_dump(mode="json"),
                },
            )
            if action.supersedes and action.supersedes in self.state.actions:
                prior = self.state.actions[action.supersedes]
                self.state.actions[action.supersedes] = prior.model_copy(
                    update={"status": "superseded"}
                )
            self.state.actions[action.action_id] = action
        return action

    def record_work_package(
        self,
        wp: Any,
        *,
        actor_name: str,
    ) -> Any:
        """CR1: append WorkPackageRecord (supersession by wp_id chain)."""
        from oracle.disposition.workpackage import WorkPackageRecord

        if self.state is None:
            raise SessionError("Session not open")
        if not isinstance(wp, WorkPackageRecord):
            wp = WorkPackageRecord.model_validate(wp)
        with self._exclusive_lock():
            self.eventlog.append(
                actor=actor_name,
                payload={
                    "event_type": "work_package_recorded",
                    "work_package": wp.model_dump(mode="json"),
                },
            )
            if wp.supersedes and wp.supersedes in self.state.work_packages:
                prior = self.state.work_packages[wp.supersedes]
                self.state.work_packages[wp.supersedes] = prior.model_copy(
                    update={"status": "superseded"}
                )
            self.state.work_packages[wp.wp_id] = wp
        return wp

    def actions_for_unit(self, unit_id: str) -> list[Any]:
        if self.state is None:
            return []
        return [
            a
            for a in self.state.actions.values()
            if unit_id in a.affected_unit_ids or not a.affected_unit_ids
        ]

    def record_advisor_output(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        actor_name: str,
        unit_id: Optional[str] = None,
    ) -> None:
        """Stage B: log advisor output as proposed-only event."""
        if self.state is None:
            raise SessionError("Session not open")
        with self._exclusive_lock():
            body = {
                "event_type": "advisor_output",
                "kind": kind,
                **payload,
            }
            self.eventlog.append(
                actor=actor_name,
                unit_id=unit_id,
                payload=body,
            )
            self.state.advisor_outputs.append(
                {k: v for k, v in body.items() if k != "event_type"}
            )

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
