#!/usr/bin/env python3
"""
Module: oracle.tailor.session
Purpose: A resumable tailoring session over a rule pack — cursor, decisions,
         and durable save.

The whole model: a rule pack is an ordered list of requirements; a session is
a cursor into that list plus a decision per requirement. Nothing else.

Durability is one narrow guarantee — write-temp-rename, so an interrupted save
leaves the previous session intact rather than a truncated file. That is the
piece of provenance machinery worth keeping at this size: it is cheap, and the
alternative is losing an afternoon of judgment to a crash.

Safety Critical: no — advisory tooling; a human makes every disposition here
Financially Critical: no

__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from oracle.disposition.codes import DispositionCode, OPENSubReason

LOGGER = logging.getLogger("oracle.tailor.session")

SCHEMA_VERSION = "tailor/v1"

# WHY OPEN is the default for an undecided unit rather than "unset": OPEN is
# already the vocabulary's "decision incomplete" value (§2.3), so an unfinished
# session renders in exactly the same terms as a finished one. No second
# representation of "we don't know yet" to keep in sync.
UNDECIDED = None


class TailorError(Exception):
    """Raised when a session cannot be loaded, saved, or advanced."""


@dataclass(frozen=True)
class Requirement:
    """One requirement served to the user, projected from the rule pack."""

    id: str
    tag: str
    section: str
    page: Optional[int]
    subject: str
    requirement: str
    shall_text: str
    keywords: tuple[str, ...] = ()

    @classmethod
    def from_pack_entry(cls, e: dict[str, Any]) -> "Requirement":
        return cls(
            id=str(e.get("id") or e.get("source_tag") or "").strip(),
            tag=str(e.get("source_tag") or "").strip(),
            section=str(e.get("section") or "").strip(),
            page=e.get("page"),
            subject=str(e.get("subject") or "").strip(),
            requirement=str(e.get("requirement") or "").strip(),
            shall_text=str(e.get("shall_text") or "").strip(),
            keywords=tuple(e.get("keywords") or ()),
        )


@dataclass
class Decision:
    """A disposition recorded against one requirement."""

    code: DispositionCode
    rationale: str
    decided_at: str
    decided_by: str
    open_sub_reason: Optional[OPENSubReason] = None
    evidence: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "code": self.code.value,
            "rationale": self.rationale,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
        }
        if self.open_sub_reason:
            d["open_sub_reason"] = self.open_sub_reason.value
        if self.evidence:
            d["evidence"] = self.evidence
        if self.note:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Decision":
        sub = d.get("open_sub_reason")
        return cls(
            code=DispositionCode(d["code"]),
            rationale=d.get("rationale", ""),
            decided_at=d.get("decided_at", ""),
            decided_by=d.get("decided_by", ""),
            open_sub_reason=OPENSubReason(sub) if sub else None,
            evidence=d.get("evidence", ""),
            note=d.get("note", ""),
        )


@dataclass
class TailorSession:
    """Cursor + decisions over an ordered rule pack."""

    pack_path: Path
    standard_id: str
    requirements: list[Requirement]
    operator: str
    session_path: Path
    cursor: int = 0
    decisions: dict[str, Decision] = field(default_factory=dict)
    started: str = ""
    # WHY persisted: proposals are only as good as the declared scope, and a
    # resumed session must advise against the same scope it was started with.
    # Re-advising an in-flight session under a different scope would silently
    # make earlier and later dispositions incomparable.
    scope_notes: str = ""

    # ── construction ──────────────────────────────────────────────────────

    @classmethod
    def start(
        cls, pack_path: Path, session_path: Path, operator: str
    ) -> "TailorSession":
        """Begin a new session over a rule pack."""
        pack = _load_json(pack_path)
        entries = pack.get("requirements") or []
        if not entries:
            raise TailorError(f"{pack_path} contains no requirements")
        return cls(
            pack_path=pack_path,
            standard_id=str(pack.get("standard_id") or pack_path.stem),
            requirements=[Requirement.from_pack_entry(e) for e in entries],
            operator=operator,
            session_path=session_path,
            started=_now(),
        )

    @classmethod
    def resume(cls, session_path: Path) -> "TailorSession":
        """Reopen an existing session, re-reading the pack it was started from."""
        state = _load_json(session_path)
        if state.get("schema_version") != SCHEMA_VERSION:
            raise TailorError(
                f"{session_path} has schema_version "
                f"{state.get('schema_version')!r}; expected {SCHEMA_VERSION!r}"
            )
        pack_path = Path(state["pack_path"])
        s = cls.start(pack_path, session_path, state.get("operator", "unknown"))
        s.started = state.get("started", s.started)
        s.cursor = int(state.get("cursor", 0))
        s.scope_notes = state.get("scope_notes", "")
        s.decisions = {
            k: Decision.from_dict(v) for k, v in (state.get("decisions") or {}).items()
        }
        return s

    # ── navigation ────────────────────────────────────────────────────────

    @property
    def total(self) -> int:
        return len(self.requirements)

    @property
    def decided_count(self) -> int:
        return len(self.decisions)

    def current(self) -> Optional[Requirement]:
        """The requirement under the cursor, or None when past the end."""
        if 0 <= self.cursor < self.total:
            return self.requirements[self.cursor]
        return None

    def seek(self, index: int) -> None:
        """Move the cursor, clamped to the pack."""
        self.cursor = max(0, min(index, self.total))

    def seek_id(self, unit_id: str) -> bool:
        """Jump to a requirement by id or tag. Returns False if not found."""
        needle = unit_id.strip().lower()
        for i, r in enumerate(self.requirements):
            if needle in (r.id.lower(), r.tag.lower()):
                self.cursor = i
                return True
        return False

    def advance_to_next_undecided(self) -> None:
        """Move to the next requirement with no decision, else past the end."""
        for i in range(self.cursor, self.total):
            if self.requirements[i].id not in self.decisions:
                self.cursor = i
                return
        self.cursor = self.total

    def undecided(self) -> Iterator[Requirement]:
        return (r for r in self.requirements if r.id not in self.decisions)

    # ── recording ─────────────────────────────────────────────────────────

    def record(
        self,
        code: DispositionCode,
        rationale: str,
        *,
        open_sub_reason: Optional[OPENSubReason] = None,
        evidence: str = "",
        note: str = "",
    ) -> Requirement:
        """Record a disposition for the current requirement.

        A rationale is mandatory. The whole product is the reasoning; a bare
        code with no stated basis is the artifact this tool exists to prevent.
        """
        req = self.current()
        if req is None:
            raise TailorError("cursor is past the end of the pack")
        if not rationale or not rationale.strip():
            raise TailorError("a rationale is required for every disposition")
        if code is DispositionCode.OPEN and open_sub_reason is None:
            raise TailorError("OPEN requires a sub-reason (§2.3)")
        self.decisions[req.id] = Decision(
            code=code,
            rationale=rationale.strip(),
            decided_at=_now(),
            decided_by=self.operator,
            open_sub_reason=open_sub_reason,
            evidence=evidence.strip(),
            note=note.strip(),
        )
        return req

    def clear(self, unit_id: str) -> bool:
        """Remove a recorded decision. Returns False if there was none."""
        return self.decisions.pop(unit_id, None) is not None

    def tally(self) -> dict[str, int]:
        """Count decisions by code — computed, never stored.

        WHY computed: a stored count is a second source of truth that drifts
        from the matrix and gets quoted in briefings. Recompute at render time.
        """
        counts = {c.value: 0 for c in DispositionCode}
        for d in self.decisions.values():
            counts[d.code.value] += 1
        return counts

    # ── persistence ───────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "pack_path": str(self.pack_path),
            "standard_id": self.standard_id,
            "operator": self.operator,
            "started": self.started,
            "scope_notes": self.scope_notes,
            "saved": _now(),
            "cursor": self.cursor,
            "total": self.total,
            "decisions": {k: v.to_dict() for k, v in self.decisions.items()},
        }

    def save(self) -> None:
        """Persist atomically: an interrupted save leaves the prior file intact."""
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        tmp = self.session_path.with_suffix(self.session_path.suffix + ".tmp")
        try:
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.session_path)
        except OSError as exc:
            raise TailorError(f"could not save session to {self.session_path}: {exc}") from exc
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    LOGGER.warning("could not remove temp file %s", tmp)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TailorError(f"could not load {path}: {exc}") from exc
