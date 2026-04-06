#!/usr/bin/env python3
"""
Shall Statement Extractor - Local-Only Processing

Extracts obligation statements from PDF text:
  Pass 1: PyMuPDF text extraction + regex + MPR/FCR tag-aware parsing
  Pass 1b: Header/footer dedup, enrichment (justification, keywords, applies_to)
  Pass 2: Local Ollama LLM classification (optional)

Output is always written to JSON + summary text.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import socket
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


# ============================================================================
# Models
# ============================================================================

OBLIGATION_KEYWORDS = {
    "shall": "mandatory",
    "shall not": "prohibition",
    "must": "mandatory",
    "must not": "prohibition",
    "is required to": "mandatory",
    "is required": "mandatory",
    "required": "mandatory",
    "is prohibited": "prohibition",
    "prohibited": "prohibition",
    "will": "intent",
    "should": "recommendation",
    "should not": "recommendation",
    "may": "permission",
    "may not": "prohibition",
}

OBLIGATION_PATTERN = re.compile(
    r"(?:^|(?<=\.\s)|(?<=\n))"
    r"([^.;\n]*?"
    r"\b(shall not|shall|must not|must|is required to|is required|required|"
    r"is prohibited|prohibited|should not|should|may not|may|will)\b"
    r"[^.;\n]*)"
    r"[.;]?",
    re.IGNORECASE | re.MULTILINE,
)

# Improved section pattern: tolerant of PDF line-break artifacts
SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*"
    r"(\d+(?:\.\d+)*[a-z]?(?:\(\d+\))*)"
    r"[\s.:\-]+"
    r"([A-Z][^\n]{0,120})",
    re.MULTILINE,
)

# MPR/FCR tag extraction
MPR_TAG_PATTERN = re.compile(r"\[(MPR|FCR)\s*(\d+[a-z]?)\]", re.IGNORECASE)

# Justification/rationale markers
RATIONALE_PATTERN = re.compile(
    r"(?:Rationale|Note|Justification|Basis)\s*[:\-]\s*(.+?)(?=\n\s*\n|\n\s*\[(?:MPR|FCR)|\n\s*\d+(?:\.\d+)+\s+[A-Z]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Domain vocabulary for keyword extraction
DOMAIN_KEYWORDS = {
    "material", "materials", "process", "processes", "test", "testing",
    "oxygen", "hydrogen", "flammability", "compatibility", "corrosion",
    "fracture", "stress", "pressure", "temperature", "fluid", "gas",
    "metallic", "nonmetallic", "non-metallic", "polymer", "composite",
    "adhesive", "welding", "bonding", "coating", "plating", "inspection",
    "NDE", "qualification", "certification", "MUA", "MAPTIS",
    "specification", "vendor", "supplier", "contamination", "cleaning",
    "handling", "storage", "assembly", "propellant", "cryogenic",
    "fatigue", "embrittlement", "toxicity", "outgassing", "vacuum",
    "mechanical", "thermal", "chemical", "structural", "design",
    "flight", "hardware", "safety", "hazard", "environment",
    "elevated", "ambient", "fracture-critical", "limited-life",
    "fastener", "seal", "lubricant", "elastomer", "fluoropolymer",
    "weld", "braze", "solder", "heat-treat", "annealing",
}

# Applicability classification patterns
APPLICABILITY_PATTERNS = {
    "human_rated": re.compile(
        r"human.?rated|crew|life.?critical|habitable|crewed", re.IGNORECASE
    ),
    "mission_critical": re.compile(
        r"mission.?critical|flight.?critical|safety.?critical", re.IGNORECASE
    ),
    "oxygen_service": re.compile(r"\boxygen\b|O2\b|LOX|GOX", re.IGNORECASE),
    "hydrogen_service": re.compile(r"\bhydrogen\b|H2\b|LH2|GH2", re.IGNORECASE),
    "propellant": re.compile(
        r"propellant|hypergol|NTO|MMH|hydrazine", re.IGNORECASE
    ),
    "pressure_systems": re.compile(
        r"pressur|psi[ag]?\b|MPa\b|vessel", re.IGNORECASE
    ),
    "structural": re.compile(
        r"structur|load\b|stress\b|fracture|fatigue", re.IGNORECASE
    ),
    "thermal": re.compile(
        r"\bthermal\b|temperatur|cryogenic|elevated.?temp", re.IGNORECASE
    ),
    "contamination_control": re.compile(
        r"contaminat|clean|particulate|NVR|outgas", re.IGNORECASE
    ),
    "metallic": re.compile(
        r"\bmetallic\b|alloy|steel|aluminum|titanium|nickel|copper|inconel",
        re.IGNORECASE,
    ),
    "nonmetallic": re.compile(
        r"nonmetallic|non-metallic|polymer|elastomer|adhesive|seal\b|lubricant|composite",
        re.IGNORECASE,
    ),
}


@dataclass
class ShallStatement:
    id: int
    page: int
    section: str
    obligation_keyword: str
    obligation_type: str
    statement_text: str
    subject: str
    requirement: str
    context: str
    mpr_id: str = ""
    justification: str = ""
    keywords: list[str] = field(default_factory=list)
    applies_to: list[str] = field(default_factory=list)
    category: str = ""
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    source_file: str
    total_pages: int
    extraction_date: str
    total_statements: int
    by_type: dict = field(default_factory=dict)
    mpr_count: int = 0
    dedup_removed: int = 0
    statements: list[ShallStatement] = field(default_factory=list)


# ============================================================================
# Fix 4: Text preprocessing — join PDF-broken lines
# ============================================================================


def _preprocess_page_text(raw_text: str) -> str:
    """Rejoin lines broken by PDF column/page layout.

    Preserves line breaks before section headers (e.g. '4.1.2 Title')
    and before [MPR X]/[FCR X] tags.  Everything else gets joined so
    that sentence-boundary regex can work on complete paragraphs.
    """
    lines = raw_text.split("\n")
    joined: list[str] = []
    buf = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # Blank line = paragraph break
            if buf:
                joined.append(buf)
                buf = ""
            joined.append("")
            continue

        # New paragraph if line starts with section number or [MPR/FCR tag
        starts_new = bool(
            re.match(r"\s*\d+(?:\.\d+)+[a-z]?\s+[A-Z]", line)
            or re.match(r"\s*\[(?:MPR|FCR)\s*\d+", line, re.IGNORECASE)
        )

        if starts_new:
            if buf:
                joined.append(buf)
            buf = stripped
        elif buf:
            buf += " " + stripped
        else:
            buf = stripped

    if buf:
        joined.append(buf)

    return "\n".join(joined)


# ============================================================================
# Fix 2 + 3: MPR-aware extraction with full text capture
# ============================================================================

_MPR_NEXT_SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*"
    r"(\d+(?:\.\d+)*[a-z]?(?:\(\d+\))*)"
    r"[\s.:\-]+"
    r"([A-Z][^\n]{0,120})",
    re.MULTILINE,
)


def _find_mpr_block_end(text: str, start: int) -> int:
    """Find the end of a tagged MPR/FCR block.

    Tagged requirements in NASA standards often continue across blank lines
    and sub-items like ``a.``, ``b.``, ``(1)``, etc.  We therefore do not
    terminate on paragraph breaks alone.  A block ends only at the next tag
    or the next real section header.
    """
    candidates: list[int] = []

    next_tag = MPR_TAG_PATTERN.search(text, start)
    if next_tag:
        candidates.append(next_tag.start())

    next_section = _MPR_NEXT_SECTION_PATTERN.search(text, start)
    if next_section:
        candidates.append(next_section.start())

    return min(candidates) if candidates else len(text)


def _extract_mpr_blocks(text: str, page: int) -> list[dict]:
    """Extract full requirement text between consecutive [MPR/FCR] tags."""
    results = []
    for match in MPR_TAG_PATTERN.finditer(text):
        tag_type = match.group(1).upper()
        tag_num = match.group(2)
        mpr_id = f"{tag_type} {tag_num}"

        # Capture from end of tag to next boundary
        start = match.end()
        end = _find_mpr_block_end(text, start)

        block = re.sub(r"\s+", " ", text[start:end]).strip().rstrip(".")

        if len(block) < 10:
            continue

        results.append(
            {
                "mpr_id": mpr_id,
                "text": block,
                "tag_start": match.start(),
                "page": page,
            }
        )

    return results


# ============================================================================
# Enrichments
# ============================================================================


def _extract_keywords(text: str) -> list[str]:
    """Pull 3-7 domain-relevant terms from the requirement text."""
    words = set(re.findall(r"[A-Za-z][\w-]*", text))
    hits = []
    for w in words:
        low = w.lower()
        if low in DOMAIN_KEYWORDS or w in DOMAIN_KEYWORDS:
            hits.append(low)
    # Also grab any acronyms (2+ uppercase letters)
    for acro in re.findall(r"\b[A-Z]{2,6}\b", text):
        if acro not in ("THE", "AND", "FOR", "NOT", "ARE", "ALL", "PER"):
            hits.append(acro)
    return sorted(set(hits))[:7]


def _classify_applicability(text: str, context: str = "") -> list[str]:
    """Classify requirement applicability from text + context."""
    combined = text + " " + context
    tags = []
    for tag, pattern in APPLICABILITY_PATTERNS.items():
        if pattern.search(combined):
            tags.append(tag)
    return sorted(tags)


def _extract_justification(full_page_text: str, tag_end_pos: int) -> str:
    """Look for Rationale/Note text following the requirement."""
    # Search in a window after the requirement
    search_start = tag_end_pos
    search_end = min(len(full_page_text), tag_end_pos + 500)
    window = full_page_text[search_start:search_end]

    m = RATIONALE_PATTERN.search(window)
    if m:
        rationale = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(rationale) > 10:
            return rationale[:300]
    return ""


# ============================================================================
# Pass 1 extraction (improved)
# ============================================================================

NOISE_TERMS = (
    "page ",
    "table of contents",
    "revision history",
    "export controlled",
    "proprietary",
)


def _detect_current_section(text: str, char_pos: int) -> str:
    best_section = ""
    for match in SECTION_PATTERN.finditer(text):
        if match.start() <= char_pos:
            best_section = match.group(1).strip()
        else:
            break
    return best_section


def _extract_subject_requirement(statement: str, keyword: str) -> tuple[str, str]:
    match = re.search(r"\b" + re.escape(keyword) + r"\b", statement, re.IGNORECASE)
    if not match:
        return "", statement
    subject = statement[: match.start()].strip().rstrip(",").strip()
    requirement = statement[match.end() :].strip().lstrip(",").strip()
    if len(subject) < 2:
        subject = "(implicit)"
    return subject, requirement


def extract_pass1(pdf_path: Path) -> ExtractionResult:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    statements: list[ShallStatement] = []
    stmt_id = 0
    seen_mpr_ids: set[str] = set()

    logger.info("Pass 1: extracting from %s (%d pages)", pdf_path.name, total_pages)

    # ------------------------------------------------------------------
    # Phase A: MPR/FCR tag-aware extraction (full block text)
    # ------------------------------------------------------------------
    for page_idx in range(len(doc)):
        raw_text = doc[page_idx].get_text()
        if not raw_text or len(raw_text.strip()) < 20:
            continue

        text = _preprocess_page_text(raw_text)

        for block in _extract_mpr_blocks(text, page_idx + 1):
            mpr_id = block["mpr_id"]
            if mpr_id in seen_mpr_ids:
                continue

            full_text = block["text"]

            # Skip change-log / front-matter noise: require obligation keyword
            # in the block text and minimum meaningful length
            has_obligation = bool(
                re.search(
                    r"\bshall\b|\bmust\b|\brequired\b|\bprohibited\b",
                    full_text,
                    re.IGNORECASE,
                )
            )
            if not has_obligation or len(full_text) < 30:
                continue

            seen_mpr_ids.add(mpr_id)

            section = _detect_current_section(text, block["tag_start"])

            # Determine obligation keyword from the block text
            kw_match = re.search(
                r"\b(shall not|shall|must not|must|is required to|is required|"
                r"required|is prohibited|prohibited)\b",
                full_text,
                re.IGNORECASE,
            )
            keyword = kw_match.group(0).lower() if kw_match else "shall"
            obligation_type = OBLIGATION_KEYWORDS.get(keyword, "mandatory")
            subject, requirement = _extract_subject_requirement(full_text, keyword)

            justification = _extract_justification(
                text, block["tag_start"] + len(full_text)
            )
            keywords = _extract_keywords(full_text)
            applies_to = _classify_applicability(full_text, justification)

            stmt_id += 1
            statements.append(
                ShallStatement(
                    id=stmt_id,
                    page=block["page"],
                    section=section,
                    obligation_keyword=keyword,
                    obligation_type=obligation_type,
                    statement_text=full_text,
                    subject=subject,
                    requirement=requirement,
                    context="",
                    mpr_id=mpr_id,
                    justification=justification,
                    keywords=keywords,
                    applies_to=applies_to,
                )
            )

    logger.info("Phase A: %d MPR/FCR tagged requirements", len(statements))

    # ------------------------------------------------------------------
    # Phase B: Generic obligation extraction (non-tagged shall/must/etc.)
    # ------------------------------------------------------------------
    generic_statements: list[ShallStatement] = []
    raw_texts: list[str] = []

    for page_idx in range(len(doc)):
        raw_text = doc[page_idx].get_text()
        if not raw_text or len(raw_text.strip()) < 20:
            raw_texts.append("")
            continue

        text = _preprocess_page_text(raw_text)
        raw_texts.append(text)

        for match in OBLIGATION_PATTERN.finditer(text):
            sentence = match.group(1).strip()
            keyword = match.group(2).lower()
            if len(sentence) < 15:
                continue
            if any(noise in sentence.lower() for noise in NOISE_TERMS):
                continue

            # Skip if this text is already covered by an MPR block
            if MPR_TAG_PATTERN.search(sentence):
                continue

            obligation_type = OBLIGATION_KEYWORDS.get(keyword, "mandatory")
            section = _detect_current_section(text, match.start())
            subject, requirement = _extract_subject_requirement(sentence, keyword)
            ctx_start = max(0, match.start() - 120)
            ctx_end = min(len(text), match.end() + 120)
            context = text[ctx_start:ctx_end].strip()

            keywords = _extract_keywords(sentence)
            applies_to = _classify_applicability(sentence, context)

            stmt_id += 1
            generic_statements.append(
                ShallStatement(
                    id=stmt_id,
                    page=page_idx + 1,
                    section=section,
                    obligation_keyword=keyword,
                    obligation_type=obligation_type,
                    statement_text=sentence,
                    subject=subject,
                    requirement=requirement,
                    context=context,
                    keywords=keywords,
                    applies_to=applies_to,
                )
            )

    doc.close()

    # ------------------------------------------------------------------
    # Fix 1: Header/footer dedup — remove any text appearing 5+ times
    # ------------------------------------------------------------------
    text_counts = Counter(s.statement_text for s in generic_statements)
    boilerplate = {txt for txt, cnt in text_counts.items() if cnt >= 5}
    before_dedup = len(generic_statements)
    generic_statements = [s for s in generic_statements if s.statement_text not in boilerplate]
    dedup_removed = before_dedup - len(generic_statements)

    if boilerplate:
        logger.info(
            "Fix 1: removed %d boilerplate duplicates (%d unique patterns)",
            dedup_removed,
            len(boilerplate),
        )

    statements.extend(generic_statements)

    # Renumber IDs sequentially
    for i, s in enumerate(statements, 1):
        s.id = i

    by_type: dict[str, int] = {}
    for s in statements:
        by_type[s.obligation_type] = by_type.get(s.obligation_type, 0) + 1

    mpr_count = sum(1 for s in statements if s.mpr_id)

    result = ExtractionResult(
        source_file=pdf_path.name,
        total_pages=total_pages,
        extraction_date=datetime.now().isoformat(),
        total_statements=len(statements),
        by_type=by_type,
        mpr_count=mpr_count,
        dedup_removed=dedup_removed,
        statements=statements,
    )

    logger.info(
        "Pass 1 complete: %d statements (%d MPR/FCR, %d generic, %d deduped)",
        result.total_statements,
        mpr_count,
        len(generic_statements),
        dedup_removed,
    )
    return result


# ============================================================================
# Pass 1.5: Sonnet Vision Enrichment
# ============================================================================

SONNET_MODEL = "claude-sonnet-4-5-20250929"

ENRICHMENT_PROMPT = """You are analyzing a page from a NASA technical standard document.

