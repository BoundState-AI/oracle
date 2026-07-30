#!/usr/bin/env python3
"""
Module: oracle.disposition.export
Purpose: Supplier matrix CSV + DOCX exports (RDW Stage E).

Counts computed from the matrix at render. Refuse phantom artifact refs.
Every artifact carries the D-1 advisory banner.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from oracle.disposition.codes import ExportLabel
from oracle.disposition.rulepack import RequirementRecord
from oracle.disposition.session import DispositionSession, Fact, UnitAxesState

LOGGER = logging.getLogger("oracle.disposition.export")

ADVISORY_BANNER = (
    "ADVISORY ONLY: This artifact supports, and never substitutes for, a "
    "qualified human compliance determination (BoundState D-1)."
)

SPEC_VERSIONS = {
    "rdw_spec": "0.2",
    "oracle_disposition_spec": "0.5.0",
    "export_schema": "rdw-export/v0",
}


class ExportError(Exception):
    """Export refused (phantom ref, empty session, etc.)."""


@dataclass(frozen=True)
class MatrixRow:
    unit_id: str
    text_ref: str
    applicability: str
    obligated_actor: str
    organization_responsibility: str
    implementation_state: str
    approval_state: str
    export_label: str
    comment: str
    evidence_refs: str
    actions: str


def _text_ref(rec: Optional[RequirementRecord], unit_id: str) -> str:
    if rec is None:
        return unit_id
    loc = rec.locator
    page = f" p.{loc.page}" if loc.page else ""
    return f"{loc.standard} {loc.revision} §{loc.section}{page}"


def build_matrix_rows(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    *,
    known_artifact_ids: Optional[set[str]] = None,
) -> list[MatrixRow]:
    """Build matrix rows; refuse rows that cite nonexistent artifacts."""
    if session.state is None:
        raise ExportError("Session not open")
    known = known_artifact_ids or set()
    # Always allow evidence refs recorded on the unit itself
    rows: list[MatrixRow] = []
    for uid, unit in sorted(session.state.units.items()):
        for ref in unit.evidence_refs:
            # Case 23: refuse phantom refs not in known set when set is provided
            if known_artifact_ids is not None and ref.doc_id not in known:
                # Unit-local refs are always accepted if attached via session
                if ref.doc_id not in {r.doc_id for r in unit.evidence_refs}:
                    raise ExportError(
                        f"Refuse export: unit {uid} references nonexistent artifact {ref.doc_id!r}"
                    )
        # Stricter API: caller may pass known_artifact_ids that must cover refs
        if known_artifact_ids is not None:
            for ref in unit.evidence_refs:
                if ref.doc_id not in known_artifact_ids:
                    raise ExportError(
                        f"Refuse export: unit {uid} references nonexistent artifact {ref.doc_id!r}"
                    )
        try:
            label = unit.export_label().value
        except Exception as e:
            raise ExportError(f"Unit {uid} axes do not map: {e}") from e
        rec = records.get(uid)
        rows.append(
            MatrixRow(
                unit_id=uid,
                text_ref=_text_ref(rec, uid),
                applicability=str(unit.applicability),
                obligated_actor=str(unit.obligated_actor or ""),
                organization_responsibility=str(unit.organization_responsibility),
                implementation_state=str(unit.implementation_state),
                approval_state=str(unit.approval_state),
                export_label=label,
                comment=unit.comment or "",
                evidence_refs="; ".join(
                    f"{r.doc_id}@{r.revision}" for r in unit.evidence_refs
                ),
                actions="; ".join(unit.open_actions),
            )
        )
    return rows


def count_by_export_label(rows: list[MatrixRow]) -> dict[str, int]:
    """Case 22: every count computed from the matrix at render."""
    counts: dict[str, int] = {lab.value: 0 for lab in ExportLabel}
    for r in rows:
        counts[r.export_label] = counts.get(r.export_label, 0) + 1
    return counts


def assumptions_log(session: DispositionSession) -> list[Fact]:
    if session.state is None:
        return []
    return [f for f in session.state.facts.values() if f.assumed]


def tbd_register(rows: list[MatrixRow], session: DispositionSession) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if session.state is None:
        return out
    for r in rows:
        if r.export_label != ExportLabel.TBD.value:
            continue
        u = session.state.units[r.unit_id]
        reasons = []
        if u.applicability == "tbd":
            reasons.append(f"applicability:{u.applicability_tbd_reason}")
        if u.implementation_state == "tbd":
            reasons.append(f"implementation:{u.implementation_tbd_reason}")
        if u.approval_state == "tbd":
            reasons.append(f"approval:{u.approval_tbd_reason}")
        out.append({"unit_id": r.unit_id, "reasons": "; ".join(reasons)})
    return out


def open_action_register(session: DispositionSession) -> list[dict[str, str]]:
    if session.state is None:
        return []
    actions: list[dict[str, str]] = []
    for uid, u in session.state.units.items():
        for a in u.open_actions:
            actions.append({"unit_id": uid, "action": a})
    return actions


def export_csv(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    path: Path | str,
    *,
    known_artifact_ids: Optional[set[str]] = None,
) -> Path:
    rows = build_matrix_rows(session, records, known_artifact_ids=known_artifact_ids)
    counts = count_by_export_label(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    buf = io.StringIO()
    buf.write(f"# {ADVISORY_BANNER}\n")
    st = session.state
    assert st is not None
    buf.write(
        f"# session_id={st.session_id} pack_hash={st.pack_hash} "
        f"rdw={SPEC_VERSIONS['rdw_spec']} engine={SPEC_VERSIONS['oracle_disposition_spec']}\n"
    )
    buf.write(f"# counts={counts}\n")

    writer = csv.writer(buf)
    writer.writerow(
        [
            "unit_id",
            "text_ref",
            "applicability",
            "obligated_actor",
            "organization_responsibility",
            "implementation_state",
            "approval_state",
            "export_label",
            "comment",
            "evidence_refs",
            "actions",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.unit_id,
                r.text_ref,
                r.applicability,
                r.obligated_actor,
                r.organization_responsibility,
                r.implementation_state,
                r.approval_state,
                r.export_label,
                r.comment,
                r.evidence_refs,
                r.actions,
            ]
        )

    # Registers as comment sections
    buf.write("\n# --- Assumptions log ---\n")
    for f in assumptions_log(session):
        buf.write(f"# ASSUMPTION {f.key}: {f.statement} (owner={f.owner})\n")
    buf.write("# --- TBD register ---\n")
    for t in tbd_register(rows, session):
        buf.write(f"# TBD {t['unit_id']}: {t['reasons']}\n")
    buf.write("# --- Open actions ---\n")
    for a in open_action_register(session):
        buf.write(f"# ACTION {a['unit_id']}: {a['action']}\n")

    path.write_text(buf.getvalue(), encoding="utf-8")
    LOGGER.info("Wrote CSV export to %s (%d rows)", path, len(rows))
    return path


def export_docx(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    path: Path | str,
    *,
    known_artifact_ids: Optional[set[str]] = None,
) -> Path:
    try:
        from docx import Document
    except ImportError as e:
        raise ExportError(
            "python-docx is required for DOCX export (already a repo dependency)"
        ) from e

    rows = build_matrix_rows(session, records, known_artifact_ids=known_artifact_ids)
    counts = count_by_export_label(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    doc.add_heading("Supplier Disposition Matrix", level=1)
    doc.add_paragraph(ADVISORY_BANNER)
    st = session.state
    assert st is not None
    doc.add_paragraph(
        f"session_id={st.session_id} | pack_hash={st.pack_hash} | "
        f"RDW {SPEC_VERSIONS['rdw_spec']} | engine {SPEC_VERSIONS['oracle_disposition_spec']}"
    )
    doc.add_paragraph("Counts (computed from matrix): " + ", ".join(
        f"{k}={v}" for k, v in counts.items() if v
    ))

    table = doc.add_table(rows=1, cols=6)
    hdr = table.rows[0].cells
    for i, name in enumerate(
        ["Unit", "Text ref", "Label", "Axes", "Comment", "Evidence"]
    ):
        hdr[i].text = name
    for r in rows:
        cells = table.add_row().cells
        cells[0].text = r.unit_id
        cells[1].text = r.text_ref
        cells[2].text = r.export_label
        cells[3].text = (
            f"app={r.applicability}; actor={r.obligated_actor}; "
            f"org={r.organization_responsibility}; impl={r.implementation_state}; "
            f"appr={r.approval_state}"
        )
        cells[4].text = r.comment
        cells[5].text = r.evidence_refs

    doc.add_heading("Assumptions log", level=2)
    for f in assumptions_log(session):
        doc.add_paragraph(f"{f.key}: {f.statement} (owner={f.owner})", style="List Bullet")

    doc.add_heading("TBD register", level=2)
    for t in tbd_register(rows, session):
        doc.add_paragraph(f"{t['unit_id']}: {t['reasons']}", style="List Bullet")

    doc.add_heading("Open-action register", level=2)
    for a in open_action_register(session):
        doc.add_paragraph(f"{a['unit_id']}: {a['action']}", style="List Bullet")

    doc.save(str(path))
    LOGGER.info("Wrote DOCX export to %s (%d rows)", path, len(rows))
    return path


def stamp_meta(session: DispositionSession) -> dict[str, Any]:
    st = session.state
    assert st is not None
    return {
        "session_id": st.session_id,
        "pack_hash": st.pack_hash,
        "spec_versions": SPEC_VERSIONS,
        "banner": ADVISORY_BANNER,
    }
