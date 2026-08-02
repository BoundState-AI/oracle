#!/usr/bin/env python3
"""
Module: oracle.disposition.corpus_scrub
Purpose: FR8 follow-on — turn a RAW engagement export into the scrubbed
corpus RDW_CORPUS_PATH expects, with D-3 enforced by tooling.

Reads raw CSV/XLSX, maps real-world headers to the corpus schema, applies
operator-supplied term replacements, scans EVERY output cell against the
D-3 blocklist + the terms, and writes only on a clean scan with apply=True
(fail closed). Engagement identifiers live in the operator's terms file
OUTSIDE the repo — never in this code, never in the output.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

from oracle.disposition.corpus import (
    CorpusError,
    CorpusRow,
    _assert_row_coherent,
    _read_xlsx_rows,
    load_corpus,
    reconcile,
)
from oracle.disposition.library import DEFAULT_BLOCKLIST_PATTERNS

LOGGER = logging.getLogger("oracle.disposition.corpus_scrub")

# Canonical output column order = the corpus schema, stable.
CANONICAL_FIELDS: tuple[str, ...] = tuple(CorpusRow.model_fields.keys())

# Real-world header synonyms (normalized) -> corpus field. Explicit --map
# overrides always win; unknown raw columns are dropped WITH a report line.
_SYNONYMS: dict[str, str] = {
    "reqid": "requirement_id",
    "req": "requirement_id",
    "requirement": "requirement_id",
    "amr": "requirement_id",
    "id": "requirement_id",
    "disposition": "contract_label",
    "contract": "contract_label",
    "response": "contract_label",
    "contractdisposition": "contract_label",
    "readiness": "readiness_label",
    "status": "readiness_label",
    "readinessstatus": "readiness_label",
    "applicable": "applicability",
    "org": "organization_responsibility",
    "orgresponsibility": "organization_responsibility",
    "responsibility": "organization_responsibility",
    "implementation": "implementation_state",
    "impl": "implementation_state",
    "approval": "approval_state",
    "comments": "comment",
    "notes": "comment",
    "wp": "work_package",
    "workpackage": "work_package",
    "actions": "action_ids",
    "actionids": "action_ids",
    "answers": "raw_answers",
    "rawanswers": "raw_answers",
    "evidence": "evidence_refs",
    "evidencerefs": "evidence_refs",
}


class ScrubViolation(BaseModel):
    """One D-3 hit in the would-be output (reported, never written)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    row: int  # 1-based data row (header = row 1)
    column: str
    kind: str  # "pattern" | "term"
    detail: str  # the regex or the term that matched
    excerpt: str  # matched text, console-only


class ScrubReport(BaseModel):
    """Result of a scrub run (written=False means fail-closed refusal)."""

    model_config = ConfigDict(extra="forbid")

    rows: int
    mapped: dict[str, str]  # raw header -> corpus field
    dropped_columns: list[str]
    replacements: int
    violations: list[ScrubViolation]
    format_errors: list[str] = []  # G5: loader-level refusals, pre-write
    warnings: list[str] = []
    written: bool
    out_path: Optional[str] = None


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def read_raw(path: Path | str) -> tuple[list[str], list[list[str]]]:
    """Read raw CSV/XLSX to (headers, data rows). Blank rows dropped."""
    p = Path(path)
    if not p.is_file():
        raise CorpusError(f"Raw export not found: {p}")
    if p.suffix.lower() == ".xlsx":
        grid = _read_xlsx_rows(p)
    elif p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            grid = [list(r) for r in csv.reader(f)]
    else:
        raise CorpusError(f"Raw export must be .csv or .xlsx (got {p.suffix!r})")
    if not grid:
        raise CorpusError(f"Raw export is empty: {p}")
    headers = [h.strip() for h in grid[0]]
    rows = [r for r in grid[1:] if any((c or "").strip() for c in r)]
    return headers, rows