The following requirement tags were found on this page: {mpr_list}

For EACH tagged requirement on this page, extract these fields by reading the actual document:

1. "mpr_id": The tag exactly as written (e.g., "MPR 15", "FCR 3")
2. "section": The section number this requirement falls under (e.g., "4.1.2", "4.2.1.3.a"). Read the section heading above the requirement.
3. "shall_text": The COMPLETE requirement text from the [MPR/FCR X] tag through the end of the requirement. Include all sentences — do not truncate.
4. "justification": Any rationale, note, or guidance text that follows the requirement. This is often italicized, indented, or preceded by "Rationale:", "Note:", "Guidance:", or appears as explanatory text below the requirement. If none, use empty string.
5. "keywords": 3-7 domain-specific technical terms from the requirement (e.g., "flammability", "hydrogen", "fracture-critical", "NDE", "outgassing")
6. "applies_to": Classification tags that describe what this requirement applies to. Choose from: human_rated, mission_critical, oxygen_service, hydrogen_service, propellant, pressure_systems, structural, thermal, contamination_control, metallic, nonmetallic, electrical, welding_joining, testing, documentation, vendor_control, additive_manufacturing

Return ONLY valid JSON in this format:
{{"requirements": [{{"mpr_id": "MPR 15", "section": "4.1.2", "shall_text": "...", "justification": "...", "keywords": [...], "applies_to": [...]}}]}}
"""


def _get_anthropic_client(api_key: str | None = None):
    """Get Anthropic client, preferring direct API."""
    import os

    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError("anthropic package required for --enrich-sonnet. Run: pip install anthropic")

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError(
            "No API key found. Set ANTHROPIC_API_KEY or pass --api-key"
        )
    return Anthropic(api_key=key)


def _render_page_to_base64(doc, page_idx: int, dpi: int = 150) -> str:
    """Render a PDF page to PNG base64."""
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    return base64.standard_b64encode(png_bytes).decode()


def enrich_with_sonnet(
    result: ExtractionResult,
    pdf_path: Path,
    *,
    api_key: str | None = None,
    dpi: int = 150,
    max_pages: int = 0,
) -> ExtractionResult:
    """Enrich MPR/FCR statements with Sonnet Vision for better section,
    justification, keywords, and applies_to extraction."""
    mpr_stmts = [s for s in result.statements if s.mpr_id]
    if not mpr_stmts:
        logger.info("Sonnet enrichment skipped: no MPR/FCR statements")
        return result

    # Group by page
    by_page: dict[int, list[ShallStatement]] = {}
    for s in mpr_stmts:
        by_page.setdefault(s.page, []).append(s)

    pages = sorted(by_page.keys())
    if max_pages and max_pages > 0:
        pages = pages[:max_pages]

    total_pages = len(pages)
    logger.info(
        "Sonnet enrichment: %d MPR/FCR across %d pages",
        sum(len(by_page[p]) for p in pages),
        total_pages,
    )

    client = _get_anthropic_client(api_key)
    doc = fitz.open(pdf_path)
    enriched_count = 0
    failed_count = 0
    started = time.time()

    for i, page_num in enumerate(pages, 1):
        page_stmts = by_page[page_num]
        mpr_ids = [s.mpr_id for s in page_stmts]
        mpr_list_str = ", ".join(f"[{m}]" for m in mpr_ids)

        page_idx = page_num - 1  # 0-indexed
        if page_idx >= len(doc):
            continue

        try:
            # Render page to PNG
            img_b64 = _render_page_to_base64(doc, page_idx, dpi)

            prompt = ENRICHMENT_PROMPT.format(mpr_list=mpr_list_str)

            response = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )

            response_text = response.content[0].text.strip()

            # Parse JSON (handle markdown code blocks)
            if "```" in response_text:
                start_idx = response_text.find("```")
                first_nl = response_text.find("\n", start_idx)
                end_idx = response_text.rfind("```")
                if first_nl != -1 and end_idx > first_nl:
                    response_text = response_text[first_nl + 1 : end_idx].strip()

            parsed = json.loads(response_text)
            reqs = parsed.get("requirements", [])

            # Merge enrichments back into statements
            enrichments_by_id = {r["mpr_id"]: r for r in reqs if "mpr_id" in r}

            for stmt in page_stmts:
                enrich = enrichments_by_id.get(stmt.mpr_id)
                if not enrich:
                    continue

                # Only overwrite if Sonnet provides better data
                if enrich.get("section") and len(enrich["section"]) >= len(stmt.section):
                    stmt.section = enrich["section"]
                if enrich.get("shall_text") and len(enrich["shall_text"]) > len(stmt.statement_text):
                    stmt.statement_text = enrich["shall_text"]
                    # Re-derive subject/requirement from enriched text
                    subject, requirement = _extract_subject_requirement(
                        stmt.statement_text, stmt.obligation_keyword
                    )
                    stmt.subject = subject
                    stmt.requirement = requirement
                if enrich.get("justification"):
                    stmt.justification = enrich["justification"][:500]
                if enrich.get("keywords"):
                    stmt.keywords = enrich["keywords"][:7]
                if enrich.get("applies_to"):
                    stmt.applies_to = enrich["applies_to"]

                enriched_count += 1

            elapsed = time.time() - started
            avg = elapsed / i
            eta = max(0, (total_pages - i) * avg)
            logger.info(
                "  Page %d/%d (p.%d): %d/%d enriched (%.1fs, ETA ~%.0fs)",
                i,
                total_pages,
                page_num,
                len(enrichments_by_id),
                len(page_stmts),
                time.time() - (started + (i - 1) * avg),
                eta,
            )

        except json.JSONDecodeError as e:
            failed_count += len(page_stmts)
            logger.warning("  Page %d: JSON parse failed: %s", page_num, e)
        except Exception as e:
            failed_count += len(page_stmts)
            logger.error("  Page %d: %s", page_num, e)

    doc.close()

    logger.info(
        "Sonnet enrichment complete: %d/%d enriched, %d failed (%.1fs total)",
        enriched_count,
        len(mpr_stmts),
        failed_count,
        time.time() - started,
    )
    return result


# ============================================================================
# Pass 2 classification
# ============================================================================

CLASSIFY_PROMPT_SYSTEM = (
    'You classify "shall" statements into categories. '
    "Return strict JSON only."
)
CLASSIFY_PROMPT_USER = """Classify these statements.
Return JSON object with key "results", array of objects:
{{"id":<int>,"cat":"<design|testing|inspection|documentation|handling|cleaning|materials|safety|process|approval|prohibition|general>","subj":"<who>","req":"<what they must do>","conf":<0.0-1.0>}}

