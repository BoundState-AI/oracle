#!/usr/bin/env python3
"""
Module: oracle.disposition.curate_6030
Purpose: Stage 0 — extract NASA-STD-6030 AMR shall texts from the pinned PDF.

Body-only extraction (§4–8); Appendix A is completeness cross-check only.
Writes a draft pack JSON for DraftPackWorkspace promote (FR-003).

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LOGGER = logging.getLogger("oracle.disposition.curate_6030")

SOURCE_PDF_NAME = "2021-04-21_nasa-std-6030-approveddocx.pdf"
SOURCE_HASH = (
    "sha256:5246d3b992ac0cc7a7deadb4c3c10284444add7d7e055968ae011d671d5a96cd"
)
EXPECTED_AMR_COUNT = 115

# Header/footer noise on every page
_PAGE_NOISE = re.compile(
    r"(?:NASA-STD-6030\s*)?"
    r"(?:APPROVED FOR PUBLIC RELEASE[^\n]*\n)?"
    r"(?:\d+\s+of\s+190\s*)?",
    re.I,
)
_AMR_MARKER = re.compile(r"\[AMR-(\d+[a-z]?)\]", re.I)
_RATIONALE = re.compile(
    r"\[Rationale:\s*(.*?)\]",
    re.I | re.DOTALL,
)
_SECTION_HDR = re.compile(
    r"^(?P<section>\d+(?:\.\d+)*)\s+(?P<title>[A-Z][^\n]{3,120})$",
    re.M,
)
_APPENDIX_A = re.compile(r"^\s*APPENDIX\s+A\b", re.I | re.M)


@dataclass
class ExtractedAmr:
    requirement_id: str
    shall_text: str
    section: str
    page: int
    rationale: str = ""
    notes: str = ""
    raw_block: str = ""


def verify_source_pdf(path: Path | str) -> str:
    """Return content hash; raise if size/hash mismatch vs pinned source."""
    p = Path(path)
    raw = p.read_bytes()
    digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    if digest != SOURCE_HASH:
        raise ValueError(
            f"Source PDF hash mismatch: expected {SOURCE_HASH}, got {digest}"
        )
    if len(raw) != 3_317_520:
        raise ValueError(f"Source PDF size unexpected: {len(raw)} bytes")
    return digest


def _clean_page_text(text: str) -> str:
    # Collapse soft line wraps inside paragraphs carefully later; strip footers first
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if s.upper() == "NASA-STD-6030":
            continue
        if "APPROVED FOR PUBLIC RELEASE" in s.upper():
            continue
        if re.fullmatch(r"\d+\s+of\s+190", s):
            continue
        if re.fullmatch(r"\d+\s+of\s+\d+", s):
            continue
        lines.append(s)
    return "\n".join(lines)


def _normalize_ws(text: str) -> str:
    """Join hyphenated line breaks and collapse whitespace for shall text."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    # join hyphenation across newlines: word-\nword → wordword
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
    # single newlines inside sentences → space
    t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _find_appendix_a_page(pages: list[str]) -> int:
    """Return 0-based page index of Appendix A start (or len if not found)."""
    for i, t in enumerate(pages):
        if i < 100:
            continue
        if _APPENDIX_A.search(t) or re.search(
            r"APPENDIX\s+A\s*[—\-–:]?\s*REQUIREMENTS?\s+COMPLIANCE",
            t,
            re.I,
        ):
            return i
    # Fallback: first page after 150 with dense [AMR-n] table-like content
    for i, t in enumerate(pages):
        if i < 150:
            continue
        if t.upper().count("[AMR-") > 10 and "COMPLIANCE" in t.upper():
            return i
    return len(pages)