def map_headers(
    headers: list[str], overrides: Optional[dict[str, str]] = None
) -> tuple[dict[int, str], list[str]]:
    """Map raw columns to corpus fields. Returns (index->field, dropped).

    Overrides (raw header -> field) win; then exact normalized field names;
    then the synonym table. First raw column wins a contested field.
    """
    overrides_n = {(_norm_header(k)): v for k, v in (overrides or {}).items()}
    for field in overrides_n.values():
        if field not in CANONICAL_FIELDS:
            raise CorpusError(f"--map target {field!r} is not a corpus field")
    canon = {_norm_header(f): f for f in CANONICAL_FIELDS}
    mapping: dict[int, str] = {}
    taken: set[str] = set()
    dropped: list[str] = []
    # G4: pass 1 — explicit overrides claim their fields FIRST, so a
    # synonym column earlier in the sheet can never steal an explicitly
    # mapped field. Unknown override headers are an error, not a no-op.
    matched: set[str] = set()
    for i, h in enumerate(headers):
        n = _norm_header(h)
        if n in overrides_n:
            field = overrides_n[n]
            if field in taken:
                raise CorpusError(
                    f"--map assigns {field!r} to more than one column"
                )
            mapping[i] = field
            taken.add(field)
            matched.add(n)
    missing = sorted(set(overrides_n) - matched)
    if missing:
        raise CorpusError(
            f"--map headers not found in the raw export: {missing} "
            f"(headers: {headers})"
        )
    # pass 2 — exact names, then synonyms, for the remaining columns
    for i, h in enumerate(headers):
        if i in mapping:
            continue
        n = _norm_header(h)
        field = canon.get(n) or _SYNONYMS.get(n)
        if field and field not in taken:
            mapping[i] = field
            taken.add(field)
        else:
            dropped.append(h or f"<col {i + 1}>")
    if "requirement_id" not in taken:
        raise CorpusError(
            f"No column maps to requirement_id (headers: {headers}); "
            "use --map \"YourHeader=requirement_id\""
        )
    return mapping, dropped