{statements_json}
"""


def _call_ollama(
    prompt: str,
    model: str,
    *,
    system: str = "",
    timeout: int = 300,
    num_predict: int = 512,
    retries: int = 1,
) -> str:
    import urllib.error
    import urllib.request

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": num_predict,
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                content = data.get("message", {}).get("content", "")
                if not str(content).strip():
                    raise ValueError("Empty content from Ollama")
                return str(content)
        except (TimeoutError, socket.timeout) as e:
            if attempt < retries:
                logger.warning(
                    "Ollama timeout (attempt %d/%d), retrying...",
                    attempt + 1,
                    retries + 1,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            raise TimeoutError(
                f"Ollama timed out after {timeout}s (model={model})"
            ) from e
        except urllib.error.URLError as e:
            msg = str(e).lower()
            if "timed out" in msg:
                if attempt < retries:
                    logger.warning(
                        "Ollama timeout/URLError (attempt %d/%d), retrying...",
                        attempt + 1,
                        retries + 1,
                    )
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise TimeoutError(
                    f"Ollama timed out after {timeout}s (model={model})"
                ) from e
            raise ConnectionError(
                "Ollama not reachable at localhost:11434. Start with: ollama serve"
            ) from e


def _parse_llm_classifications(response_text: str) -> list[dict]:
    text = (response_text or "").strip()
    if not text:
        return []

    if "```" in text:
        first = text.find("```")
        first_nl = text.find("\n", first)
        last = text.rfind("```")
        if first_nl != -1 and last > first_nl:
            text = text[first_nl + 1 : last].strip()

    parsed: object
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
        for opener, closer in [("{", "}"), ("[", "]")]:
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    break
                except json.JSONDecodeError:
                    continue
        if parsed is None:
            logger.warning("Could not parse LLM JSON payload (prefix=%r)", text[:120])
            return []

    if isinstance(parsed, dict):
        for key in ("results", "items", "classifications", "data"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]

    if not isinstance(parsed, list):
        return []

    out: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id"),
                "category": item.get("cat") or item.get("category", ""),
                "subject_refined": item.get("subj")
                or item.get("subject_refined", ""),
                "requirement_refined": item.get("req")
                or item.get("requirement_refined", ""),
                "confidence": item.get("conf")
                if item.get("conf") is not None
                else item.get("confidence", 1.0),
            }
        )
    return out


def extract_pass2(
    result: ExtractionResult,
    *,
    model: str = "llama3.1:8b-instruct-q4_K_M",
    batch_size: int = 5,
    timeout: int = 300,
    num_predict: int = 512,
    retries: int = 1,
    max_consecutive_failures: int = 3,
    max_statements: int = 0,
) -> ExtractionResult:
    statements = result.statements
    if max_statements and max_statements > 0:
        statements = statements[:max_statements]

    total = len(statements)
    if total == 0:
        logger.info("Pass 2 skipped: no statements")
        return result

    total_batches = (total + batch_size - 1) // batch_size
    logger.info(
        "Pass 2: classifying %d statements with %s (%d batches x %d)",
        total,
        model,
        total_batches,
        batch_size,
    )

    classified_count = 0
    failed_count = 0
    consecutive_failures = 0
    started = time.time()

    for batch_start in range(0, total, batch_size):
        batch = statements[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        batch_started = time.time()

        batch_json = json.dumps(
            [
                {"id": s.id, "statement": s.statement_text[:200], "section": s.section}
                for s in batch
            ],
            ensure_ascii=False,
        )
        prompt = CLASSIFY_PROMPT_USER.format(statements_json=batch_json)

        try:
            response = _call_ollama(
                prompt,
                model,
                system=CLASSIFY_PROMPT_SYSTEM,
                timeout=timeout,
                num_predict=num_predict,
                retries=retries,
            )
            classes = _parse_llm_classifications(response)
            by_id = {c.get("id"): c for c in classes if c.get("id") is not None}

            for stmt in batch:
                c = by_id.get(stmt.id)
                if c:
                    stmt.category = str(c.get("category", "") or "")
                    stmt.confidence = float(c.get("confidence", 1.0) or 1.0)
                    if c.get("subject_refined"):
                        stmt.subject = str(c["subject_refined"])
                    if c.get("requirement_refined"):
                        stmt.requirement = str(c["requirement_refined"])
                    classified_count += 1
                else:
                    failed_count += 1

            consecutive_failures = 0
            elapsed = time.time() - batch_started
            avg = (time.time() - started) / batch_num
            rem = max(0, total_batches - batch_num)
            eta_min = int((avg * rem) / 60)
            logger.info(
                "  Batch %d/%d: %d/%d OK (%d/%d total, %d%%, %.1fs, ETA ~%dm)",
                batch_num,
                total_batches,
                len(classes),
                len(batch),
                classified_count,
                total,
                int((classified_count * 100) / total),
                elapsed,
                eta_min,
            )

        except ConnectionError:
            logger.error("Ollama not available - aborting pass 2")
            break
        except TimeoutError as e:
            failed_count += len(batch)
            consecutive_failures += 1
            logger.error(
                "  Batch %d/%d timeout: %s (%d/%d total)",
                batch_num,
                total_batches,
                e,
                classified_count,
                total,
            )
            if consecutive_failures >= max_consecutive_failures:
                logger.error(
                    "Stopping pass 2 after %d consecutive failures.",
                    consecutive_failures,
                )
                break
        except Exception as e:
            failed_count += len(batch)
            consecutive_failures += 1
            logger.error(
                "  Batch %d/%d failed: %s (%d/%d total)",
                batch_num,
                total_batches,
                e,
                classified_count,
                total,
            )
            if consecutive_failures >= max_consecutive_failures:
                logger.error(
                    "Stopping pass 2 after %d consecutive failures.",
                    consecutive_failures,
                )
                break

    logger.info(
        "Pass 2 complete: %d/%d classified, %d failed",
        classified_count,
        total,
        failed_count,
    )
    return result


# ============================================================================
# Output
# ============================================================================


def save_results(result: ExtractionResult, output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(result.source_file).stem

    json_path = output_dir / f"{stem}_shall_statements.json"
    summary_path = output_dir / f"{stem}_shall_summary.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, indent=2, ensure_ascii=False)

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("SHALL STATEMENT EXTRACTION REPORT\n")
        f.write("=" * 60 + "\n")
        f.write(f"Source: {result.source_file}\n")
        f.write(f"Pages: {result.total_pages}\n")
        f.write(f"Date: {result.extraction_date}\n")
        f.write(f"Total Statements: {result.total_statements}\n")
        f.write(f"MPR/FCR Tagged: {result.mpr_count}\n")
        f.write(f"Boilerplate Removed: {result.dedup_removed}\n\n")

        f.write("BREAKDOWN BY TYPE:\n")
        for typ, count in sorted(result.by_type.items(), key=lambda x: -x[1]):
            f.write(f"  {typ:20s}: {count}\n")
        f.write("\n" + "=" * 60 + "\n\n")

        # MPR/FCR tagged requirements first
        mpr_stmts = [s for s in result.statements if s.mpr_id]
        if mpr_stmts:
            f.write("TAGGED REQUIREMENTS (MPR/FCR)\n")
            f.write("=" * 60 + "\n")
            for s in mpr_stmts:
                f.write(f"\n  [{s.mpr_id}] Section {s.section or '?'}, p.{s.page}\n")
                f.write(f"    {s.statement_text[:300]}\n")
                if s.subject and s.subject != "(implicit)":
                    f.write(f"    Subject: {s.subject}\n")
                f.write(f"    Requirement: {s.requirement[:250]}\n")
                if s.justification:
                    f.write(f"    Justification: {s.justification[:200]}\n")
                if s.keywords:
                    f.write(f"    Keywords: {', '.join(s.keywords)}\n")
                if s.applies_to:
                    f.write(f"    Applies to: {', '.join(s.applies_to)}\n")
            f.write("\n" + "=" * 60 + "\n\n")

        # Then by section
        by_section: dict[str, list[ShallStatement]] = {}
        generic = [s for s in result.statements if not s.mpr_id]
        for s in generic:
            by_section.setdefault(s.section or "(no section)", []).append(s)

        f.write("GENERIC REQUIREMENTS BY SECTION\n")
        f.write("=" * 60 + "\n")
        for section, stmts in sorted(by_section.items(), key=lambda kv: kv[0]):
            f.write(f"\nSECTION {section}\n")
            f.write("-" * 40 + "\n")
            for s in stmts:
                cat = f" [{s.category}]" if s.category else ""
                f.write(f"  [{s.obligation_type.upper()}]{cat} p.{s.page}\n")
                f.write(f"    {s.statement_text[:300]}\n")
                if s.subject and s.subject != "(implicit)":
                    f.write(f"    Subject: {s.subject}\n")
                f.write(f"    Requirement: {s.requirement[:250]}\n")
                if s.keywords:
                    f.write(f"    Keywords: {', '.join(s.keywords)}\n")
                if s.applies_to:
                    f.write(f"    Applies to: {', '.join(s.applies_to)}\n")
                f.write("\n")

    logger.info("Saved: %s", json_path)
    logger.info("Saved: %s", summary_path)
    return {"json": json_path, "summary": summary_path}


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Extract shall/must/required statements from a PDF"
    )
    parser.add_argument("pdf", type=str, help="Path to PDF file")
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output directory (default: same as PDF)",
    )
    parser.add_argument(
        "--classify",
        action="store_true",
        help="Run pass 2 with local Ollama model",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        help="Ollama model name",
    )
    parser.add_argument(
        "--mandatory-only",
        action="store_true",
        help="Only keep mandatory/prohibition statements",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Statements per LLM batch (default: 5)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout per LLM call in seconds (default: 300)",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=512,
        help="Max generated tokens per LLM call (default: 512)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retries per failed LLM call (default: 1)",
    )
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=3,
        help="Abort pass 2 after this many consecutive failures (default: 3)",
    )
    parser.add_argument(
        "--max-statements",
        type=int,
        default=0,
        help="Cap number of statements sent to pass 2 (0 = no cap)",
    )
    parser.add_argument(
        "--enrich-sonnet",
        action="store_true",
        help="Run Sonnet Vision enrichment on MPR/FCR requirements",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Cap pages sent to Sonnet enrichment (0 = all, useful for testing)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="DPI for page rendering in Sonnet enrichment (default: 150)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    output_dir = Path(args.output) if args.output else pdf_path.parent

    result = extract_pass1(pdf_path)

    if args.mandatory_only:
        before = len(result.statements)
        result.statements = [
            s
            for s in result.statements
            if s.obligation_type in ("mandatory", "prohibition")
        ]
        result.total_statements = len(result.statements)
        result.by_type = {}
        for s in result.statements:
            result.by_type[s.obligation_type] = result.by_type.get(s.obligation_type, 0) + 1
        logger.info("Filtered to mandatory/prohibition: %d -> %d", before, result.total_statements)

    # Always checkpoint pass 1 immediately so caller gets JSON even if enrichment is slow.
    checkpoint = save_results(result, output_dir)
    logger.info("Pass 1 checkpoint written: %s", checkpoint["json"])

    # Sonnet Vision enrichment (Pass 1.5)
    if args.enrich_sonnet:
        result = enrich_with_sonnet(
            result,
            pdf_path,
            api_key=args.api_key,
            dpi=args.dpi,
            max_pages=args.max_pages,
        )
        # Checkpoint after enrichment
        save_results(result, output_dir)
        logger.info("Sonnet enrichment checkpoint written")

    if args.classify:
        result = extract_pass2(
            result,
            model=args.model,
            batch_size=args.batch_size,
            timeout=args.timeout,
            num_predict=args.num_predict,
            retries=args.retries,
            max_consecutive_failures=args.max_consecutive_failures,
            max_statements=args.max_statements,
        )

    paths = save_results(result, output_dir)

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Source:      {result.source_file}")
    print(f"Pages:       {result.total_pages}")
    print(f"Statements:  {result.total_statements}")
    print(f"MPR/FCR:     {result.mpr_count}")
    print(f"Dedup removed: {result.dedup_removed}")
    print()
    for typ, count in sorted(result.by_type.items(), key=lambda x: -x[1]):
        print(f"  {typ:20s}: {count}")
    print()
    print(f"JSON:    {paths['json']}")
    print(f"Summary: {paths['summary']}")


if __name__ == "__main__":
    main()
