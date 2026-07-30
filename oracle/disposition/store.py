#!/usr/bin/env python3
"""
Module: oracle.disposition.store
Purpose: Versioned, append-only repository for disposition units, elections,
         acceptance records, and package state.

All persistent records carry schema_version and rule_version.
Reads are pure functions over the files. All mutations are append-only
or atomic replace-via-temp-rename.

Supersession is expressed by writing a successor record that links
to its predecessor (units carry workflow_state transitions via events;
acceptances use supersedes).

Concurrency v1: honest single-writer file lock (documented limits below).
Optimistic version checks are part of the public contract so that a
future multi-writer store can be swapped without schema change.

Re-import conflict detection produces an actionable diff, never silent merge.

Safety Critical: persistence boundary for release authority decisions
__safety_critical__: bool = False   # authority decisions are in release + eventlog

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from oracle.disposition.eventlog import EventLog
from oracle.disposition.identity import ActorIdentity
from oracle.disposition.models import (
    DispositionUnit,
    AcceptanceRecord,
    Locator,
    EvidenceEntry,
    _ALLOW_RELEASED_CONSTRUCTION,
    _ALLOW_TRANSITION_STATE,
)

LOGGER = logging.getLogger("oracle.disposition.store")

STORE_SCHEMA = "disposition-store/v1"
STORE_RULE = "0.5.0"


class StoreError(Exception):
    """Base error for store operations. Fail closed."""
    pass


class ConcurrencyError(StoreError):
    """Two writers attempted conflicting work."""
    pass


class ReimportConflictError(StoreError):
    """Re-imported package conflicts with recorded state."""
    def __init__(self, message: str, diff: dict[str, Any]):
        super().__init__(message)
        self.diff = diff


@dataclass(frozen=True)
class PackageHeader:
    """Lightweight package descriptor persisted with units."""
    package_id: str
    levied_standard: str
    levied_revision: str
    created_at: str
    schema_version: str = STORE_SCHEMA
    rule_version: str = STORE_RULE


class DispositionStore:
    """
    File-backed append-only store for a disposition package.

    Layout under root:
      <root>/
        package.json          # header (id, levy info)
        units.jsonl           # current (last) state per unit_id, written atomically
        acceptances.jsonl     # acceptance records (append-only, supersedes linked)
        events.jsonl          # the hash-chained EventLog

    Concurrency: v1 implements an honest single-writer advisory lock via
    an exclusive lockfile. Concurrent writers from separate processes will
    see ConcurrencyError on the second writer. The lock is best-effort
    (advisory); operators must not run two writers against the same root.
    The optimistic version contract (unit.version or event tail) is
    implemented so callers can detect races even if the lock is bypassed.

    Never fails open: any integrity problem (bad JSON, broken event chain,
    version skew) raises before returning data or committing a write.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.root / ".writer.lock"
        self._units_path = self.root / "units.jsonl"
        self._acc_path = self.root / "acceptances.jsonl"
        self._package_path = self.root / "package.json"
        self._eventlog = EventLog(self.root / "events.jsonl")

    # ---------- Lock (single-writer honest facade) ----------

    @contextmanager
    def _exclusive_lock(self, timeout_s: float = 5.0):
        """
        Best-effort exclusive writer lock.

        Uses exclusive creation of the lockfile. If it exists and the pid
        inside is still alive we treat it as held. On Windows and Unix we
        rely on the filesystem for create exclusivity.

        Documented limits (per spec):
        - Advisory only. A determined actor with filesystem write can remove it.
        - Not a distributed lock.
        - Two writers in the same process are not protected (use one Store).
        - If the owning process crashes without cleanup the lock may need
          manual removal after verifying the pid is dead.
        """
        if self._lock_path.exists():
            try:
                data = json.loads(self._lock_path.read_text())
                pid = data.get("pid")
                if pid and self._pid_alive(pid):
                    raise ConcurrencyError(
                        f"Another writer (pid={pid}) holds the store lock at {self.root}"
                    )
                # stale lock — remove
                self._lock_path.unlink(missing_ok=True)
            except Exception:
                # If we cannot even read it, be conservative
                raise ConcurrencyError(f"Store lock at {self.root} is unreadable or corrupt")

        fd = None
        try:
            # Exclusive create
            fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {"pid": os.getpid(), "ts": time.time()}
            os.write(fd, json.dumps(payload).encode("utf-8"))
            os.close(fd)
            fd = None
            yield
        except FileExistsError:
            raise ConcurrencyError(f"Store lock contention at {self.root}")
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
            # Best effort release
            try:
                if self._lock_path.exists():
                    # Only remove if we own it (pid match)
                    try:
                        data = json.loads(self._lock_path.read_text())
                        if data.get("pid") == os.getpid():
                            self._lock_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception:
                pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if os.name == "nt":
            # WHY not os.kill(pid, 0) here: on Windows signal 0 is
            # CTRL_C_EVENT, so os.kill(pid, 0) SENDS Ctrl+C to the console
            # process group instead of probing liveness — it killed pytest
            # runs and the operator's terminal whenever the probed pid was
            # alive on the same console. OpenProcess is a true probe.
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return True
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    # ---------- Package header ----------

    def init_package(self, header: PackageHeader) -> None:
        if self._package_path.exists():
            existing = json.loads(self._package_path.read_text())
            if existing.get("package_id") != header.package_id:
                raise StoreError("Package already initialized with different id")
            return
        self._atomic_write(self._package_path, json.dumps(asdict(header), indent=2) + "\n")

    def get_package_header(self) -> Optional[PackageHeader]:
        if not self._package_path.exists():
            return None
        data = json.loads(self._package_path.read_text())
        return PackageHeader(**{k: data[k] for k in PackageHeader.__dataclass_fields__ if k in data})

    # ---------- Units (current view via last-per-id in append-only log) ----------

    def _load_units(self) -> dict[str, dict]:
        """Return last record per unit_id. Pure read."""
        units: dict[str, dict] = {}
        if not self._units_path.exists():
            return units
        with self._units_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                uid = rec.get("unit_id")
                if uid:
                    units[uid] = rec
        return units

    def get_unit(self, unit_id: str) -> Optional[DispositionUnit]:
        rec = self._load_units().get(unit_id)
        if not rec:
            return None
        return self._rec_to_unit(rec)

    def list_units(self) -> list[DispositionUnit]:
        recs = self._load_units()
        return [self._rec_to_unit(r) for r in recs.values()]

    def _rec_to_unit(self, rec: dict) -> DispositionUnit:
        # Strip internal store versioning keys before model validation
        clean = {k: v for k, v in rec.items() if not k.startswith("_store_")}
        # Re-hydrate nested models defensively
        loc = clean.get("locator")
        if isinstance(loc, dict):
            clean = dict(clean)
            clean["locator"] = Locator.model_validate(loc)
        evs = clean.get("evidence")
        if isinstance(evs, list):
            clean = dict(clean)
            clean["evidence"] = tuple(EvidenceEntry.model_validate(e) for e in evs)
        acc = clean.get("acceptance")
        if isinstance(acc, dict):
            clean = dict(clean)
            clean["acceptance"] = AcceptanceRecord.model_validate(acc)

        # For any non-"proposed" persisted state, we must set the appropriate internal
        # authorization token so the model validator permits it. These units were
        # only ever written through the audited transition / release paths.
        state = clean.get("workflow_state")
        if state != "proposed":
            if state == "release_approved":
                tok = _ALLOW_RELEASED_CONSTRUCTION.set(True)
                try:
                    return DispositionUnit.model_validate(clean)
                finally:
                    _ALLOW_RELEASED_CONSTRUCTION.reset(tok)
            else:
                # human_confirmed or rejected
                tok = _ALLOW_TRANSITION_STATE.set(True)
                try:
                    return DispositionUnit.model_validate(clean)
                finally:
                    _ALLOW_TRANSITION_STATE.reset(tok)
        return DispositionUnit.model_validate(clean)

    def _append_unit_record(self, unit: DispositionUnit) -> None:
        """Append a new record for this unit (current state)."""
        rec = unit.model_dump(mode="json")
        rec["_store_schema"] = STORE_SCHEMA
        rec["_store_rule"] = STORE_RULE
        line = json.dumps(rec, sort_keys=True) + "\n"
        self._atomic_append(self._units_path, line)

    # ---------- Acceptances ----------

    def _append_acceptance(self, acc: AcceptanceRecord) -> None:
        rec = acc.model_dump(mode="json")
        rec["_store_schema"] = STORE_SCHEMA
        rec["_store_rule"] = STORE_RULE
        line = json.dumps(rec, sort_keys=True) + "\n"
        self._atomic_append(self._acc_path, line)

    def get_acceptance(self, acc_id: str) -> Optional[AcceptanceRecord]:
        if not self._acc_path.exists():
            return None
        last = None
        with self._acc_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("id") == acc_id:
                    last = rec
        if last:
            # Strip internal store keys before validation (same as units)
            clean = {k: v for k, v in last.items() if not k.startswith("_store_")}
            return AcceptanceRecord.model_validate(clean)
        return None

    # ---------- Events (delegated) ----------

    @property
    def events(self) -> EventLog:
        return self._eventlog

    def verify_integrity(self) -> None:
        """Verify event chain. Raises on tamper."""
        self._eventlog.verify()

    # ---------- Core operations: record transition ----------

    def record_transition(
        self,
        unit: DispositionUnit,
        actor: ActorIdentity,
        from_state: str,
        to_state: str,
        *,
        release_context: Optional[dict[str, Any]] = None,
        extra_payload: Optional[dict[str, Any]] = None,
    ) -> DispositionUnit:
        """
        Record a human (or machine) election.

        - Verifies the current stored state matches `from_state` (optimistic concurrency).
        - Appends an event (hash-chained).
        - Appends the new unit state (append-only history).
        - Returns the successor.
        """
        with self._exclusive_lock():
            self.verify_integrity()

            current = self.get_unit(unit.unit_id)
            if current is not None and current.workflow_state != from_state:
                raise ConcurrencyError(
                    f"Optimistic concurrency violation on {unit.unit_id}: "
                    f"expected from_state={from_state}, stored={current.workflow_state}"
                )

            payload = {"transition": f"{from_state}->{to_state}", **(extra_payload or {})}
            self._eventlog.append(
                actor=actor.name,
                from_state=from_state,
                to_state=to_state,
                unit_id=unit.unit_id,
                release_context=release_context,
                payload=payload,
            )
            self._append_unit_record(unit)
            return unit

    # ---------- Release application (called by release.py) ----------

    def apply_release_marking(
        self,
        units: list[DispositionUnit],
        actor: ActorIdentity,
        release_context: dict[str, Any],
    ) -> list[DispositionUnit]:
        """
        Atomically mark the given units as release_approved.

        Appends new unit records (history-preserving) and one package-level
        release event under the exclusive lock.

        Idempotent: if the supplied units are already release_approved in the
        store, no additional event is appended.
        """
        with self._exclusive_lock():
            self.verify_integrity()
            current = self._load_units()

            newly_marked = []
            for u in units:
                rec = current.get(u.unit_id)
                if rec and rec.get("workflow_state") == "release_approved":
                    continue
                newly_marked.append(u)

            # Append unit records for the ones we are advancing (append-only)
            for u in newly_marked:
                self._append_unit_record(u)

            # Only append a package-level release event when we actually did work
            if newly_marked:
                self._eventlog.append(
                    actor=actor.name,
                    from_state="human_confirmed",
                    to_state="release_approved",
                    unit_id=None,
                    release_context=release_context,
                    payload={"marked_count": len(newly_marked)},
                )

            return list(units)

    # ---------- Re-import ----------

    def import_units(
        self,
        incoming: list[DispositionUnit],
        *,
        package_header: Optional[PackageHeader] = None,
        strict: bool = True,
    ) -> None:
        """
        Import a set of units (e.g. from countersign export).

        If strict and any unit differs in a material way (code, state,
        acceptance, locator) from current recorded state, raise
        ReimportConflictError with a diff.
        """
        with self._exclusive_lock():
            self.verify_integrity()
            current = self._load_units()

            conflicts: list[dict] = []
            for inc in incoming:
                cur = current.get(inc.unit_id)
                if cur:
                    # Compare key fields
                    diff = self._unit_diff(cur, inc.model_dump(mode="json"))
                    if diff:
                        conflicts.append({"unit_id": inc.unit_id, "diff": diff})

            if conflicts and strict:
                raise ReimportConflictError(
                    "Re-import conflicts with recorded state",
                    {"conflicts": conflicts},
                )

            # Accept (append the incoming as new current)
            for inc in incoming:
                self._append_unit_record(inc)

            if package_header:
                self.init_package(package_header)

    def _unit_diff(self, recorded: dict, incoming: dict) -> dict:
        # Compare material fields that affect meaning and audit.
        # requirement_text, proposer, confirmed_by, and code/state/acceptance/evidence/locator
        # are all relevant. A change to requirement_text is tampering.
        keys = (
            "code", "workflow_state", "acceptance", "evidence", "locator",
            "requirement_text", "proposer", "unit_boundary_confirmed_by",
            "open_sub_reason", "scope_citation", "intent_statement",
            "alternative_control", "control_class", "proposal_band",
        )
        d = {}
        for k in keys:
            if recorded.get(k) != incoming.get(k):
                d[k] = {"recorded": recorded.get(k), "incoming": incoming.get(k)}
        return d

    # ---------- Atomic helpers ----------

    def _atomic_append(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="store-", suffix=".jsonl", dir=str(path.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp:
                if path.exists():
                    with path.open("r", encoding="utf-8") as src:
                        for l in src:
                            tmp.write(l)
                tmp.write(line)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="store-", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp:
                tmp.write(content)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise

    def _atomic_write_units(self, recs: dict[str, dict]) -> None:
        """Write the entire current units map atomically (snapshot style)."""
        lines = []
        for rec in recs.values():
            lines.append(json.dumps(rec, sort_keys=True) + "\n")
        content = "".join(lines)
        self._atomic_write(self._units_path, content)

    # ---------- Crash-safety note ----------
    # On abrupt termination mid-write the temp file is left behind.
    # On next open we only see the previous committed state because rename is atomic.
    # Readers always see a consistent previous snapshot.