def parse_terms(path: Path | str) -> list[tuple[str, str]]:
    """Operator terms file: one per line, `term` or `term=Replacement`.

    Lines starting with # and blanks are skipped. The file lives OUTSIDE
    the repo; this function never writes it anywhere.
    """
    p = Path(path)
    if not p.is_file():
        raise CorpusError(f"Terms file not found: {p}")
    terms: list[tuple[str, str]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        term, _, repl = line.partition("=")
        term = term.strip()
        if not term:
            continue
        terms.append((term, repl.strip() or "[REDACTED]"))
    if not terms:
        raise CorpusError(f"Terms file has no usable entries: {p}")
    # Longest first so "Acme Corp" wins over "Acme"
    return sorted(terms, key=lambda t: -len(t[0]))


def _apply_terms(cell: str, terms: list[tuple[str, str]]) -> tuple[str, int]:
    n = 0
    for term, repl in terms:
        # G7: replacement is LITERAL text — a lambda bypasses re's escape
        # handling, so `C:\Safe` or `\1` in a replacement never errors.
        cell, k = re.subn(
            re.escape(term), lambda _m: repl, cell, flags=re.I
        )
        n += k
    return cell, n


def _scan_cell(
    row: int, column: str, cell: str, terms: list[tuple[str, str]]
) -> list[ScrubViolation]:
    out: list[ScrubViolation] = []
    for pat in DEFAULT_BLOCKLIST_PATTERNS:
        m = re.search(pat, cell or "", re.I)
        if m:
            out.append(
                ScrubViolation(
                    row=row, column=column, kind="pattern",
                    detail=pat, excerpt=m.group(0)[:60],
                )
            )
    for term, _ in terms:
        m = re.search(re.escape(term), cell or "", re.I)
        if m:
            out.append(
                ScrubViolation(
                    row=row, column=column, kind="term",
                    detail=term, excerpt=m.group(0)[:60],
                )
            )
    return out


def scrub(
    raw_path: Path | str,
    out_path: Path | str,
    *,
    terms_path: Path | str | None = None,
    mapping_overrides: Optional[dict[str, str]] = None,
    apply: bool = False,
    allow_no_terms: bool = False,
) -> ScrubReport:
    """CS1-CS4: map, replace terms, scan everything, write only when clean.

    Without apply=True this is a dry run: full report, nothing written.
    With apply=True the output is written ONLY when the D-3 scan has zero
    hits AND the rows pass loader-level validation (G5) — and only with a
    terms file, because pattern scanning cannot catch bare organization or
    person names (G1; allow_no_terms=True is an explicit attestation that
    the corpus contains none).
    """
    out_p = Path(out_path)
    # G2: never let the output destroy its own inputs.
    out_res = out_p.resolve()
    if out_res == Path(raw_path).resolve():
        raise CorpusError("Refusing to write output over the raw export")
    if terms_path is not None and out_res == Path(terms_path).resolve():
        raise CorpusError("Refusing to write output over the terms file")

    headers, raw_rows = read_raw(raw_path)
    mapping, dropped = map_headers(headers, mapping_overrides)
    terms = parse_terms(terms_path) if terms_path else []
    warnings: list[str] = []
    if not terms:
        if apply and not allow_no_terms:
            raise CorpusError(
                "A terms file is required to write output (D-3): pattern "
                "scanning cannot catch bare organization/person names. "
                "Pass terms_path, or allow_no_terms=True (--no-terms) to "
                "attest the corpus contains no engagement names."
            )
        warnings.append(
            "no terms file — organization/person names are NOT scanned; "
            "only generic identifier patterns apply"
        )

    replaced = 0
    out_rows: list[dict[str, str]] = []
    for r_i, raw in enumerate(raw_rows, start=2):
        row: dict[str, str] = {}
        for c_i, field in mapping.items():
            cell = (raw[c_i] if c_i < len(raw) else "").strip()
            cell, k = _apply_terms(cell, terms)
            replaced += k
            row[field] = cell
        out_rows.append(row)

    # G5: the output must be a corpus the loader ACCEPTS — validate and
    # normalize (label vocabulary, axis vocabulary, unique ids) pre-write.
    from oracle.disposition.corpus import _validate_row

    format_errors: list[str] = []
    seen_ids: dict[str, int] = {}
    normalized: list[dict[str, str]] = []
    for r_i, row in enumerate(out_rows, start=2):
        data = dict(row)
        rid = data.get("requirement_id", "")
        if not rid:
            format_errors.append(f"Row {r_i}: requirement_id missing")
        elif rid in seen_ids:
            format_errors.append(
                f"Row {r_i}: duplicate requirement_id {rid!r} "
                f"(first at row {seen_ids[rid]})"
            )
        else:
            seen_ids[rid] = r_i
        try:
            data = _validate_row(r_i, data)
        except CorpusError as e:
            format_errors.append(str(e))
        normalized.append(data)

    # G8 (Atlas round 2): the authoritative D-3 scan runs on the FINAL
    # normalized cells — the exact content that would be written — because
    # normalization itself can introduce a blocked term (e.g. a full label
    # normalizing to a code the operator prohibited). Nothing is scanned
    # earlier and trusted later.
    violations: list[ScrubViolation] = []
    for r_i, data in enumerate(normalized, start=2):
        for field in CANONICAL_FIELDS:
            violations.extend(
                _scan_cell(r_i, field, data.get(field, ""), terms)
            )

    written = False
    if apply and not violations and not format_errors:
        # G3: atomic — temp file in the destination directory, then
        # os.replace; a failed write never leaves partial output.
        import os
        import tempfile

        out_p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix="corpus-", suffix=".csv", dir=str(out_p.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(CANONICAL_FIELDS)
                for row in normalized:
                    w.writerow([row.get(f, "") for f in CANONICAL_FIELDS])
            os.replace(tmp_name, out_p)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        written = True
        LOGGER.info("Scrubbed corpus written to %s (%d rows)", out_p, len(out_rows))
    elif violations:
        LOGGER.warning(
            "Scrub refused: %d unresolved D-3 hits (fail closed)", len(violations)
        )
    elif format_errors:
        LOGGER.warning(
            "Scrub refused: %d loader-level format errors", len(format_errors)
        )

    return ScrubReport(
        rows=len(out_rows),
        mapped={headers[i]: f for i, f in mapping.items()},
        dropped_columns=dropped,
        replacements=replaced,
        violations=violations,
        format_errors=format_errors,
        warnings=warnings,
        written=written,
        out_path=str(out_p) if written else None,
    )


def check(path: Path | str) -> dict:
    """CS5, identity-first: computed tallies + ALL coherence errors.

    Tallies are REPORTS (Fran 2026-08-02) — 'reconciled' means the rows
    are internally coherent, never that they hit a target count."""
    from oracle.disposition.corpus import load_work_packages, scan_work_packages

    rows = load_corpus(path)
    got = reconcile(rows)
    errors: list[str] = []
    for r in rows:
        try:
            _assert_row_coherent(r)
        except CorpusError as e:
            errors.append(str(e))
    wps = load_work_packages(path)
    # D-3 floor covers the sibling too (Atlas CR Medium 4)
    errors.extend(f"work package {h}" for h in scan_work_packages(wps))
    return {
        "rows": len(rows),
        "contract": got["contract"],
        "readiness": got["readiness"],
        "work_packages": got["work_packages"]["count"],
        "work_package_records": len(wps),
        "coherence_errors": errors,
        "reconciled": not errors,
    }
