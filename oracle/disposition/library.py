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

    # N9: v2 adds paired_citations + paired_units. This model reads v1
    # bundles (missing fields default); v1 readers reject v2 bundles by the
    # version string rather than a bare extra_forbidden error.
    schema_version: str = "rdw-library/v2"
    exported_at: str
    source_session_id: str
    pack_hash: str
    facts: list[dict[str, Any]] = Field(default_factory=list)
    paired_answers: dict[str, str] = Field(default_factory=dict)
    # AR5: a paired "no" only re-elects N/A with the REAL citation the source
    # operator supplied — without it, import lands TBD(scope_decision_not_made).
    paired_citations: dict[str, str] = Field(default_factory=dict)
    # N9: which units each paired answer applied to (self-describing pairs)
    paired_units: dict[str, list[str]] = Field(default_factory=dict)
    dispositions: list[dict[str, Any]] = Field(default_factory=list)
    action_patterns: list[dict[str, Any]] = Field(default_factory=list)


def _matches_blocklist(text: str, patterns: Iterable[str]) -> Optional[str]:
    for pat in patterns:
        if re.search(pat, text or "", re.I):
            return pat
    return None


def _scan_tree(value: Any, path: str, patterns: tuple[str, ...]) -> None:
    """AR6: defense in depth — scan EVERY string leaf of the serialized
    bundle, not an allow-list of fields. Per-field checks above give better
    messages; this pass guarantees nothing (due_or_trigger, work_package,
    ids, provenance, keys) ships unscanned (D-3)."""
    if isinstance(value, str):
        hit = _matches_blocklist(value, patterns)
        if hit:
            raise LibraryError(
                f"Refuse library export: {path} matches engagement "
                f"identifier blocklist pattern {hit!r} (D-3)"
            )
    elif isinstance(value, dict):
        for k, v in value.items():
            _scan_tree(k, f"{path}.<key>", patterns)
            _scan_tree(v, f"{path}.{k}", patterns)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _scan_tree(v, f"{path}[{i}]", patterns)


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

    def _refuse_if_blocked(text: str, field_name: str) -> None:
        """INTEG-2: EVERY exported string is scanned, not just facts (D-3)."""
        hit = _matches_blocklist(text or "", patterns)
        if hit:
            raise LibraryError(
                f"Refuse library export: {field_name} matches engagement "
                f"identifier blocklist pattern {hit!r} (D-3)"
            )

    facts_out: list[dict[str, Any]] = []
    for key, fact in st.facts.items():
        if not fact.confirmed or fact.assumed:
            continue
        _refuse_if_blocked(fact.statement, f"fact {key!r}")
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

    paired_citations: dict[str, str] = {}
    paired_units_out: dict[str, list[str]] = {}
    for qk, ans in st.paired_answers.items():
        _refuse_if_blocked(ans, f"paired answer {qk!r}")
        # N9: the pair membership comes from the session record, not a
        # hardcoded constant — custom pairs survive the round-trip.
        pair_ids = list(st.paired_units.get(qk) or ("AMR-21", "AMR-82"))
        paired_units_out[qk] = pair_ids
        if str(ans).strip().lower() in ("no", "n"):
            # AR5: carry the operator's citation from a paired unit so the
            # answer stays reusable.
            for pid in pair_ids:
                u = st.units.get(pid)
                if u is not None and (u.scope_citation or "").strip():
                    _refuse_if_blocked(
                        u.scope_citation, f"paired citation for {qk!r}"
                    )
                    paired_citations[qk] = u.scope_citation
                    break

    dispositions: list[dict[str, Any]] = []
    for uid, unit in st.units.items():
        if unit.review_state != "accepted":
            continue
        _refuse_if_blocked(unit.comment or "", f"disposition comment on {uid}")
        _refuse_if_blocked(unit.scope_citation or "", f"scope_citation on {uid}")
        _refuse_if_blocked(unit.exception_basis or "", f"exception_basis on {uid}")
        _refuse_if_blocked(
            unit.intent_statement or "", f"intent_statement on {uid}"
        )
        _refuse_if_blocked(
            unit.alternative_control or "", f"alternative_control on {uid}"
        )
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
                    # AR7: without the actor axis a re-imported suggestion
                    # cannot re-elect — exports were not reusable.
                    "obligated_actor": unit.obligated_actor,
                    "organization_responsibility": unit.organization_responsibility,
                    "implementation_state": unit.implementation_state,
                    "approval_state": unit.approval_state,
                },
                "comment": unit.comment,
                "accepted_with_tbd": unit.accepted_with_tbd,
                "provenance": {"session_id": st.session_id},
            }
        )

    actions = []
    for a in st.actions.values():
        if getattr(a, "status", "open") != "open":
            continue
        dumped = a.model_dump(mode="json")
        for fname in ("title", "owner", "deliverable", "exit_criteria", "note"):
            _refuse_if_blocked(
                str(dumped.get(fname) or ""), f"action {a.action_id}.{fname}"
            )
        actions.append(dumped)

    bundle = LibraryBundle(
        exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_session_id=st.session_id,
        pack_hash=st.pack_hash,
        facts=facts_out,
        paired_answers=dict(st.paired_answers),
        paired_citations=paired_citations,
        paired_units=paired_units_out,
        dispositions=dispositions,
        action_patterns=actions,
    )
    _scan_tree(bundle.model_dump(mode="json"), "bundle", patterns)
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
    # N9: refuse unknown future schemas with a version message, not a bare
    # pydantic extra_forbidden error.
    ver = str(data.get("schema_version") or "")
    if ver not in ("rdw-library/v1", "rdw-library/v2"):
        raise LibraryError(
            f"Unsupported library schema_version {ver!r} — this reader "
            "supports rdw-library/v1 and /v2"
        )
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
            # FR5/AF5: apply through the shared gated path — never a silent
            # suppression that leaves paired units untouched. AR5: only a
            # bundled real citation re-elects N/A; otherwise TBD. N9: apply
            # to the pair the bundle names, not a hardcoded default.
            pair_ids = tuple(bundle.paired_units.get(qk) or ("AMR-21", "AMR-82"))
            session.apply_paired_answer(
                qk, ans, actor_name,
                paired_unit_ids=pair_ids,
                scope_citation=bundle.paired_citations.get(qk),
            )
            n_paired += 1
    # FR5: dispositions + action patterns arrive as SUGGESTIONS (event-logged),
    # surfaced by the walk with provenance; election + attestation stay manual.
    n_sug = 0
    if bundle.dispositions or bundle.action_patterns:
        session.record_library_import(
            source_session_id=bundle.source_session_id,
            dispositions=bundle.dispositions,
            action_patterns=bundle.action_patterns,
            actor_name=actor_name,
        )
        n_sug = len(bundle.dispositions)
    LOGGER.info(
        "Library import: %d assumption facts, %d paired answers, %d "
        "disposition suggestions from %s",
        n_facts,
        n_paired,
        n_sug,
        library_path,
    )
    return {
        "facts": n_facts,
        "paired_answers": n_paired,
        "disposition_suggestions": n_sug,
    }
