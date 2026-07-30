#!/usr/bin/env python3
"""
Module: oracle.disposition.eventlog
Purpose: Append-only, hash-chained transition and decision event log.

Every significant state change and release decision is recorded as an
immutable event. The chain provides tamper evidence: any mutation of a
prior event invalidates the hash of all subsequent events.

Verification is a public operation and a broken chain is a hard error
(never a warning or silent continue).

Writes are append-only. Supersession is expressed by new events that
reference prior event ids or record ids, never by rewriting history.

Safety Critical: yes — tamper-evident record of release authority
__safety_critical__: bool = True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

LOGGER = logging.getLogger("oracle.disposition.eventlog")

__safety_critical__: bool = True

SCHEMA_VERSION = "disposition-event/v1"
RULE_VERSION = "0.5.0"


def _canonical_json(obj: Any) -> str:
    """Stable JSON for hashing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    """Compute the chain hash for an event.

    The hash covers the previous hash + the canonical form of the event
    content (without the 'hash' field itself).
    """
    material = {"prev_hash": prev_hash, "payload": payload}
    digest = hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True)
class Event:
    """One immutable event in the log."""

    event_id: str
    prev_hash: str  # "sha256:..." or "" for the genesis event
    timestamp: str  # ISO-8601 UTC
    actor: str
    from_state: Optional[str]
    to_state: Optional[str]
    unit_id: Optional[str]
    release_context: Optional[dict[str, Any]]
    rule_version: str
    payload: dict[str, Any]  # free-form but should be small and stable
    hash: str  # the computed chain hash for this event

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure consistent ordering for external consumers
        return {k: d[k] for k in [
            "event_id", "prev_hash", "timestamp", "actor",
            "from_state", "to_state", "unit_id", "release_context",
            "rule_version", "payload", "hash"
        ]}


class EventLogError(Exception):
    """Base for event log integrity or I/O failures (fail closed)."""
    pass


class EventLog:
    """
    Append-only hash-chained event log backed by a JSONL file.

    All mutations go through append(). Read paths are pure.

    Concurrency: v1 uses an honest single-writer file lock at the
    enclosing store level. The log itself documents that concurrent
    appends from multiple processes are not safe and will corrupt the
    chain or lose events. Callers must serialize at the store.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Touch file so it exists for readers
        if not self.path.exists():
            self.path.touch()

    def _last_hash(self) -> str:
        last = ""
        for ev in self.iter_events():
            last = ev.hash
        return last

    def iter_events(self) -> Iterator[Event]:
        """Yield events in order from the file. Does not verify."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    yield Event(**data)
                except Exception as e:
                    raise EventLogError(f"Corrupt event at line {lineno}: {e}") from e

    def verify(self) -> None:
        """
        Verify the entire chain.

        Raises EventLogError on any break (missing prev, wrong hash,
        out-of-order, etc.). A broken chain is fatal.
        """
        prev = ""
        for ev in self.iter_events():
            expected = _compute_hash(prev, {
                "event_id": ev.event_id,
                "timestamp": ev.timestamp,
                "actor": ev.actor,
                "from_state": ev.from_state,
                "to_state": ev.to_state,
                "unit_id": ev.unit_id,
                "release_context": ev.release_context,
                "rule_version": ev.rule_version,
                "payload": ev.payload,
            })
            if ev.prev_hash != prev:
                raise EventLogError(
                    f"Chain break at {ev.event_id}: prev_hash mismatch "
                    f"(expected {prev!r}, got {ev.prev_hash!r})"
                )
            if ev.hash != expected:
                raise EventLogError(
                    f"Chain break at {ev.event_id}: hash mismatch "
                    f"(event content was tampered or hash is wrong)"
                )
            prev = ev.hash

    def append(
        self,
        *,
        actor: str,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        unit_id: Optional[str] = None,
        release_context: Optional[dict[str, Any]] = None,
        payload: Optional[dict[str, Any]] = None,
        rule_version: str = RULE_VERSION,
    ) -> Event:
        """
        Append a new event. Returns the written Event.

        This is a low-level append. Higher layers (release, store,
        identity) supply structured payload and ensure the event
        describes a meaningful decision.

        Atomicity: write to a temp file then rename into place.
        On any write failure the log is left unchanged.
        """
        prev_hash = self._last_hash()

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        event_id = f"evt-{now.replace(':', '').replace('-', '')}-{hashlib.sha256(str(os.getpid()).encode()).hexdigest()[:8]}"

        content_payload = payload or {}
        # Always include a stable schema marker
        content_payload.setdefault("_schema", SCHEMA_VERSION)

        hash_value = _compute_hash(prev_hash, {
            "event_id": event_id,
            "timestamp": now,
            "actor": actor,
            "from_state": from_state,
            "to_state": to_state,
            "unit_id": unit_id,
            "release_context": release_context,
            "rule_version": rule_version,
            "payload": content_payload,
        })

        ev = Event(
            event_id=event_id,
            prev_hash=prev_hash,
            timestamp=now,
            actor=actor,
            from_state=from_state,
            to_state=to_state,
            unit_id=unit_id,
            release_context=release_context,
            rule_version=rule_version,
            payload=content_payload,
            hash=hash_value,
        )

        # Atomic append via temp + rename
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="eventlog-", suffix=".jsonl", dir=str(self.path.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp:
                # Copy existing content
                if self.path.exists():
                    with self.path.open("r", encoding="utf-8") as src:
                        for line in src:
                            tmp.write(line)
                # Append new line
                tmp.write(_canonical_json(ev.to_json_dict()) + "\n")
            os.replace(tmp_name, self.path)
        except Exception:
            # Best effort cleanup
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise

        LOGGER.info("eventlog.append id=%s actor=%s %s->%s unit=%s", event_id, actor, from_state, to_state, unit_id)
        return ev

    def tail(self, n: int = 10) -> list[Event]:
        """Return the last n events (most recent last)."""
        events = list(self.iter_events())
        return events[-n:]
