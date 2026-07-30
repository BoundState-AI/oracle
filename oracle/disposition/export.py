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
    enforce_decision: bool = True,
    require_review_accepted: bool = False,
) -> list[MatrixRow]:
    """Build matrix rows; refuse phantom refs and decision-blocked labels (C1)."""
    if session.state is None:
        raise ExportError("Session not open")
    from oracle.disposition.comments import prohibited_language_hits
    from oracle.disposition.decision import evaluate_unit
    from oracle.disposition.graph import DependencyGraph

    graph = DependencyGraph.from_seeds()
    rows: list[MatrixRow] = []
    for uid, unit in sorted(session.state.units.items()):
        # Case 23: refuse phantom refs when known set provided
        if known_artifact_ids is not None:
            for ref in unit.evidence_refs:
                if ref.doc_id not in known_artifact_ids:
                    raise ExportError(
                        f"Refuse export: unit {uid} references nonexistent "
                        f"artifact {ref.doc_id!r}"
                    )
        try:
            label = unit.export_label().value
        except Exception as e:
            raise ExportError(f"Unit {uid} axes do not map: {e}") from e

        # C1: §13.2 on stored comment
        if unit.comment:
            hits = prohibited_language_hits(unit.comment)
            if hits:
                raise ExportError(
                    f"Refuse export: unit {uid} comment fails §13.2: {hits}"
                )

        if enforce_decision:
            has_ev = bool(unit.evidence_refs)
            decision = evaluate_unit(
                unit,
                facts=session.state.facts,
                graph=graph,
                has_scope_rationale=bool(unit.scope_citation),
                has_evidence_for_meet=has_ev,
            )
            if label in decision.blocked:
                raise ExportError(
                    f"Refuse export: unit {uid} label {label!r} blocked "
                    f"({decision.blocked[label]})"
                )

        if require_review_accepted and unit.review_state != "accepted":
            raise ExportError(
                f"Refuse export: unit {uid} review_state={unit.review_state!r} "
                "(not accepted)"
            )

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
    enforce_decision: bool = True,
) -> Path:
    rows = build_matrix_rows(
        session,
        records,
        known_artifact_ids=known_artifact_ids,
        enforce_decision=enforce_decision,
    )
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
    enforce_decision: bool = True,
) -> Path:
    try:
        from docx import Document
    except ImportError as e:
        raise ExportError(
            "python-docx is required for DOCX export (already a repo dependency)"
        ) from e

    rows = build_matrix_rows(
        session,
        records,
        known_artifact_ids=known_artifact_ids,
        enforce_decision=enforce_decision,
    )
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