def extract_pages(pdf_path: Path | str) -> list[tuple[int, str]]:
    """Return list of (1-based page number, cleaned text)."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    out: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages):
        raw = page.extract_text() or ""
        out.append((i + 1, _clean_page_text(raw)))
    return out


def extract_amrs_from_pdf(pdf_path: Path | str) -> list[ExtractedAmr]:
    """
    Extract all AMR shall texts from main body only.

    Verbatim reconstruction: page text cleaned of headers/footers only;
    shall text is the block from [AMR-n] through the next marker/section/
    rationale boundary, whitespace-normalized for single-line storage.
    """
    pages = extract_pages(pdf_path)
    page_texts = [t for _, t in pages]
    app_idx = _find_appendix_a_page(page_texts)
    LOGGER.info("Appendix A starts at page index %s (1-based %s)", app_idx, app_idx + 1)

    # Concatenate body with page break markers
    body_parts: list[str] = []
    page_of_offset: list[tuple[int, int]] = []  # (char_offset, page_no)
    cursor = 0
    for page_no, text in pages[:app_idx]:
        page_of_offset.append((cursor, page_no))
        chunk = text + "\n"
        body_parts.append(chunk)
        cursor += len(chunk)
    body = "".join(body_parts)

    def page_at(pos: int) -> int:
        page = pages[0][0] if pages else 1
        for off, pno in page_of_offset:
            if off <= pos:
                page = pno
            else:
                break
        return page

    # Track current section number from headers
    section_at: list[tuple[int, str]] = [(0, "4")]
    for m in _SECTION_HDR.finditer(body):
        section_at.append((m.start(), m.group("section")))

    def section_at_pos(pos: int) -> str:
        sec = "4"
        for off, s in section_at:
            if off <= pos:
                sec = s
            else:
                break
        return sec

    markers = list(_AMR_MARKER.finditer(body))
    extracted: list[ExtractedAmr] = []
    seen: set[str] = set()

    for i, m in enumerate(markers):
        raw_id = m.group(1)
        rid = f"AMR-{raw_id}"
        # Normalize letter suffixes: AMR-51e style
        if raw_id[-1:].isalpha():
            rid = f"AMR-{raw_id[:-1]}{raw_id[-1].lower()}"
        else:
            rid = f"AMR-{raw_id}"
        # Prefer first (body) occurrence
        if rid.upper() in {x.upper() for x in seen}:
            continue
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(body)
        block = body[start:end]

        # Split rationale / notes
        rationale = ""
        notes = ""
        rat = _RATIONALE.search(block)
        if rat:
            rationale = _normalize_ws(rat.group(1))
            before = block[: rat.start()]
            after = block[rat.end() :]
            # Guidance after rationale until next major header
            notes = _normalize_ws(after)
            shall_raw = before
        else:
            shall_raw = block

        # Truncate shall at common post-requirement prose markers if multi-para
        # Keep full shall sentence(s) including lettered sub-items that are part of shall
        shall_raw = shall_raw.strip()
        # Cut at standalone section headers inside block
        cut = re.search(
            r"\n(?=\d+\.\d+\s+[A-Z])",
            shall_raw,
        )
        if cut and cut.start() > 40:
            # material after may be guidance without [Rationale:]
            extra = shall_raw[cut.start() :].strip()
            if not notes:
                notes = _normalize_ws(extra)
            shall_raw = shall_raw[: cut.start()]

        shall = _normalize_ws(shall_raw)
        # Strip leading colon/space remnants
        shall = shall.lstrip(": ").strip()
        if not shall:
            LOGGER.warning("Empty shall for %s at page %s", rid, page_at(m.start()))
            continue

        # Detect incomplete extraction
        if shall.endswith("[") or shall.endswith("["):
            LOGGER.warning("Dangling bracket in %s", rid)

        seen.add(rid)
        extracted.append(
            ExtractedAmr(
                requirement_id=rid,
                shall_text=shall,
                section=section_at_pos(m.start()),
                page=page_at(m.start()),
                rationale=rationale,
                notes=notes[:2000] if notes else "",
                raw_block=block[:500],
            )
        )

    # Appendix A completeness cross-check
    app_text = "\n".join(page_texts[app_idx:])
    app_ids = {f"AMR-{x}" for x in _AMR_MARKER.findall(app_text)}
    # normalize
    app_ids_n = set()
    for a in app_ids:
        m = re.match(r"AMR-(\d+)([a-zA-Z]?)", a, re.I)
        if m:
            app_ids_n.add(
                f"AMR-{m.group(1)}{m.group(2).lower()}" if m.group(2) else f"AMR-{m.group(1)}"
            )
    body_ids = {e.requirement_id for e in extracted}
    missing_in_body = sorted(app_ids_n - body_ids)
    extra_in_body = sorted(body_ids - app_ids_n)
    if missing_in_body:
        LOGGER.warning("In Appendix A but not body extract: %s", missing_in_body[:20])
    if extra_in_body:
        LOGGER.info("In body but not Appendix A set: %s", extra_in_body[:20])

    return extracted


def build_pack_dict(
    extracted: list[ExtractedAmr],
    *,
    source_hash: str,
    source_path: str,
) -> dict[str, Any]:
    """Build pack JSON matching load_requirement_records schema + rationale/notes."""
    reqs = []
    for e in extracted:
        reqs.append(
            {
                "id": e.requirement_id.lower(),
                "source_tag": e.requirement_id,
                "section": e.section,
                "shall_text": e.shall_text,
                "subject": None,
                "requirement": e.shall_text,
                "context": e.notes or None,
                "page": e.page,
                "justification": e.rationale or None,
                "rationale": e.rationale or "",
                "notes": e.notes or "",
                "keywords": [],
                "applies_to": [],
                "mua_relevant": False,
                "source_coordinates": {"page": e.page, "section": e.section},
            }
        )
    return {
        "schema_version": "disposition-pack/v1",
        "rule_pack_id": "nasa_std_6030_curated",
        "standard_id": "NASA-STD-6030",
        "version": "Baseline",
        "revision": "Baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_document": SOURCE_PDF_NAME,
        "source_path": source_path,
        "source_hash": source_hash,
        "source_extract": "body-only §§4–8; Appendix A completeness cross-check",
        "total_requirements": len(reqs),
        "requirements": reqs,
    }


def curate_to_workspace(
    pdf_path: Path | str,
    workspace_root: Path | str,
    *,
    reviewer: str = "operator",
    promote: bool = False,
    dest: Optional[Path | str] = None,
) -> dict[str, Any]:
    """
    Full Stage-0 pipeline: verify PDF → extract → draft workspace → optional promote.
    """
    from oracle.disposition.packs import DraftPackWorkspace

    pdf_path = Path(pdf_path)
    source_hash = verify_source_pdf(pdf_path)
    extracted = extract_amrs_from_pdf(pdf_path)
    pack = build_pack_dict(
        extracted, source_hash=source_hash, source_path=str(pdf_path)
    )

    ws = DraftPackWorkspace(workspace_root)
    # Write draft via import of a temp JSON
    tmp = ws.root / "_extracted.json"
    tmp.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    ws.import_source_json(tmp, name="nasa_std_6030_curated")
    # Re-write draft with full pack (import already copied)
    ws.draft_path.write_text(
        json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # Update meta hash after rewrite
    from oracle.disposition.rulepack import content_hash_path

    meta = json.loads(ws.meta_path.read_text(encoding="utf-8"))
    meta["content_hash"] = content_hash_path(ws.draft_path)
    meta["source_hash"] = source_hash
    meta["amr_count"] = len(extracted)
    ws.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "amr_count": len(extracted),
        "source_hash": source_hash,
        "draft_path": str(ws.draft_path),
        "dangling": [
            e.requirement_id
            for e in extracted
            if e.shall_text.rstrip().endswith("[")
        ],
        "empty": [e.requirement_id for e in extracted if not e.shall_text.strip()],
        "amr2_preview": next(
            (e.shall_text[:200] for e in extracted if e.requirement_id == "AMR-2"),
            None,
        ),
    }

    if promote:
        ws.mark_reviewed(reviewer, notes="Stage 0 curated from pinned PDF")
        dest_p = Path(dest) if dest else (
            Path(__file__).resolve().parent / "data" / "nasa_std_6030_curated.json"
        )
        ws.promote_to(dest_p)
        result["promoted_to"] = str(dest_p)

    return result


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Curate NASA-STD-6030 AMR pack from PDF")
    ap.add_argument(
        "--pdf",
        default=str(
            Path(__file__).resolve().parents[2]
            / "docs"
            / SOURCE_PDF_NAME
        ),
    )
    ap.add_argument(
        "--workspace",
        default=str(Path(__file__).resolve().parents[2] / "oracle_sessions" / "curate_6030"),
    )
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--reviewer", default="dr.wilde")
    ap.add_argument(
        "--dest",
        default=str(
            Path(__file__).resolve().parent / "data" / "nasa_std_6030_curated.json"
        ),
    )
    args = ap.parse_args()
    result = curate_to_workspace(
        args.pdf,
        args.workspace,
        reviewer=args.reviewer,
        promote=args.promote,
        dest=args.dest,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
