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
from collections import Counter
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

LOGGER = logging.getLogger("oracle.disposition.corpus")

CORPUS_ENV = "RDW_CORPUS_PATH"

# Fran's engagement reconciliation targets (2026-07-30) — EXACT.
EXPECTED_CONTRACT: dict[str, int] = {
    "CW": 85,
    "MI": 6,
    "EX": 7,
    "NA": 17,
}
EXPECTED_READINESS: dict[str, int] = {
    "Met": 2,
    "Not Met with Plan": 39,
    "TBD": 34,
    "Program Action": 18,
    "Technical N/A": 21,
    "Not Yet Due": 1,
}
EXPECTED_WORK_PACKAGES = 16


class CorpusRow(BaseModel):
    """One expert-adjudicated requirement row from the engagement."""

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
    that matches the tallies while being structurally meaningless."""
    for f in _AXIS_FIELDS:
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
    if r.contract_label == "MI" and r.implementation_state != "alternate_proposed":
        raise CorpusError(
            f"{r.requirement_id}: contract MI but "
            f"implementation_state={r.implementation_state!r}"
        )
    if r.readiness_label == "Met" and r.implementation_state != "meets_as_written":
        raise CorpusError(
            f"{r.requirement_id}: readiness Met but "
            f"implementation_state={r.implementation_state!r}"
        )
    if r.readiness_label == "Not Yet Due" and r.implementation_state != "tbd":
        raise CorpusError(
            f"{r.requirement_id}: readiness Not Yet Due but "
            f"implementation_state={r.implementation_state!r}"
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
    """FR8: EXACT reconciliation against the engagement targets."""
    got = reconcile(rows)
    if len(rows) != 115:
        raise CorpusError(f"Corpus has {len(rows)} rows; expected 115")
    for r in rows:
        _assert_row_coherent(r)
    if got["contract"] != EXPECTED_CONTRACT:
        raise CorpusError(
            f"Contract counts differ: got {got['contract']} "
            f"expected {EXPECTED_CONTRACT}"
        )
    if got["readiness"] != EXPECTED_READINESS:
        raise CorpusError(
            f"Readiness counts differ: got {got['readiness']} "
            f"expected {EXPECTED_READINESS}"
        )
    if got["work_packages"]["count"] != EXPECTED_WORK_PACKAGES:
        raise CorpusError(
            f"Work packages: got {got['work_packages']['count']} "
            f"expected {EXPECTED_WORK_PACKAGES}"
        )