def _xlsx_sheet_xml(headers: list[str], rows: list[list[str]]) -> str:
    """Minimal SpreadsheetML worksheet (shared strings avoided — inline)."""
    def cell(ref: str, val: str) -> str:
        # Escape XML
        safe = (
            val.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        return f'<c r="{ref}" t="inlineStr"><is><t>{safe}</t></is></c>'

    def col_letter(i: int) -> str:
        s = ""
        n = i
        while True:
            s = chr(ord("A") + (n % 26)) + s
            n = n // 26 - 1
            if n < 0:
                break
        return s

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    all_rows = [headers] + rows
    for r_idx, row in enumerate(all_rows, start=1):
        lines.append(f'<row r="{r_idx}">')
        for c_idx, val in enumerate(row):
            ref = f"{col_letter(c_idx)}{r_idx}"
            lines.append(cell(ref, str(val)))
        lines.append("</row>")
    lines.append("</sheetData></worksheet>")
    return "".join(lines)


def export_xlsx(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    path: Path | str,
    *,
    known_artifact_ids: Optional[set[str]] = None,
    enforce_decision: bool = True,
    evidence_rows: Optional[list[list[str]]] = None,
) -> Path:
    """
    Phase 2: supplier matrix as XLSX using stdlib zipfile (no new dependency).

    Sheets: Matrix, Assumptions, TBD, OpenActions, Meta.
    """
    import zipfile

    rows = build_matrix_rows(
        session,
        records,
        known_artifact_ids=known_artifact_ids,
        enforce_decision=enforce_decision,
    )
    counts = count_by_export_label(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    st = session.state
    assert st is not None

    matrix_headers = [
        "unit_id", "text_ref", "applicability", "obligated_actor",
        "organization_responsibility", "implementation_state", "approval_state",
        "export_label", "comment", "evidence_refs", "actions",
    ]
    matrix_data = [
        [
            r.unit_id, r.text_ref, r.applicability, r.obligated_actor,
            r.organization_responsibility, r.implementation_state, r.approval_state,
            r.export_label, r.comment, r.evidence_refs, r.actions,
        ]
        for r in rows
    ]
    assump = assumptions_log(session)
    assump_data = [[f.key, f.statement, f.owner or "", f.confidence] for f in assump]
    tbd = tbd_register(rows, session)
    tbd_data = [[t["unit_id"], t["reasons"]] for t in tbd]
    actions = open_action_register(session)
    act_data = [[a["unit_id"], a["action"]] for a in actions]
    # H5: evidence register sheet
    ev_data = evidence_rows or []
    if not ev_data:
        for r in rows:
            if r.evidence_refs:
                for part in r.evidence_refs.split("; "):
                    if part:
                        ev_data.append([r.unit_id, part, ""])
    meta_data = [
        ["banner", ADVISORY_BANNER],
        ["session_id", st.session_id],
        ["pack_hash", st.pack_hash],
        ["rdw_spec", SPEC_VERSIONS["rdw_spec"]],
        ["engine_spec", SPEC_VERSIONS["oracle_disposition_spec"]],
        ["counts", str(counts)],
    ]

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet4.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet5.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet6.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    wb_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet4.xml"/>
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet5.xml"/>
  <Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet6.xml"/>
</Relationships>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Matrix" sheetId="1" r:id="rId1"/>
    <sheet name="Assumptions" sheetId="2" r:id="rId2"/>
    <sheet name="TBD" sheetId="3" r:id="rId3"/>
    <sheet name="OpenActions" sheetId="4" r:id="rId4"/>
    <sheet name="Evidence" sheetId="5" r:id="rId5"/>
    <sheet name="Meta" sheetId="6" r:id="rId6"/>
  </sheets>
</workbook>"""

    sheets = [
        _xlsx_sheet_xml(matrix_headers, matrix_data),
        _xlsx_sheet_xml(["key", "statement", "owner", "confidence"], assump_data),
        _xlsx_sheet_xml(["unit_id", "reasons"], tbd_data),
        _xlsx_sheet_xml(["unit_id", "action"], act_data),
        _xlsx_sheet_xml(["unit_id", "evidence_ref", "note"], ev_data),
        _xlsx_sheet_xml(["field", "value"], meta_data),
    ]

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        for i, xml in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", xml)

    LOGGER.info("Wrote XLSX export to %s (%d rows)", path, len(rows))
    return path


def export_all(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    out_dir: Path | str,
    *,
    known_artifact_ids: Optional[set[str]] = None,
    enforce_decision: bool = True,
) -> dict[str, Path]:
    """Write CSV + DOCX + XLSX suite under out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # H5: if known set omitted, synthesize from unit evidence refs (non-phantom)
    if known_artifact_ids is None and session.state is not None:
        known_artifact_ids = set()
        for u in session.state.units.values():
            for r in u.evidence_refs:
                known_artifact_ids.add(r.doc_id)
    paths = {
        "csv": export_csv(
            session,
            records,
            out / "supplier_matrix.csv",
            known_artifact_ids=known_artifact_ids,
            enforce_decision=enforce_decision,
        ),
        "docx": export_docx(
            session,
            records,
            out / "supplier_matrix.docx",
            known_artifact_ids=known_artifact_ids,
            enforce_decision=enforce_decision,
        ),
        "xlsx": export_xlsx(
            session,
            records,
            out / "supplier_matrix.xlsx",
            known_artifact_ids=known_artifact_ids,
            enforce_decision=enforce_decision,
        ),
    }
    return paths
