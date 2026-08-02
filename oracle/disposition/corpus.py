#!/usr/bin/env python3
"""
Module: oracle.disposition.corpus
Purpose: FR8 — engagement-corpus loader + dual-view reconciliation harness.

The behavioral golden is the operator's real 115-AMR session (scrubbed per
D-3). This module defines the input format, loads it, and reconciles EXACT
counts on both derived views. The corpus file itself lives outside the repo
until scrubbed and cleared; tests skip-with-reason while it is absent.

Expected CSV columns (header row required, extra columns ignored):
  requirement_id, contract_label, readiness_label, applicability,
  organization_responsibility, implementation_state, approval_state,
  comment, work_package, action_ids, raw_answers, evidence_refs

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import csv
import logging
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

LOGGER = logging.getLogger("oracle.disposition.corpus")

CORPUS_ENV = "RDW_CORPUS_PATH"

# Identity-first (Fran ruling 2026-08-02): the corpus file locks the
# adjudicated ROW IDENTITIES; tallies are COMPUTED for reporting and are
# never enforcement targets. The earlier EXACT tally constants
# (85/6/7/17 etc.) were retired as stale — forcing totals was shown to
# push rows into false codes (the AMR-16/41 lesson).


class CorpusRow(BaseModel):
    """One expert-adjudicated requirement row from the engagement.

    v2 (CR2): carries everything the replay harness needs to drive a
    real session through the normal gated APIs — split axes, gate
    fields (citation / MI fields / EX closure / NYD), and evidence.
    All v2 fields default so legacy v1 files still load.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1)
    contract_label: str = Field(min_length=1)  # CW/MI/EX/NA (or full labels)
    readiness_label: str = Field(min_length=1)
    applicability: str = ""
    organization_responsibility: str = ""
    implementation_state: str = ""
    approval_state: str = ""
    comment: str = ""
    work_package: str = ""
    action_ids: tuple[str, ...] = ()
    raw_answers: str = ""
    evidence_refs: str = ""
    # ---- v2 replay fields
    obligated_actor: str = ""
    fulfillment_path: str = ""
    execution_state: str = ""
    scope_citation: str = ""
    intent_statement: str = ""
    alternative_control: str = ""
    control_class: str = ""
    exception_basis: str = ""
    permanent_relief_basis: str = ""
    closure_action_id: str = ""
    not_yet_due: str = ""  # truthy strings: yes/true/1
    not_yet_due_justification: str = ""
    evidence_date: str = ""


class CorpusError(Exception):
    """Corpus missing or malformed (fail closed, never guess)."""


