#!/usr/bin/env python3
"""
Module: oracle.disposition.library
Purpose: Stage D — cross-project context library export/import.

Export confirmed facts, paired answers, attested dispositions, action patterns.
Import seeds facts as assumptions only. Engagement-identifier blocklist (D-3).

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field

from oracle.disposition.session import DispositionSession, SessionError

LOGGER = logging.getLogger("oracle.disposition.library")

# Default engagement-identifier patterns (operator may extend)
DEFAULT_BLOCKLIST_PATTERNS: tuple[str, ...] = (
    r"\bCAGE\s*[:=]?\s*\w+",
    r"\bcontract\s*(no\.?|number|#)\s*[:=]?\s*\w+",
    r"\bNN[A-Z]?\d{5,}",  # NASA contract-like
    r"@\w+\.(com|gov|mil)\b",
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN-like
)


class LibraryError(Exception):
    """Library export/import refused."""


class LibraryBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rdw-library/v1"
    exported_at: str
    source_session_id: str
    pack_hash: str
    facts: list[dict[str, Any]] = Field(default_factory=list)
    paired_answers: dict[str, str] = Field(default_factory=dict)
    dispositions: list[dict[str, Any]] = Field(default_factory=list)
    action_patterns: list[dict[str, Any]] = Field(default_factory=list)


def _matches_blocklist(text: str, patterns: Iterable[str]) -> Optional[str]:
    for pat in patterns:
        if re.search(pat, text or "", re.I):
            return pat
    return None


def export_library(
    session: DispositionSession,
    out_path: Path | str,
    *,
    blocklist: Optional[Iterable[str]] = None,
) -> Path:
    """
    Export scrubbed learning bundle. Refuses if any fact statement matches
    the engagement-identifier blocklist.
    """
    if session.state is None:
        raise SessionError("Session not open")
    patterns = tuple(blocklist) if blocklist is not None else DEFAULT_BLOCKLIST_PATTERNS
    st = session.state

    facts_out: list[dict[str, Any]] = []
    for key, fact in st.facts.items():
        if not fact.confirmed or fact.assumed:
            continue
        hit = _matches_blocklist(fact.statement, patterns)
        if hit:
            raise LibraryError(
                f"Refuse library export: fact {key!r} matches engagement "
                f"identifier blocklist pattern {hit!r} (D-3)"
            )
        facts_out.append(
            {
                "key": key,
                "statement": fact.statement,
                "kind": fact.kind,
                "confidence": fact.confidence,
                "provenance": {
                    "session_id": st.session_id,
                    "fact_id": fact.fact_id,
                    "timestamp": fact.timestamp,
                },
            }
        )

    dispositions: list[dict[str, Any]] = []
    for uid, unit in st.units.items():
        if unit.review_state != "accepted":
            continue
        try:
            label = unit.export_label().value
        except Exception:
            label = None
        dispositions.append(
            {
                "requirement_id": uid,
                "export_label": label,
                "axes": {
                    "applicability": unit.applicability,
                    "organization_responsibility": unit.organization_responsibility,
                    "implementation_state": unit.implementation_state,
                    "approval_state": unit.approval_state,
                },
                "comment": unit.comment,
                "accepted_with_tbd": unit.accepted_with_tbd,
                "provenance": {"session_id": st.session_id},
            }
        )

    actions = [
        a.model_dump(mode="json")
        for a in st.actions.values()
        if getattr(a, "status", "open") == "open"
    ]

    bundle = LibraryBundle(
        exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_session_id=st.session_id,
        pack_hash=st.pack_hash,
        facts=facts_out,
        paired_answers=dict(st.paired_answers),
        dispositions=dispositions,
        action_patterns=actions,
    )
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    LOGGER.info("Library export wrote %s (%d facts)", path, len(facts_out))
    return path


def import_library(
    session: DispositionSession,
    library_path: Path | str,
    *,
    actor_name: str,
    owner: Optional[str] = None,
) -> dict[str, int]:
    """
    Pre-seed facts as assumptions and paired answers from a library bundle.

    Nothing imported is confirmed until the operator confirms it.
    """
    if session.state is None:
        raise SessionError("Session not open")
    data = json.loads(Path(library_path).read_text(encoding="utf-8"))
    bundle = LibraryBundle.model_validate(data)
    owner = owner or actor_name
    n_facts = 0
    for f in bundle.facts:
        key = f["key"]
        # Skip if already present
        if key in session.state.facts:
            continue
        prov = f.get("provenance") or {}
        source = (
            f"library:{prov.get('session_id', bundle.source_session_id)}"
        )
        session.assert_fact(
            key=key,
            statement=f["statement"],
            author=actor_name,
            assumed=True,
            owner=owner,
            confidence=f.get("confidence") or "low",
            source=source,
        )
        n_facts += 1
    n_paired = 0
    for qk, ans in bundle.paired_answers.items():
        if qk not in session.state.paired_answers:
            session.record_paired_answer(qk, ans, actor_name)
            n_paired += 1
    LOGGER.info(
        "Library import: %d assumption facts, %d paired answers from %s",
        n_facts,
        n_paired,
        library_path,
    )
    return {"facts": n_facts, "paired_answers": n_paired}
