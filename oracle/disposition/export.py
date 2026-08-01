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
import re
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


# Stamp when phantom-ref check is skipped (no evidence registry). Must appear in Meta.
PHANTOM_REF_SKIPPED = "phantom-ref check: skipped (no evidence registry)"


def _normalize_known_artifacts(
    known: Optional[set[Any]],
) -> Optional[set[tuple[str, str]]]:
    """
    F2: known artifacts are (doc_id, revision) pairs.

    Accepts legacy set[str] of doc_ids (maps to (doc_id, "*") wildcard) for
    older callers; prefer explicit pairs.
    """
    if known is None:
        return None
    out: set[tuple[str, str]] = set()
    for item in known:
        if isinstance(item, tuple) and len(item) == 2:
            out.add((str(item[0]), str(item[1])))
        else:
            # legacy doc_id-only: match any revision via sentinel
            out.add((str(item), "*"))
    return out


def build_matrix_rows(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    *,
    known_artifact_ids: Optional[set[Any]] = None,
    enforce_decision: bool = True,
    require_review_accepted: bool = False,
) -> list[MatrixRow]:
    """Build matrix rows; refuse phantom refs, rereview, and blocked labels."""
    if session.state is None:
        raise ExportError("Session not open")
    from oracle.disposition.comments import prohibited_language_hits
    from oracle.disposition.decision import evaluate_unit
    from oracle.disposition.graph import DependencyGraph

    graph = DependencyGraph.from_seeds()
    known_pairs = _normalize_known_artifacts(known_artifact_ids)

    # F1: units needing re-review must not export (no bypass flag)
    rereview = set(session.state.needs_rereview)
    if rereview:
        bad = sorted(uid for uid in rereview if uid in session.state.units)
        if bad:
            raise ExportError(
                f"Refuse export: units need re-review before export: {', '.join(bad)}"
            )

    rows: list[MatrixRow] = []
    for uid, unit in sorted(session.state.units.items()):
        # F2 Case 23: phantom-ref on (doc_id, revision) when known set provided
        if known_pairs is not None:
            for ref in unit.evidence_refs:
                pair = (ref.doc_id, ref.revision)
                exact = pair in known_pairs
                wildcard = (ref.doc_id, "*") in known_pairs
                if not exact and not wildcard:
                    raise ExportError(
                        f"Refuse export: unit {uid} references nonexistent "
                        f"artifact {ref.doc_id!r}@{ref.revision!r}"
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
            # F2: qualifying Meet evidence (registry-aware)
            has_ev = session.has_qualifying_meet_evidence(unit)
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
        if u.execution_state == "tbd":
            reasons.append(f"execution:{u.implementation_tbd_reason}")
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
    known_artifact_ids: Optional[set[Any]] = None,
    enforce_decision: bool = True,
    phantom_ref_note: Optional[str] = None,
    include_draft: bool = False,
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
    if phantom_ref_note:
        buf.write(f"# {phantom_ref_note}\n")
    draft_note = _release_note(session, include_draft=include_draft)
    if draft_note:
        buf.write(f"# {draft_note}\n")

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
    known_artifact_ids: Optional[set[Any]] = None,
    enforce_decision: bool = True,
    phantom_ref_note: Optional[str] = None,
    include_draft: bool = False,
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
    if phantom_ref_note:
        doc.add_paragraph(phantom_ref_note)
    draft_note = _release_note(session, include_draft=include_draft)
    if draft_note:
        doc.add_paragraph(draft_note)

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
    known_artifact_ids: Optional[set[Any]] = None,
    enforce_decision: bool = True,
    evidence_rows: Optional[list[list[str]]] = None,
    phantom_ref_note: Optional[str] = None,
    include_draft: bool = False,
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
    if phantom_ref_note:
        meta_data.append(["phantom_ref_check", phantom_ref_note])
    draft_note = _release_note(session, include_draft=include_draft)
    if draft_note:
        meta_data.append(["release_state", draft_note])

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


def _release_note(
    session: DispositionSession,
    *,
    include_draft: bool,
    unit_pred: Optional[Any] = None,
) -> Optional[str]:
    """M4 (Fran P1): external products require review-accepted rows.

    Strict (default) refuses naming the unaccepted units; include_draft
    trades refusal for an explicit DRAFT watermark on every product.
    unit_pred scopes the gate to the rows the product actually exports
    (Atlas M4-4: Appendix A must not refuse over excluded EFCR rows)."""
    assert session.state is not None
    unaccepted = [
        uid
        for uid, u in sorted(session.state.units.items())
        if (unit_pred is None or unit_pred(uid)) and u.review_state != "accepted"
    ]
    if not unaccepted:
        return None
    if not include_draft:
        raise ExportError(
            f"Refuse export: {len(unaccepted)} unit(s) not review-accepted "
            f"(first: {', '.join(unaccepted[:5])}). Use include_draft "
            "(--include-draft) for a DRAFT-watermarked working copy."
        )
    return (
        f"DRAFT — NOT RELEASABLE: {len(unaccepted)} unit(s) not "
        "review-accepted"
    )


def export_all(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    out_dir: Path | str,
    *,
    known_artifact_ids: Optional[set[Any]] = None,
    enforce_decision: bool = True,
    include_draft: bool = False,
) -> dict[str, Path]:
    """
    Write CSV + DOCX + XLSX suite under out_dir.

    F2: never synthesize the known-set from the refs under validation.
    When known_artifact_ids is omitted, load from session evidence registry if
    present; otherwise skip the phantom check and stamp that fact into Meta
    (CSV comment / DOCX paragraph / XLSX Meta sheet). No silent skip.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _release_note(session, include_draft=include_draft)  # fail fast
    phantom_note: Optional[str] = None
    if known_artifact_ids is None:
        store = session.evidence_store()
        if store is not None:
            known_artifact_ids = store.known_doc_revisions()
        else:
            phantom_note = PHANTOM_REF_SKIPPED
            # leave known_artifact_ids None → no phantom enforcement
    paths = {
        "csv": export_csv(
            session,
            records,
            out / "supplier_matrix.csv",
            known_artifact_ids=known_artifact_ids,
            enforce_decision=enforce_decision,
            phantom_ref_note=phantom_note,
            include_draft=include_draft,
        ),
        "docx": export_docx(
            session,
            records,
            out / "supplier_matrix.docx",
            known_artifact_ids=known_artifact_ids,
            enforce_decision=enforce_decision,
            phantom_ref_note=phantom_note,
            include_draft=include_draft,
        ),
        "xlsx": export_xlsx(
            session,
            records,
            out / "supplier_matrix.xlsx",
            known_artifact_ids=known_artifact_ids,
            enforce_decision=enforce_decision,
            phantom_ref_note=phantom_note,
            include_draft=include_draft,
        ),
    }
    return paths


def export_appendix_a(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    path: Path | str,
    *,
    enforce_decision: bool = True,
    include_draft: bool = False,
) -> Path:
    """
    Stage E external product: Appendix-A-format compliance matrix.

    Columns: Section / Description / Requirement / Applicable / Comments
    (contract-label view). Counts computed at render. D-1 banner.
    """
    if session.state is None:
        raise ExportError("Session not open")
    draft_note = _release_note(
        session, include_draft=include_draft,
        unit_pred=lambda uid: uid.upper().startswith("AMR-"),
    )
    # Reuse matrix rows for refusal discipline, then reshape
    rows = build_matrix_rows(
        session, records, enforce_decision=enforce_decision
    )
    # AR12: Appendix A is the 6030 AMR matrix — EFCR (6033) rows belong to
    # the internal products, not this deliverable.
    rows = [r for r in rows if r.unit_id.upper().startswith("AMR-")]
    counts = count_by_export_label(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    st = session.state
    buf = io.StringIO()
    buf.write(f"# {ADVISORY_BANNER}\n")
    if draft_note:
        buf.write(f"# {draft_note}\n")
    buf.write(
        f"# Appendix A format | session_id={st.session_id} "
        f"pack_hash={st.pack_hash} rdw={SPEC_VERSIONS['rdw_spec']}\n"
    )
    buf.write(f"# counts={counts}\n")
    # advisor stamps if any
    if st.advisor_outputs:
        models = sorted(
            {
                str(o.get("model_id") or o.get("model") or "")
                for o in st.advisor_outputs
                if o.get("model_id") or o.get("model")
            }
        )
        if models:
            buf.write(f"# advisor_models={models}\n")
    writer = csv.writer(buf)
    writer.writerow(
        ["Section", "Description", "Requirement", "Applicable", "Comments"]
    )
    for r in sorted(rows, key=lambda x: _unit_sort_key(x.unit_id)):
        rec = records.get(r.unit_id)
        section = rec.locator.section if rec else ""
        # FR6: FULL verbatim requirement text — no truncation, ever.
        desc = rec.shall_text if rec else ""
        applicable = _APPENDIX_APPLICABLE.get(r.export_label, r.export_label)
        writer.writerow(
            [
                section,
                desc,
                r.unit_id,
                applicable,
                r.comment or r.export_label,
            ]
        )
    path.write_text(buf.getvalue(), encoding="utf-8")
    LOGGER.info("Wrote Appendix-A matrix to %s (%d rows)", path, len(rows))
    return path


_APPENDIX_APPLICABLE = {
    "Meet": "Yes",
    "Meets Intent": "Yes (MI)",
    "Exception": "Yes (EX)",
    "N/A": "No",
    "TBD": "TBD",
    "Open/Not Met": "Yes (Open)",
}


def _unit_sort_key(unit_id: str) -> tuple[str, int]:
    """Standard document order: AMR-2 before AMR-10 (numeric, not lexicographic)."""
    m = re.match(r"([A-Za-z]+)-(\d+)", unit_id or "")
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return (unit_id or "", 0)


def _write_xlsx_book(
    path: Path,
    sheets: list[tuple[str, list[str], list[list[str]]]],
) -> Path:
    """Generic stdlib OOXML workbook writer: sheets = [(name, headers, rows)]."""
    import zipfile

    n = len(sheets)
    overrides = "\n".join(
        f'  <Override PartName="/xl/worksheets/sheet{i}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.'
        f'spreadsheetml.worksheet+xml"/>'
        for i in range(1, n + 1)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
        f"{overrides}\n</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>\n'
        "</Relationships>"
    )
    wb_rels_items = "\n".join(
        f'  <Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
        f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, n + 1)
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        f"{wb_rels_items}\n</Relationships>"
    )
    sheet_tags = "\n".join(
        f'    <sheet name="{name[:31]}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _, _) in enumerate(sheets, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"\n'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        f"  <sheets>\n{sheet_tags}\n  </sheets>\n</workbook>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        for i, (_, headers, rows_) in enumerate(sheets, start=1):
            zf.writestr(
                f"xl/worksheets/sheet{i}.xml", _xlsx_sheet_xml(headers, rows_)
            )
    return path


def export_appendix_a_xlsx(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    path: Path | str,
    *,
    enforce_decision: bool = True,
    include_draft: bool = False,
) -> Path:
    """FR6: the real Appendix-A worksheet — full verbatim text, standard order."""
    if session.state is None:
        raise ExportError("Session not open")
    draft_note = _release_note(
        session, include_draft=include_draft,
        unit_pred=lambda uid: uid.upper().startswith("AMR-"),
    )
    rows = build_matrix_rows(session, records, enforce_decision=enforce_decision)
    # AR12: AMR-only — same filter as the CSV form.
    rows = [r for r in rows if r.unit_id.upper().startswith("AMR-")]
    counts = count_by_export_label(rows)
    st = session.state
    data: list[list[str]] = []
    for r in sorted(rows, key=lambda x: _unit_sort_key(x.unit_id)):
        rec = records.get(r.unit_id)
        data.append(
            [
                rec.locator.section if rec else "",
                rec.shall_text if rec else "",  # FULL text — no truncation
                r.unit_id,
                _APPENDIX_APPLICABLE.get(r.export_label, r.export_label),
                r.comment or r.export_label,
            ]
        )
    meta = [
        ["banner", ADVISORY_BANNER],
        ["session_id", st.session_id],
        ["pack_hash", st.pack_hash],
        ["rdw_spec", SPEC_VERSIONS["rdw_spec"]],
        ["counts", str(counts)],
    ]
    if draft_note:
        meta.insert(1, ["release_state", draft_note])
    out = _write_xlsx_book(
        Path(path),
        [
            (
                "Appendix A",
                ["Section", "Description", "Requirement", "Applicable", "Comments"],
                data,
            ),
            ("Meta", ["field", "value"], meta),
        ],
    )
    LOGGER.info("Wrote Appendix-A XLSX to %s (%d rows)", out, len(data))
    return out


def export_readiness_roadmap(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    path: Path | str,
) -> Path:
    """
    Stage E internal product: gap-closure / readiness roadmap by work_package.

    Every non-Met row with ActionRecords; readiness counts; action ids.
    """
    if session.state is None:
        raise ExportError("Session not open")
    from oracle.disposition.readiness import map_readiness, readiness_counts

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    st = session.state
    results = []
    lines: list[str] = []
    lines.append(f"# {ADVISORY_BANNER}")
    lines.append(
        f"# Readiness roadmap | session_id={st.session_id} pack_hash={st.pack_hash}"
    )
    by_wp: dict[str, list[str]] = {}
    for uid, unit in sorted(st.units.items()):
        acts = session.actions_for_unit(uid)
        # migrate legacy strings
        from oracle.disposition.actions import migrate_string_action

        if not acts and unit.open_actions:
            acts = [
                migrate_string_action(t, unit_id=uid, index=i)
                for i, t in enumerate(unit.open_actions)
            ]
        has_ev = session.has_qualifying_meet_evidence(unit)
        rr = map_readiness(unit, acts, has_qualifying_evidence=has_ev)
        results.append(rr)
        if rr.label.value == "Met":
            continue
        wp = "unassigned"
        for a in acts:
            if a.work_package:
                wp = a.work_package
                break
        block = [
            f"## {uid} — {rr.label.value}",
            f"reasons: {'; '.join(rr.reasons)}",
        ]
        try:
            block.append(f"contract_label: {unit.export_label().value}")
        except Exception:
            block.append("contract_label: <unmapped>")
        for a in acts:
            block.append(
                f"  ACTION {a.action_id}: {a.title} | owner={a.owner} | "
                f"deliverable={a.deliverable} | exit={a.exit_criteria} | "
                f"due={a.due_or_trigger} | wp={a.work_package}"
            )
        by_wp.setdefault(wp, []).append("\n".join(block))

    counts = readiness_counts(results)
    lines.append(f"# readiness_counts={counts}")
    for wp, blocks in sorted(by_wp.items()):
        lines.append(f"\n# === work_package: {wp} ===")
        lines.extend(blocks)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote readiness roadmap to %s", path)
    return path


_GAP = "— (not yet established)"


def _guide_section(
    session: DispositionSession,
    uid: str,
    rec: Optional[RequirementRecord],
    unit: UnitAxesState,
    acts: list,
) -> list[str]:
    """FR6: one working-guide section — explicit gaps, never invented content."""
    from oracle.disposition.graph import DependencyGraph

    g = getattr(session, "_graph", None) or DependencyGraph.from_seeds()
    related = sorted(
        {e.dependent_id for e in g.edges if e.prerequisite_id == uid}
        | {e.prerequisite_id for e in g.prerequisites_of(uid) if not e.fact_key}
    )
    process = session.fact_for("hardware.process")
    ev = "; ".join(f"{r.doc_id}@{r.revision}" for r in unit.evidence_refs) or _GAP
    # AR13: "objective evidence" means REGISTERED refs only — a cited but
    # unregistered ref is a claim, not objective evidence.
    store = session.evidence_store()
    if store is None:
        reg_ev = "— (no evidence registry; cited refs above are unverified)"
    else:
        known = store.known_doc_revisions()
        reg_ev = "; ".join(
            f"{r.doc_id}@{r.revision}"
            for r in unit.evidence_refs
            if (r.doc_id, r.revision) in known
        ) or _GAP
    done_when = "; ".join(a.exit_criteria for a in acts if a.exit_criteria) or _GAP
    dest = "; ".join(a.deliverable for a in acts if a.deliverable) or _GAP
    gate = (
        "authority-dependent (CEO/NASA approval path)"
        if rec and rec.authority_dependent
        else f"approval_state={unit.approval_state}"
    )
    try:
        label = unit.export_label().value
    except Exception:
        label = "<unmapped>"
    return [
        f"## {uid} — {label}",
        f"**What it requires (verbatim):** {rec.shall_text if rec else _GAP}",
        f"**Why it exists (published rationale):** "
        f"{(rec.rationale.strip() if rec and rec.rationale else _GAP)}",
        # AR13: only an attested intent_statement is an interpretation; the
        # matrix comment has its own line and must not masquerade as one.
        f"**Process interpretation ({process.statement if process else 'process not recorded'}):** "
        f"{unit.intent_statement or _GAP}",
        f"**Matrix comment:** {unit.comment or _GAP}",
        f"**Current evidence (cited refs):** {ev}",
        f"**Controlled destination (deliverables):** {dest}",
        f"**Objective evidence (registered refs):** {reg_ev}",
        f"**Done-when (exit criteria):** {done_when}",
        f"**Related AMRs:** {', '.join(related) or _GAP}",
        f"**Gate / hold point:** {gate}",
        "",
    ]


def export_implementation_guide(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    path: Path | str,
) -> Path:
    """FR6 internal product: the detailed MRL implementation working guide.

    Per-AMR sections for every non-Met row. Fields come from the record and
    attested content only; empty fields render as explicit gaps.
    """
    if session.state is None:
        raise ExportError("Session not open")
    from oracle.disposition.actions import migrate_string_action
    from oracle.disposition.readiness import map_readiness

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    st = session.state
    lines = [
        f"# MRL Implementation Guide",
        f"{ADVISORY_BANNER}",
        f"session_id={st.session_id} pack_hash={st.pack_hash} "
        f"rdw={SPEC_VERSIONS['rdw_spec']}",
        "",
    ]
    n = 0
    for uid in sorted(st.units.keys(), key=_unit_sort_key):
        unit = st.units[uid]
        acts = session.actions_for_unit(uid)
        if not acts and unit.open_actions:
            acts = [
                migrate_string_action(t, unit_id=uid, index=i)
                for i, t in enumerate(unit.open_actions)
            ]
        rr = map_readiness(
            unit, acts,
            has_qualifying_evidence=session.has_qualifying_meet_evidence(unit),
        )
        if rr.label.value == "Met":
            continue
        lines.extend(
            _guide_section(session, uid, records.get(uid), unit, list(acts))
        )
        n += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote implementation guide to %s (%d sections)", path, n)
    return path


def export_dual_products(
    session: DispositionSession,
    records: dict[str, RequirementRecord],
    out_dir: Path | str,
    *,
    enforce_decision: bool = True,
    include_draft: bool = False,
) -> dict[str, Path]:
    """Stage E: supplier suite + Appendix-A (XLSX + CSV) + roadmap + guide.

    M4: the EXTERNAL products (supplier matrix, Appendix A) gate on
    review-accepted rows; internal products (roadmap, guide) are exempt.
    """
    out = Path(out_dir)
    paths = export_all(
        session, records, out, enforce_decision=enforce_decision,
        include_draft=include_draft,
    )
    paths["appendix_a"] = export_appendix_a_xlsx(
        session, records, out / "appendix_a_matrix.xlsx",
        enforce_decision=enforce_decision, include_draft=include_draft,
    )
    paths["appendix_a_csv"] = export_appendix_a(
        session, records, out / "appendix_a_matrix.csv",
        enforce_decision=enforce_decision, include_draft=include_draft,
    )
    paths["roadmap"] = export_readiness_roadmap(
        session, records, out / "readiness_roadmap.md"
    )
    paths["implementation_guide"] = export_implementation_guide(
        session, records, out / "implementation_guide.md"
    )
    return paths