def corpus_path() -> Optional[Path]:
    """Path from RDW_CORPUS_PATH when set and existing; else None."""
    raw = os.environ.get(CORPUS_ENV, "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_file() else None


# AR11: label + axis vocabularies — a corpus row with an unknown label is
# structurally meaningless and must fail at load, not at reconciliation.
_CONTRACT_NORMALIZE: dict[str, str] = {
    "cw": "CW",
    "comply as written": "CW",
    "comply-as-written": "CW",
    "mi": "MI",
    "meets intent": "MI",
    "ex": "EX",
    "exception": "EX",
    "na": "NA",
    "n/a": "NA",
    "not applicable": "NA",
}
_READINESS_CANON: dict[str, str] = {
    "met": "Met",
    "not met with plan": "Not Met with Plan",
    "tbd": "TBD",
    "program action": "Program Action",
    "technical n/a": "Technical N/A",
    "technical n-a": "Technical N/A",
    "not yet due": "Not Yet Due",
}
_AXIS_VOCAB: dict[str, frozenset[str]] = {
    "applicability": frozenset({"yes", "no", "tbd"}),
    "organization_responsibility": frozenset({"owner", "support", "external", "tbd"}),
    "implementation_state": frozenset(
        {"meets_as_written", "alternate_proposed", "partial", "not_met", "tbd", "not_reached"}
    ),
    "approval_state": frozenset(
        {"not_required", "required", "draft", "submitted", "approved", "rejected", "tbd"}
    ),
    # v2 (model split)
    "obligated_actor": frozenset(
        {"program", "ceo", "producer", "supplier", "subtier", "other"}
    ),
    "fulfillment_path": frozenset(
        {"as_written", "alternative_intent", "exception", "not_applicable", "tbd"}
    ),
    "execution_state": frozenset(
        {"not_started", "partial", "implemented", "evidenced", "verified", "tbd"}
    ),
    "control_class": frozenset({"integral", "disclosed"}),
}


def _validate_row(i: int, data: dict[str, str]) -> dict[str, str]:
    """Normalize labels to canonical vocabulary; refuse unknowns (AR11)."""
    cl = _CONTRACT_NORMALIZE.get(data.get("contract_label", "").strip().lower())
    if cl is None:
        raise CorpusError(
            f"Row {i}: unknown contract_label {data.get('contract_label')!r} "
            f"(expected one of CW/MI/EX/NA or their full forms)"
        )
    data["contract_label"] = cl
    rl = _READINESS_CANON.get(data.get("readiness_label", "").strip().lower())
    if rl is None:
        raise CorpusError(
            f"Row {i}: unknown readiness_label {data.get('readiness_label')!r} "
            f"(expected one of {sorted(set(_READINESS_CANON.values()))})"
        )
    data["readiness_label"] = rl
    for axis, vocab in _AXIS_VOCAB.items():
        val = (data.get(axis) or "").strip().lower()
        if val and val not in vocab:
            raise CorpusError(
                f"Row {i}: {axis}={data[axis]!r} not in {sorted(vocab)}"
            )
        if axis in data:
            data[axis] = val
    return data


def _pick_sheet_target(z, p: Path) -> str:
    """N6: choose the worksheet by NAME — a sheet named 'Corpus'
    (case-insensitive) wins; a single-sheet book is unambiguous; anything
    else refuses rather than silently reading the wrong table."""
    from xml.etree import ElementTree as ET

    ns_wb = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ns_r = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except KeyError as e:
        raise CorpusError(f"XLSX missing workbook part in {p}: {e}") from e
    rid_to_target = {
        rel.get("Id"): rel.get("Target") or ""
        for rel in rels
        if (rel.get("Type") or "").endswith("/worksheet")
    }
    sheets: list[tuple[str, str]] = []  # (name, zip path)
    for sh in wb.findall("m:sheets/m:sheet", ns_wb):
        target = rid_to_target.get(sh.get(f"{ns_r}id") or "")
        if not target:
            continue
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheets.append((sh.get("name") or "", target))
    if not sheets:
        raise CorpusError(f"No worksheet found in {p}")
    named = [t for n, t in sheets if n.strip().lower() == "corpus"]
    if named:
        return named[0]
    if len(sheets) == 1:
        return sheets[0][1]
    raise CorpusError(
        f"XLSX has multiple sheets {[n for n, _ in sheets]} and none named "
        f"'Corpus' — name the corpus sheet 'Corpus' so the right table is "
        f"unambiguous ({p})"
    )


def _read_xlsx_rows(p: Path) -> list[list[str]]:
    """AR11/FR8: minimal OOXML worksheet reader (stdlib only) — the inverse
    of export._write_xlsx_book. Shared/inline strings; named-sheet select."""
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(p) as z:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in root.findall("m:si", ns):
                    shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
            target = _pick_sheet_target(z, p)
            try:
                root = ET.fromstring(z.read(target))
            except KeyError as e:
                raise CorpusError(f"XLSX sheet part {target!r} missing in {p}") from e
    except zipfile.BadZipFile as e:
        raise CorpusError(f"Not a valid XLSX file: {p} ({e})") from e
    except ET.ParseError as e:
        # N10: malformed XML fails through the documented boundary
        raise CorpusError(f"Malformed XLSX XML in {p}: {e}") from e

    def _col_index(ref: str) -> int:
        letters = "".join(c for c in ref if c.isalpha())
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
        return idx - 1

    out: list[list[str]] = []
    for row in root.findall(".//m:sheetData/m:row", ns):
        cells: dict[int, str] = {}
        for j, c in enumerate(row.findall("m:c", ns)):
            ref = c.get("r") or ""
            ci = _col_index(ref) if ref else j
            ctype = c.get("t")
            if ctype == "inlineStr":
                is_el = c.find("m:is", ns)
                text = "".join(
                    t.text or "" for t in (is_el.iter() if is_el is not None else ())
                    if t.tag.endswith("}t")
                )
            else:
                v = c.find("m:v", ns)
                text = v.text or "" if v is not None else ""
                if ctype == "s":
                    try:
                        text = shared[int(text)]
                    except (ValueError, IndexError) as e:
                        raise CorpusError(
                            f"XLSX shared-string ref {text!r} invalid in {p}"
                        ) from e
            cells[ci] = text
        width = max(cells) + 1 if cells else 0
        out.append([cells.get(k, "") for k in range(width)])
    return out


def load_corpus(path: Path | str) -> list[CorpusRow]:
    """Load the scrubbed corpus (CSV or XLSX — FR8 promised both)."""
    p = Path(path)
    if not p.is_file():
        raise CorpusError(f"Corpus file not found: {p}")
    known = set(CorpusRow.model_fields.keys())

    if p.suffix.lower() == ".xlsx":
        grid = _read_xlsx_rows(p)
        if not grid:
            raise CorpusError(f"XLSX corpus is empty: {p}")
        header = [h.strip() for h in grid[0]]
        raw_rows: list[tuple[int, dict[str, str]]] = [
            (
                i,
                {
                    header[j]: (vals[j] if j < len(vals) else "").strip()
                    for j in range(len(header))
                    if header[j] in known
                },
            )
            for i, vals in enumerate(grid[1:], start=2)
            if any(v.strip() for v in vals)
        ]
    elif p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            raw_rows = [
                (
                    i,
                    {
                        k.strip(): (v or "").strip()
                        for k, v in raw.items()
                        if k and k.strip() in known
                    },
                )
                for i, raw in enumerate(reader, start=2)
            ]
    else:
        raise CorpusError(
            f"Corpus must be .csv or .xlsx (got {p.suffix!r})"
        )

    rows: list[CorpusRow] = []
    seen_ids: dict[str, int] = {}
    for i, data in raw_rows:
        rid = data.get("requirement_id", "")
        if not rid:
            raise CorpusError(f"Row {i}: requirement_id missing")
        if rid in seen_ids:
            raise CorpusError(
                f"Row {i}: duplicate requirement_id {rid!r} "
                f"(first seen at row {seen_ids[rid]})"
            )
        seen_ids[rid] = i
        data = _validate_row(i, data)
        aids = data.pop("action_ids", "")
        rows.append(
            CorpusRow(
                **data,
                action_ids=tuple(a.strip() for a in aids.split(";") if a.strip()),
            )
        )
    LOGGER.info("Loaded %d corpus rows from %s", len(rows), p)
    return rows


def reconcile(rows: list[CorpusRow]) -> dict[str, dict[str, int]]:
    """Counts for both derived views + work-package tally."""
    contract = Counter(r.contract_label for r in rows)
    readiness = Counter(r.readiness_label for r in rows)
    wps = {r.work_package for r in rows if r.work_package}
    return {
        "contract": dict(contract),
        "readiness": dict(readiness),
        "work_packages": {"count": len(wps)},
    }


_AXIS_FIELDS = (
    "applicability",
    "organization_responsibility",
    "implementation_state",
    "approval_state",
)


def _assert_row_coherent(r: CorpusRow) -> None:
    """AR11 (completion): label counts alone are not evidence — every row
    must carry axes, and its labels must cohere with them. Catches a corpus
    that matches the tallies while being structurally meaningless.
    v2: split axes (fulfillment+execution) satisfy the implementation
    requirement; execution-based invariants apply when present."""
    has_split = bool(r.fulfillment_path and r.execution_state)
    for f in _AXIS_FIELDS:
        if f == "implementation_state" and has_split:
            continue
        if not getattr(r, f):
            raise CorpusError(
                f"{r.requirement_id}: axis {f} is blank — the corpus is a "
                "behavioral golden; every row needs its axes"
            )
    # NOTE: no CW/EX -> applicability rule — Fran's real targets have 21
    # Technical N/A vs 17 contract NA, i.e. some technically-N/A rows still
    # answer CW in the contract view. Only invariants the readiness/§7.1
    # derivations force are enforced here.
    if r.contract_label == "NA" and r.applicability != "no":
        raise CorpusError(
            f"{r.requirement_id}: contract NA but applicability={r.applicability!r}"
        )
    mi_ok = (
        r.fulfillment_path == "alternative_intent"
        if has_split
        else r.implementation_state == "alternate_proposed"
    )
    if r.contract_label == "MI" and not mi_ok:
        raise CorpusError(
            f"{r.requirement_id}: contract MI but the fulfillment/"
            f"implementation axis does not elect an alternative"
        )
    if r.readiness_label == "Met":
        met_ok = (
            r.execution_state in ("evidenced", "verified")
            if has_split
            else r.implementation_state == "meets_as_written"
        )
        if not met_ok:
            raise CorpusError(
                f"{r.requirement_id}: readiness Met but execution/"
                f"implementation does not support it"
            )
    if r.readiness_label == "Not Yet Due":
        nyd_ok = (
            r.execution_state in ("tbd", "not_started")
            if has_split
            else r.implementation_state == "tbd"
        )
        if not nyd_ok:
            raise CorpusError(
                f"{r.requirement_id}: readiness Not Yet Due but execution "
                "has concrete progress"
            )
    if r.readiness_label == "Technical N/A" and r.applicability != "no":
        raise CorpusError(
            f"{r.requirement_id}: readiness Technical N/A but "
            f"applicability={r.applicability!r}"
        )
    if r.readiness_label == "Not Met with Plan" and not r.action_ids:
        raise CorpusError(
            f"{r.requirement_id}: readiness Not Met with Plan requires at "
            "least one action_id (the plan)"
        )


def assert_reconciled(rows: list[CorpusRow]) -> None:
    """Identity-first (Fran 2026-08-02): the corpus IS the identity lock.

    Enforces per-row coherence + unique identities. Tallies are computed
    by reconcile() for reporting and are never gates; row count is
    whatever the adjudication produced; the replay golden compares
    engine-derived labels against each row's locked codes."""
    seen: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r.requirement_id in seen:
            raise CorpusError(
                f"duplicate requirement_id {r.requirement_id!r} "
                f"(rows {seen[r.requirement_id]} and {i})"
            )
        seen[r.requirement_id] = i
        _assert_row_coherent(r)


def scan_work_packages(wps: list[Any]) -> list[str]:
    """D-3 floor for the sibling file (Atlas CR Medium 4): every string
    field of every work package is scanned against the identifier
    blocklist. Returns hits; callers refuse on any."""
    from oracle.disposition.library import DEFAULT_BLOCKLIST_PATTERNS

    hits: list[str] = []
    for wp in wps:
        for field, value in wp.model_dump().items():
            text = " ".join(value) if isinstance(value, (list, tuple)) else str(value)
            for pat in DEFAULT_BLOCKLIST_PATTERNS:
                m = re.search(pat, text or "", re.I)
                if m:
                    hits.append(
                        f"{wp.wp_id}.{field}: {m.group(0)[:40]!r} matches {pat!r}"
                    )
    return hits


def load_work_packages(corpus_path: Path | str) -> list[Any]:
    """CR2: sibling `<stem>.workpackages.csv` -> WorkPackageRecord list.

    Header = WorkPackageRecord field names (a few engagement synonyms
    accepted). Missing sibling file -> empty list, never an error."""
    from oracle.disposition.workpackage import WorkPackageRecord

    p = Path(corpus_path)
    sib = p.with_name(p.stem + ".workpackages.csv")
    if not sib.is_file():
        return []
    synonyms = {
        "actionid": "wp_id",
        "id": "wp_id",
        "affectedamrs": "affected_unit_ids",
        "affectedunits": "affected_unit_ids",
        "objectiveevidence": "objective_evidence",
        "exitcriteria": "exit_criteria",
        "executionactions": "execution_actions",
    }
    known = set(WorkPackageRecord.model_fields.keys())
    out: list[Any] = []
    with sib.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader, start=2):
            data: dict[str, Any] = {}
            for k, v in raw.items():
                if not k:
                    continue
                nk = re.sub(r"[^a-z0-9]", "", k.lower())
                field = synonyms.get(nk) or next(
                    (f for f in known if f.replace("_", "") == nk), None
                )
                if field:
                    data[field] = (v or "").strip()
            if not data.get("wp_id"):
                raise CorpusError(f"{sib.name} row {i}: wp_id missing")
            if any(w.wp_id == data["wp_id"] for w in out):
                raise CorpusError(
                    f"{sib.name} row {i}: duplicate wp_id {data['wp_id']!r}"
                )
            aff = data.get("affected_unit_ids", "")
            if isinstance(aff, str):
                data["affected_unit_ids"] = tuple(
                    a.strip() for a in re.split(r"[;,]", aff) if a.strip()
                )
            status = (data.get("status") or "open").lower()
            data["status"] = status if status in (
                "open", "blocked", "closed", "superseded"
            ) else "open"
            out.append(WorkPackageRecord.model_validate(data))
    return out
