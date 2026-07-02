#!/usr/bin/env python3
"""
Module: oracle.shall_extractor
Purpose: Extracts binding obligation statements from regulatory/standards PDFs.

Extracts obligation statements from PDF text:
  Pass 1: PyMuPDF text extraction + regex + tagged requirement parsing
  Pass 1b: Header/footer dedup, enrichment (justification, keywords, applies_to)
  Pass 2: Local Ollama LLM classification (optional)

Output is always written to JSON + summary text.

__safety_critical__: bool = True — extracts binding obligations that drive compliance review

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import argparse
import base64
import difflib
import json
import logging
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

LOGGER = logging.getLogger("oracle.shall_extractor")


# ============================================================================
# Models
# ============================================================================

# ---------------------------------------------------------------------------
# Obligation keyword -> type mapping.
#
# WHY these specific keywords and types:
#   These are the canonical obligation verbs defined by NASA/DoD standards
#   writing conventions (see NASA-STD-0005, MIL-STD-961E, IEEE 830):
#
#   "shall" / "must" / "is required" / "are required" = MANDATORY — legally binding, must
#     be verified.  These are the words that create enforceable requirements.
#   "shall not" / "must not" / "is prohibited" / "are prohibited" / "may not" = PROHIBITION —
#     explicitly forbidden actions.  Critical for safety: "shall not use
#     Teflon in LOX service above 350 psi."
#   "will" = INTENT — declaration of future action by the authoring body,
#     not an obligation on the implementer.  Often confused with "shall"
#     in informal writing; distinguishing them prevents over-scoping.
#   "should" / "should not" = RECOMMENDATION — best practice, not binding.
#     Important to capture because auditors sometimes treat "should" as
#     mandatory; tagging it correctly prevents scope creep.
#   "may" = PERMISSION — explicitly grants latitude.  Without this tag,
#     engineers may assume a permissive clause is mandatory.
#
# The multi-word forms ("shall not", "are required to") are listed before
# their single-word substrings so regex alternation matches the longest
# form first (OBLIGATION_PATTERN uses these in longest-first order).
#
# Known edge cases:
#   - "required" alone (without "is") catches adjectival usage like
#     "required documentation" — acceptable, as these still indicate
#     mandatory artifacts.
#   - "will" is ambiguous (intent vs. future tense narrative); Pass 2
#     LLM classification can reclassify if needed.
# ---------------------------------------------------------------------------
OBLIGATION_KEYWORDS = {
    "shall": "mandatory",
    "shall not": "prohibition",
    "must": "mandatory",
    "must not": "prohibition",
    "are required to": "mandatory",
    "are required": "mandatory",
    "is required to": "mandatory",
    "is required": "mandatory",
    "be required to": "mandatory",
    "be required": "mandatory",
    "required": "mandatory",
    "are prohibited": "prohibition",
    "is prohibited": "prohibition",
    "be prohibited": "prohibition",
    "prohibited": "prohibition",
    "will": "intent",
    "should": "recommendation",
    "should not": "recommendation",
    "may": "permission",
    "may not": "prohibition",
}

# ---------------------------------------------------------------------------
# Sentence-boundary building blocks for OBLIGATION_PATTERN.
#
# WHY a period is not always a sentence end (fix: obligation truncation):
#   Regulatory text is dense with sentence-internal periods — decimal section
#   references ("the procedures in 19.202-1"), numeric values ("0.5 percent"),
#   and abbreviations ("e.g.", "Fig. 3", "Vol. 2").  The previous pattern
#   terminated the captured sentence at ANY period or semicolon, so
#   "...shall follow the procedures in 19.202-1..." captured only "...in 19"
#   and semicolon-joined compound duties silently lost every clause after the
#   first.  A missed or truncated obligation weakens every downstream
#   compliance review, so the boundary rules are deliberately conservative:
#
#   A period TERMINATES the sentence only when followed by whitespace and a
#   plausible sentence opener (capital letter, digit-led section header,
#   bracket, or quote) or by end-of-line/end-of-text — i.e. real sentence-end
#   evidence.  Periods followed by digits/letters with no space ("19.202-1",
#   "U.S.") or preceded by a known abbreviation stem are sentence-internal.
#
#   Semicolons are ALWAYS sentence-internal: regulatory compound duties are
#   semicolon-joined lists ("shall submit reports; maintain records; and
#   notify the CO") and must be captured as one complete obligation.
#
#   The (?-i:...) groups keep the capital-letter / abbreviation checks
#   case-SENSITIVE even though the overall pattern is IGNORECASE — otherwise
#   "[A-Z]" would match lowercase and every abbreviation would break a
#   sentence.
# ---------------------------------------------------------------------------
_ABBREVIATION_STEMS = (
    "e.g", "i.e", "cf", "vs", "viz", "No", "Fig", "Sec", "Rev", "Vol", "U.S",
    # WHY these additions (fix: truncated obligations): statutory and
    # editorial citations are dense in FAR-style text — "Pub. L. 95-507",
    # "Stat. 657", "Ch. 137", "para. (b)", "Dept. of Defense", "Amdt. 4" —
    # and each missed stem cut the captured obligation off mid-citation.
    # "para"/"Para" both appear because cross-references are cited in either
    # case ("see para. (b)" vs "Para. 3.2 applies").
    "Pub", "Stat", "Ch", "para", "Para", "Dept", "Amdt",
)
# WHY \b before each stem: without it "Branch."/"Thermostat." style word
# tails could collide with short stems; the boundary pins the stem to a
# whole token.  Each stem gets its OWN fixed-width lookbehind (Python re
# forbids variable-width lookbehind, so they are joined as alternatives).
_ABBREV_LOOKBEHINDS = "|".join(
    [f"(?<=(?-i:\\b{re.escape(stem)}))" for stem in _ABBREVIATION_STEMS]
    # WHY the generic single-capital rule (fix: truncated obligations): a
    # lone capital letter before a period is an initial or enumeration
    # letter ("Pub. L. 95-507", "John Q. Public", "Rev. A"), never a
    # sentence end.  \b excludes word-final capitals ("NASA-STD-6001B.")
    # so real sentence ends still terminate.
    + [r"(?<=\b(?-i:[A-Z]))"]
)
# WHY lowercase sentence starters (fix: merged obligations): OCR'd or
# plain-text regulatory sources often lose capitalization ("the contractor
# shall comply. the vendor must report."), and a boundary that requires a
# capital/digit after the period silently fused the two duties into one
# statement.  The list is deliberately a small closed set of common sentence
# openers so mid-sentence periods ("para. (b)", "e.g. teflon") are not split:
# the abbreviation branch is tried first, and a digit before the period
# ("item 5. the next") is treated as a potential enumeration, not a boundary.
_LOWERCASE_SENTENCE_STARTERS = "the|this|unless|where|when|each|all|any|an|if|it|no|a"
_INTERNAL_PERIOD = (
    rf"(?:(?:{_ABBREV_LOOKBEHINDS})\."
    rf"|\.(?!(?:\s+(?-i:[A-Z0-9\[\(\"'])|\s*$"
    rf"|(?<!\d\.)\s+(?-i:(?:{_LOWERCASE_SENTENCE_STARTERS}))\s)))"
)
_SENTENCE_BODY = rf"(?:[^.\n]|{_INTERNAL_PERIOD})"

# WHY longest-first alternation: multi-word forms ("shall not") must be tried
# before their single-word substrings ("shall") so the strongest surface form
# is captured.  Shared by OBLIGATION_PATTERN and the strongest-class
# classifier so both always agree on what counts as a keyword.
_OBLIGATION_KEYWORD_ALTERNATION = (
    "shall not|shall|must not|must|are required to|are required|is required to|is required|"
    "be required to|be required|are prohibited|is prohibited|be prohibited|prohibited|"
    "should not|should|may not|may|will"
)

OBLIGATION_PATTERN = re.compile(
    r"(?:^|(?<=\.\s)|(?<=\n))"
    rf"({_SENTENCE_BODY}*?"
    rf"\b({_OBLIGATION_KEYWORD_ALTERNATION})\b"
    rf"{_SENTENCE_BODY}*)"
    r"\.?",
    re.IGNORECASE | re.MULTILINE,
)

_OBLIGATION_KEYWORD_RE = re.compile(
    rf"\b({_OBLIGATION_KEYWORD_ALTERNATION})\b", re.IGNORECASE
)

# WHY this ranking (fix: leftmost-keyword misclassification): a sentence like
# "The contractor should verify inputs and shall report all defects." was
# previously classified by its LEFTMOST keyword ("should" → recommendation)
# and then dropped by every mandatory-only filter, silently discarding a
# binding duty.  Classification must reflect the STRONGEST obligation class
# present anywhere in the sentence: prohibition > mandatory > recommendation
# > permission/intent.
_OBLIGATION_TYPE_STRENGTH = {
    "prohibition": 4,
    "mandatory": 3,
    "recommendation": 2,
    "permission": 1,
    "intent": 1,
}


def _classify_sentence_obligation(sentence: str) -> tuple[str, str]:
    """Return (keyword, obligation_type) for the strongest keyword class present.

    The returned keyword is the first occurrence of the winning class, so the
    obligation_keyword field stays consistent with the chosen obligation_type.
    Returns ("", "") when no obligation keyword is present.
    """
    best: tuple[int, str, str] | None = None
    for match in _OBLIGATION_KEYWORD_RE.finditer(sentence):
        keyword = match.group(1).lower()
        obligation_type = OBLIGATION_KEYWORDS.get(keyword, "mandatory")
        strength = _OBLIGATION_TYPE_STRENGTH.get(obligation_type, 0)
        if best is None or strength > best[0]:
            best = (strength, keyword, obligation_type)
    if best is None:
        return "", ""
    return best[1], best[2]

# Improved section pattern: tolerant of PDF line-break artifacts
SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*"
    r"(\d+(?:\.\d+)*[a-z]?(?:\(\d+\))*)"
    r"(?:[\s.:\-]+([A-Z][^\n]{0,120})|\s*\n\s*([A-Z][^\n]{0,120}))",
    re.MULTILINE,
)

# Tagged requirement extraction
TAG_PREFIX_PATTERN = r"MPR|FCR|NER|AMR"
TAG_BODY_PATTERN = rf"(?:{TAG_PREFIX_PATTERN})\s*[-\s]?\s*\d+[a-z]?"
MPR_TAG_PATTERN = re.compile(
    rf"\[\s*({TAG_PREFIX_PATTERN})\s*[-\s]?\s*(\d+[a-z]?)\s*\]",
    re.IGNORECASE,
)
TAGGED_SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*"
    r"(\d+(?:\.\d+)*[a-z]?(?:\(\d+\))*)"
    rf"\s+\[\s*{TAG_BODY_PATTERN}\s*\]",
    re.IGNORECASE | re.MULTILINE,
)

# Justification/rationale markers
RATIONALE_PATTERN = re.compile(
    rf"(?:Rationale|Note|Justification|Basis)\s*[:\-]\s*(.+?)(?=\n\s*\n|\n\s*\[\s*{TAG_BODY_PATTERN}|\n\s*\d+(?:\.\d+)+\s+[A-Z]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# WHY this signal pattern exists:
#   Some standards place the hazard/mechanism sentence immediately before
#   the tagged shall statement without an explicit "Rationale:" label.
#   These tokens bias the extractor toward true engineering reasons rather
#   than generic narrative prose.
PRECEDING_RATIONALE_SIGNAL_PATTERN = re.compile(
    r"\b(?:because|due to|to avoid|to prevent|to reduce|to minimize|to ensure|"
    r"to protect|hazard|risk|toxic|toxicity|contaminat|outgas|outgassing|"
    r"sublim|embrittlement|corrosion|flammab|whisker|degrad|damage|failure)\b",
    re.IGNORECASE,
)

# WHY these stopwords are excluded:
#   Overlap between the requirement and the candidate rationale is used as
#   a guardrail. Generic grammar words would create false overlap and pull
#   in nearby narrative sentences that are not actual rationale.
RATIONALE_OVERLAP_STOPWORDS = {
    "all",
    "and",
    "are",
    "be",
    "crew",
    "for",
    "from",
    "hardware",
    "not",
    "shall",
    "that",
    "the",
    "their",
    "these",
    "this",
    "use",
    "used",
    "vacuum",
}

# ---------------------------------------------------------------------------
# Domain vocabulary for keyword extraction.
#
# WHY these specific terms:
#   These are the high-signal nouns from NASA M&P (Materials & Processes)
#   standards — specifically NASA-STD-6001B (flammability), 6016C (M&P
#   requirements), MMPDS (metallic design data), and CMH-17 (composites).
#
#   Each term was selected because it appears in rule text AND is useful
#   for downstream classification:
#
#   Materials: material(s), metallic, nonmetallic, polymer, composite,
#     adhesive, elastomer, fluoropolymer — identifies WHAT is being
#     regulated.  Enables filtering by material family.
#
#   Processes: welding, bonding, coating, plating, heat-treat, annealing,
#     braze, solder, weld — identifies manufacturing processes that carry
#     their own qualification requirements.
#
#   Environments: oxygen, hydrogen, cryogenic, vacuum, propellant,
#     flammability — identifies service environments that trigger
#     additional testing requirements (e.g. O2 compatibility per 6001B).
#
#   Failure modes: corrosion, fracture, fatigue, embrittlement, toxicity,
#     outgassing — identifies the risk being mitigated.  Critical for
#     mapping rules to FMEA entries.
#
#   Program artifacts: MUA, MAPTIS, NDE, qualification, certification,
#     specification — identifies process/documentation requirements vs.
#     technical requirements.
#
#   Both singular and plural forms are included (material/materials,
#   process/processes) because PDF extraction may capture either form
#   and the extractor does not stem these terms.
#
# WHY this enables downstream use:
#   After extraction, each shall statement is tagged with matching domain
#   keywords.  This powers: (1) faceted search in rule packs, (2) auto-
#   routing to the correct MIRA engine (H2, galvanic, flammability),
#   (3) applicability filtering when building project-specific rule sets.
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Applicability classification patterns.
#
# WHY these patterns matter:
#   NASA requirements are not universally applied — they are scoped by
#   service environment, criticality level, and material class.  A rule
#   that applies to "human-rated oxygen systems" does NOT apply to an
#   unmanned structural component.  These patterns auto-tag each extracted
#   shall statement with its applicability scope.
#
#   human_rated: Triggers the most stringent requirements (crew safety).
#     Human-rated hardware must meet NASA-STD-5009 and additional testing.
#   mission_critical / safety_critical / flight_critical: Tiered
#     criticality levels that determine required test depth and review
#     authority.
#   oxygen_service: O2-compatible materials require flammability testing
#     per NASA-STD-6001B.  LOX = liquid oxygen, GOX = gaseous oxygen.
#   hydrogen_service: H2 compatibility requires embrittlement assessment.
#     LH2 = liquid hydrogen, GH2 = gaseous hydrogen.
#   propellant: Hypergolic propellants (NTO = nitrogen tetroxide,
#     MMH = monomethylhydrazine) require unique compatibility testing.
#   pressure_systems: Pressure vessels/lines require fracture-mechanics
#     analysis per NASA-STD-5019.
#   structural: Load-bearing components require fatigue and fracture
#     assessment.
#   thermal: Cryogenic or elevated-temperature service changes allowable
#     properties and requires specific test data.
#   contamination_control: NVR = non-volatile residue, outgassing per
#     ASTM E595 — critical for vacuum/optical/oxygen systems.
#   metallic / nonmetallic: Fundamental material class split that
#     determines which standards apply (MMPDS vs. CMH-17, different
#     flammability test methods).
#
# WHY regex instead of keyword sets:
#   These terms appear in compound forms with varying punctuation in PDFs
#   (e.g. "human-rated", "human rated", "humanrated" after OCR).  Regex
#   with .? wildcards handles the variation without maintaining separate
#   entries for each spelling.
# ---------------------------------------------------------------------------
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
    # WHY: implicit-obligation page attribution is best-effort (the LLM sees a
    # multi-page chunk).  When no page can be located, we set page=0 and flag
    # it here rather than fabricating precision (spec §5.5).
    page_uncertain: bool = False


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
    # WHY these three fields (spec §5.4/§5.5): a half-failed enrichment or
    # implicit-detection run must be distinguishable from a complete one.
    # Failures are logged AND recorded here so downstream pack builders and
    # the promotion gate can see exactly which page ranges are missing.
    extraction_status: str = "complete"
    failed_page_ranges: list[str] = field(default_factory=list)
    chunk_failures: list[dict] = field(default_factory=list)


# ============================================================================
# Fix 4: Text preprocessing — join PDF-broken lines
# ============================================================================


def _preprocess_page_text(raw_text: str) -> str:
    """Rejoin lines broken by PDF column/page layout.

    Preserves line breaks before section headers (e.g. '4.1.2 Title')
    and before tagged requirement markers. Everything else gets joined so
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

        # New paragraph if line starts with section number or a tagged requirement.
        starts_new = bool(
            re.match(r"\s*\d+(?:\.\d+)+[a-z]?\s+[A-Z]", line)
            or re.match(r"\s*\d+(?:\.\d+)+[a-z]?(?:\(\d+\))?\s*$", line)
            or re.match(rf"\s*\[\s*{TAG_BODY_PATTERN}", line, re.IGNORECASE)
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
    r"(?:[\s.:\-]+([A-Z][^\n]{0,120})|\s*\n\s*([A-Z][^\n]{0,120}))",
    re.MULTILINE,
)


def _find_mpr_block_end(text: str, start: int) -> int:
    """Find the end of a tagged requirement block.

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
    """Extract full requirement text between consecutive tagged requirement ids."""
    results = []
    for match in MPR_TAG_PATTERN.finditer(text):
        tag_type = match.group(1).upper()
        tag_num = match.group(2)
        mpr_id = f"{tag_type} {tag_num}"

        # Capture from end of tag to next boundary
        start = match.end()
        end = _find_mpr_block_end(text, start)

        block = re.sub(r"\s+", " ", text[start:end]).strip()
        block = re.sub(r"\s+(?:[a-z]\.|\(\d+\))\s*$", "", block, flags=re.IGNORECASE)
        block = block.rstrip(".")

        if len(block) < 10:
            continue

        results.append(
            {
                "mpr_id": mpr_id,
                "text": block,
                "tag_start": match.start(),
                "tag_end": match.end(),
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


def _extract_labeled_rationale(window: str) -> str:
    """Extract the nearest explicit rationale/note marker from a text window."""
    matches = list(RATIONALE_PATTERN.finditer(window))
    if not matches:
        return ""
    rationale = re.sub(r"\s+", " ", matches[-1].group(1)).strip()
    if len(rationale) <= 10:
        return ""
    return rationale[:300]


def _requirement_overlap_terms(requirement_text: str) -> set[str]:
    """Return subject terms that must overlap with an unlabeled rationale."""
    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9/-]{2,}", requirement_text)
    }
    return {token for token in tokens if token not in RATIONALE_OVERLAP_STOPWORDS}


def _extract_preceding_rationale(window: str, requirement_text: str) -> str:
    """Reuse the nearest prior hazard/mechanism sentence when it is on-topic."""
    overlap_terms = _requirement_overlap_terms(requirement_text)
    if not overlap_terms:
        return ""

    candidates = [
        re.sub(r"\s+", " ", chunk).strip()
        for chunk in re.split(r"(?<=[.!?])\s+|\n+", window)
        if chunk.strip()
    ]

    for candidate in reversed(candidates[-3:]):
        lowered = candidate.lower()
        if len(candidate) < 20:
            continue
        if re.search(r"\b(shall|must|required|prohibited|should|may|will)\b", candidate, re.IGNORECASE):
            continue
        if not PRECEDING_RATIONALE_SIGNAL_PATTERN.search(candidate):
            continue
        if not any(term in lowered for term in overlap_terms):
            continue
        return candidate[:300]
    return ""


def _extract_justification(
    full_page_text: str,
    tag_start_pos: int,
    tag_end_pos: int,
    requirement_text: str,
) -> str:
    """Look for rationale text around the tagged requirement."""
    # WHY 500 chars: enough to capture the adjacent note/basis paragraph
    # while staying inside the local requirement neighborhood on NASA PDFs.
    forward_window = full_page_text[tag_end_pos:min(len(full_page_text), tag_end_pos + 500)]
    forward_rationale = _extract_labeled_rationale(forward_window)
    if forward_rationale:
        return forward_rationale

    backward_window = full_page_text[max(0, tag_start_pos - 500):tag_start_pos]
    backward_rationale = _extract_labeled_rationale(backward_window)
    if backward_rationale:
        return backward_rationale

    return _extract_preceding_rationale(backward_window, requirement_text)


def _split_inline_rationale(text: str) -> tuple[str, str]:
    parts = re.split(r"\bRationale:\s*", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        lead = parts[0].strip()
        rationale = parts[1].strip()
        return lead, rationale
    return text, ""


def _clean_tagged_requirement_text(text: str) -> str:
    cleaned = re.sub(
        r"\s+\d+\.\d+\.\d+(?:\.\d+)*[a-z]?(?:\(\d+\))?\s*$",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    return cleaned.strip().rstrip(".")


def _statement_is_covered_by_tagged_requirement(
    sentence: str,
    page_number: int,
    tagged_by_page: dict[int, list[str]],
) -> bool:
    sentence_norm = re.sub(r"\s+", " ", sentence).strip().lower()
    if not sentence_norm:
        return False
    for tagged_text in tagged_by_page.get(page_number, []):
        if sentence_norm in tagged_text or tagged_text in sentence_norm:
            return True
    return False


# ============================================================================
# Pass 1 extraction (improved)
# ============================================================================

# ---------------------------------------------------------------------------
# Noise terms: strings whose presence in a sentence indicates boilerplate
# or document-navigation text rather than an actual obligation.
#
# WHY these specific terms:
#   "page " — page number artifacts from PDF extraction (e.g. "page 12 of
#     45").  The trailing space distinguishes "page 12" from legitimate
#     uses like "page-level requirements."
#   "table of contents" — TOC entries contain obligation keywords ("shall"
#     appears in the title of sections about shall-statements) but are
#     not obligations themselves.  Without this filter, every TOC line
#     would generate a false extraction.
#   "revision history" — revision log entries describe past changes using
#     obligation language ("added shall statement in 4.2") but are not
#     current requirements.
#   "export controlled" — ITAR/EAR markings appear on every page of
#     controlled documents.  They contain "shall" in the warning text
#     but are not technical requirements.
#   "proprietary" — similar to export-controlled; proprietary notices
#     use mandatory language about handling restrictions that would
#     pollute the obligation set.
#
# These are checked via substring match (case-insensitive) — simple and
# fast.  A sentence matching ANY noise term is skipped entirely.
# ---------------------------------------------------------------------------
NOISE_TERMS = (
    "page ",
    "table of contents",
    "revision history",
    "export controlled",
    "proprietary",
)

# ---------------------------------------------------------------------------
# Generic skip-page patterns: regex patterns that identify entire pages
# whose content should be excluded from obligation extraction.
#
# WHY these specific patterns:
#   "requirements identification matrix" — RIM/RTM pages are cross-reference
#     tables that LIST requirement IDs but do not DEFINE them.  Extracting
#     from these pages produces duplicate, context-free fragments.
#   "requirement in this standard" — meta-discussion about the standard's
#     own requirement structure (e.g. "Each requirement in this standard
#     is verified by...").  These are about the document, not the domain.
#   "for example purposes only" — example/illustration pages that use
#     obligation language in hypothetical contexts.  Extracting these
#     would create false requirements.
#   "not requirements related to this standard" — explicit disclaimer
#     pages that warn the reader certain content is informational only.
#
# These patterns are checked against the full page text.  If ANY pattern
# matches, the entire page is skipped.  This is aggressive but correct:
# these page types consistently produce false extractions, and any real
# obligations on these pages are restated in their canonical location.
# ---------------------------------------------------------------------------
GENERIC_SKIP_PAGE_PATTERNS = (
    re.compile(r"requirements identification matrix", re.IGNORECASE),
    re.compile(r"requirement in this standard", re.IGNORECASE),
    re.compile(r"for example purposes only", re.IGNORECASE),
    re.compile(r"not requirements related to this standard", re.IGNORECASE),
)

STRONG_GENERIC_KEYWORDS = {
    "shall",
    "shall not",
    "must",
    "must not",
    "are required to",
    "are required",
    "is required to",
    "is required",
    "be required to",
    "be required",
    "are prohibited",
    "is prohibited",
    "be prohibited",
    "prohibited",
}


def _detect_current_section(text: str, char_pos: int, carry_section: str = "") -> str:
    best_section = carry_section
    best_pos = -1
    for match in SECTION_PATTERN.finditer(text):
        if match.start() <= char_pos:
            if match.start() >= best_pos:
                best_section = match.group(1).strip()
                best_pos = match.start()
        else:
            break
    for match in TAGGED_SECTION_PATTERN.finditer(text):
        if match.start() <= char_pos:
            if match.start() >= best_pos:
                best_section = match.group(1).strip()
                best_pos = match.start()
        else:
            break
    return best_section


def _detect_subitem_suffix(text: str, char_pos: int) -> str:
    line_start = text.rfind("\n", 0, char_pos) + 1
    prefix = text[line_start:char_pos]
    letter_match = re.match(r"\s*([a-z])\.\s*$", prefix, re.IGNORECASE)
    if letter_match:
        return letter_match.group(1).lower()
    numeric_match = re.match(r"\s*(\(\d+\))\s*$", prefix)
    if numeric_match:
        return numeric_match.group(1)
    return ""


def _append_subitem_suffix(section: str, suffix: str) -> str:
    if not section or not suffix:
        return section
    if section.endswith(suffix):
        return section
    return f"{section}{suffix}"


def _extract_subject_requirement(statement: str, keyword: str) -> tuple[str, str]:
    match = re.search(r"\b" + re.escape(keyword) + r"\b", statement, re.IGNORECASE)
    if not match:
        return "", statement
    subject = statement[: match.start()].strip().rstrip(",").strip()
    requirement = statement[match.end() :].strip().lstrip(",").strip()
    if len(subject) < 2:
        subject = "(implicit)"
    return subject, requirement


def _extract_tagged_requirements(
    doc,
    stmt_id_start: int = 0,
) -> tuple[list[ShallStatement], dict[int, list[str]], int | None, int | None, int]:
    """Phase A: Extract MPR/FCR tag-aware requirements (full block text).

    Returns (statements, tagged_texts_by_page, first_tagged_page,
    last_tagged_page, next_stmt_id).
    """
    statements: list[ShallStatement] = []
    seen_mpr_ids: set[str] = set()
    tagged_texts_by_page: dict[int, list[str]] = {}
    first_tagged_page: int | None = None
    last_tagged_page: int | None = None
    carry_base_section = ""
    stmt_id = stmt_id_start

    for page_idx in range(len(doc)):
        raw_text = doc[page_idx].get_text()
        if not raw_text or len(raw_text.strip()) < 20:
            continue

        text = _preprocess_page_text(raw_text)

        for block in _extract_mpr_blocks(text, page_idx + 1):
            mpr_id = block["mpr_id"]
            if mpr_id in seen_mpr_ids:
                continue

            full_text, inline_rationale = _split_inline_rationale(block["text"])
            full_text = _clean_tagged_requirement_text(full_text)

            has_obligation = bool(
                re.search(
                    r"\bshall\b|\bmust\b|\brequired\b|\bprohibited\b",
                    full_text, re.IGNORECASE,
                )
            )
            if not has_obligation or len(full_text) < 30:
                continue

            seen_mpr_ids.add(mpr_id)
            tagged_texts_by_page.setdefault(block["page"], []).append(
                re.sub(r"\s+", " ", full_text).strip().lower()
            )
            if first_tagged_page is None:
                first_tagged_page = block["page"]
            last_tagged_page = block["page"]

            base_section = _detect_current_section(text, block["tag_start"], carry_base_section)
            section = _append_subitem_suffix(
                base_section,
                _detect_subitem_suffix(text, block["tag_start"]),
            )
            if base_section:
                carry_base_section = base_section

            kw_match = re.search(
                r"\b(shall not|shall|must not|must|are required to|are required|is required to|is required|"
                r"be required to|be required|required|are prohibited|is prohibited|be prohibited|prohibited)\b",
                full_text, re.IGNORECASE,
            )
            keyword = kw_match.group(0).lower() if kw_match else "shall"
            obligation_type = OBLIGATION_KEYWORDS.get(keyword, "mandatory")
            subject, requirement = _extract_subject_requirement(full_text, keyword)

            justification = _extract_justification(
                text,
                block["tag_start"],
                block["tag_end"],
                full_text,
            )
            if inline_rationale:
                inline_rationale = re.sub(r"\s+", " ", inline_rationale).strip()
                justification = f"{inline_rationale} {justification}".strip() if justification else inline_rationale
            keywords = _extract_keywords(full_text)
            applies_to = _classify_applicability(full_text, justification)

            stmt_id += 1
            statements.append(
                ShallStatement(
                    id=stmt_id, page=block["page"], section=section,
                    obligation_keyword=keyword, obligation_type=obligation_type,
                    statement_text=full_text, subject=subject, requirement=requirement,
                    context="", mpr_id=mpr_id, justification=justification,
                    keywords=keywords, applies_to=applies_to,
                )
            )

    return statements, tagged_texts_by_page, first_tagged_page, last_tagged_page, stmt_id


def _extract_generic_requirements(
    doc,
    tagged_texts_by_page: dict[int, list[str]],
    first_tagged_page: int | None,
    last_tagged_page: int | None,
    tagged_standard: bool,
    stmt_id_start: int = 0,
) -> tuple[list[ShallStatement], int]:
    """Phase B: Extract generic obligation statements (non-tagged shall/must/etc.).

    Returns (generic_statements_after_dedup, dedup_removed_count).
    """
    generic_statements: list[ShallStatement] = []
    stmt_id = stmt_id_start
    generic_carry_section = ""

    for page_idx in range(len(doc)):
        raw_text = doc[page_idx].get_text()
        if not raw_text or len(raw_text.strip()) < 20:
            continue

        text = _preprocess_page_text(raw_text)
        page_number = page_idx + 1

        if tagged_standard and first_tagged_page is not None and last_tagged_page is not None:
            if page_number < first_tagged_page or page_number > last_tagged_page:
                continue
            if any(pattern.search(text) for pattern in GENERIC_SKIP_PAGE_PATTERNS):
                continue

        for match in OBLIGATION_PATTERN.finditer(text):
            sentence = match.group(1).strip()
            # Classify by the STRONGEST keyword class in the sentence, not the
            # leftmost match — see _classify_sentence_obligation WHY comment.
            keyword, strongest_type = _classify_sentence_obligation(sentence)
            if not keyword:
                keyword = match.group(2).lower()
            if len(sentence) < 15:
                continue
            if any(noise in sentence.lower() for noise in NOISE_TERMS):
                continue
            if tagged_standard and keyword not in STRONG_GENERIC_KEYWORDS:
                continue

            if MPR_TAG_PATTERN.search(sentence):
                continue
            if _statement_is_covered_by_tagged_requirement(
                sentence, page_number, tagged_texts_by_page,
            ):
                continue

            obligation_type = strongest_type or OBLIGATION_KEYWORDS.get(keyword, "mandatory")
            section = _detect_current_section(text, match.start(), generic_carry_section)
            subject, requirement = _extract_subject_requirement(sentence, keyword)
            ctx_start = max(0, match.start() - 120)
            ctx_end = min(len(text), match.end() + 120)
            context = text[ctx_start:ctx_end].strip()

            keywords = _extract_keywords(sentence)
            applies_to = _classify_applicability(sentence, context)

            stmt_id += 1
            generic_statements.append(
                ShallStatement(
                    id=stmt_id, page=page_number, section=section,
                    obligation_keyword=keyword, obligation_type=obligation_type,
                    statement_text=sentence, subject=subject, requirement=requirement,
                    context=context, keywords=keywords, applies_to=applies_to,
                )
            )

        page_tail_section = _detect_current_section(text, len(text), generic_carry_section)
        if page_tail_section:
            generic_carry_section = page_tail_section

    generic_statements, dedup_removed = _dedupe_boilerplate(generic_statements)
    return generic_statements, dedup_removed


# WHY 5: page headers/footers repeat on every page, so a genuine header shows
# up at least as often as the page count of the shortest real chapter.
_BOILERPLATE_REPEAT_THRESHOLD = 5

# WHY a distinct-page spread threshold (fix: boilerplate resurrection):
# footers/headers inherit the page's CURRENT section at extraction time, so
# on a long PDF the same footer text shows up under dozens of section values
# and the one-copy-per-section keep resurrected it as one bogus "rule" per
# section context.  Genuine cross-section restatements — the case the
# section-aware keep exists for — are typically 2-4 copies; no real
# obligation is restated verbatim on 5+ DISTINCT pages, but page furniture
# by definition is.  Page numbers are available at dedup time
# (ShallStatement.page), so spread across >= 5 distinct pages marks the text
# as furniture and removes ALL copies (the pre-section-aware behavior).
_PAGE_FURNITURE_PAGE_SPREAD = 5


def _dedupe_boilerplate(
    generic_statements: list[ShallStatement],
) -> tuple[list[ShallStatement], int]:
    """Header/footer dedup keyed on page spread, section, and normalized text.

    Decision ladder for text repeated >= _BOILERPLATE_REPEAT_THRESHOLD times:
      1. Spread across >= _PAGE_FURNITURE_PAGE_SPREAD distinct pages
         => page furniture: remove ALL copies (see WHY above).
      2. Identical (possibly empty) section on every repeat
         => boilerplate within one context: remove ALL copies.
      3. Otherwise (low page spread, several sections) => a real obligation
         restated verbatim across sections (e.g. a records-retention duty in
         both the delivery and the archive section): keep one copy per
         distinct section — deleting all copies silently removed real duties.
    """
    by_text: dict[str, list[ShallStatement]] = {}
    for stmt in generic_statements:
        by_text.setdefault(_normalize_for_dedup(stmt.statement_text), []).append(stmt)

    dropped: set[int] = set()
    boilerplate_patterns = 0
    for group in by_text.values():
        if len(group) < _BOILERPLATE_REPEAT_THRESHOLD:
            continue
        pages = {stmt.page for stmt in group}
        if len(pages) >= _PAGE_FURNITURE_PAGE_SPREAD:
            dropped.update(id(stmt) for stmt in group)
            boilerplate_patterns += 1
            continue
        sections = {stmt.section for stmt in group}
        if len(sections) == 1:
            # Same (possibly empty) section on every repeat => boilerplate.
            dropped.update(id(stmt) for stmt in group)
            boilerplate_patterns += 1
            continue
        seen_sections: set[str] = set()
        for stmt in group:
            if stmt.section in seen_sections:
                dropped.add(id(stmt))
            else:
                seen_sections.add(stmt.section)

    kept = [stmt for stmt in generic_statements if id(stmt) not in dropped]
    removed = len(generic_statements) - len(kept)
    if removed:
        LOGGER.info(
            "Boilerplate dedup: removed %d duplicates (%d pure-boilerplate patterns)",
            removed, boilerplate_patterns,
        )
    return kept, removed


def extract_pass1(pdf_path: Path) -> ExtractionResult:
    """Pass 1: Extract all binding obligations from a PDF.

    Two-phase approach:
      Phase A: MPR/FCR tag-aware extraction (structured NASA standards)
      Phase B: Generic obligation extraction (shall/must/required patterns)

    Phase B is scoped to the tagged page range when >= 20 tagged requirements
    are found, to avoid extracting noise from front/back matter.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    LOGGER.info("Pass 1: extracting from %s (%d pages)", pdf_path.name, total_pages)

    # Phase A: Tagged requirements
    tagged_stmts, tagged_texts_by_page, first_tp, last_tp, stmt_id = (
        _extract_tagged_requirements(doc)
    )
    LOGGER.info("Phase A: %d MPR/FCR tagged requirements", len(tagged_stmts))

    # Phase B: Generic requirements
    tagged_standard = len({s.mpr_id for s in tagged_stmts if s.mpr_id}) >= 20
    generic_stmts, dedup_removed = _extract_generic_requirements(
        doc, tagged_texts_by_page, first_tp, last_tp, tagged_standard, stmt_id,
    )

    doc.close()

    # Merge and renumber
    statements = tagged_stmts + generic_stmts
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

    LOGGER.info(
        "Pass 1 complete: %d statements (%d MPR/FCR, %d generic, %d deduped)",
        result.total_statements, mpr_count, len(generic_stmts), dedup_removed,
    )
    return result


# ============================================================================
# Pass 1.5: Sonnet Vision Enrichment
# ============================================================================

SONNET_MODEL = "claude-sonnet-4-5-20250929"

ENRICHMENT_PROMPT = """You are analyzing a page from a NASA technical standard document.

The following requirement tags were found on this page: {mpr_list}

For EACH tagged requirement on this page, extract these fields by reading the actual document:

1. "mpr_id": The tag exactly as written (e.g., "MPR 15", "FCR 3", "NER 12")
2. "section": The section number this requirement falls under (e.g., "4.1.2", "4.2.1.3.a"). Read the section heading above the requirement.
3. "shall_text": The COMPLETE requirement text from the tagged requirement through the end of the requirement. Include all sentences — do not truncate.
4. "justification": Any rationale, note, or guidance text that follows the requirement. This is often italicized, indented, or preceded by "Rationale:", "Note:", "Guidance:", or appears as explanatory text below the requirement. If none, use empty string.
5. "keywords": 3-7 domain-specific technical terms from the requirement (e.g., "flammability", "hydrogen", "fracture-critical", "NDE", "outgassing")
6. "applies_to": Classification tags that describe what this requirement applies to. Choose from: human_rated, mission_critical, oxygen_service, hydrogen_service, propellant, pressure_systems, structural, thermal, contamination_control, metallic, nonmetallic, electrical, welding_joining, testing, documentation, vendor_control, additive_manufacturing

Return ONLY valid JSON in this format:
{{"requirements": [{{"mpr_id": "NER 12", "section": "4.1.2", "shall_text": "...", "justification": "...", "keywords": [...], "applies_to": [...]}}]}}
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


# ============================================================================
# Shared Anthropic call plumbing (Pass 1.5 vision enrichment + Pass 1c
# implicit detection)
# ============================================================================


class ExtractionAbortedError(RuntimeError):
    """A paid extraction loop must stop immediately (e.g. revoked API key)."""


class ChunkExtractionError(RuntimeError):
    """One chunk/page failed after all retries; the run may continue."""

    def __init__(self, message: str, retries_used: int = 0):
        super().__init__(message)
        self.retries_used = retries_used


# WHY 3 attempts: matches extract_pass2's consecutive-failure budget — enough
# to ride out a transient blip without burning money on a systemic outage.
_MAX_API_ATTEMPTS = 3
# WHY 2 re-prompts: spec §5.4 — strip fences, retry parse, re-prompt with the
# malformed output, at most twice, then record the chunk failure.
_JSON_REPROMPT_LIMIT = 2
_JSON_REPROMPT_INSTRUCTION = (
    "Your previous reply was not valid JSON. Reply again with the same "
    "content, emitting valid JSON only — no markdown fences, no commentary."
)

# WHY a rough constant instead of exact token math: the upfront log line only
# needs order-of-magnitude honesty so an operator notices "500 pages ≈ $10"
# BEFORE the loop spends it.  ~3.5K input + ~0.5K output tokens per page at
# Sonnet pricing ($3/$15 per MTok) ≈ $0.018/page, rounded up.
_EST_COST_PER_PAGE_USD = 0.02


def _log_run_estimate(label: str, page_count: int) -> None:
    LOGGER.info(
        "%s: %d page(s) queued for Anthropic calls (rough cost ~$%.2f at ~$%.3f/page)",
        label, page_count, page_count * _EST_COST_PER_PAGE_USD, _EST_COST_PER_PAGE_USD,
    )


def _classify_api_error(exc: Exception) -> str:
    """Triage an API error: 'auth' | 'rate_limit' | 'transient'.

    Uses status codes / class names rather than anthropic exception imports so
    the triage also works with injected fake clients in tests.
    """
    name = type(exc).__name__.lower()
    status = getattr(exc, "status_code", None)
    if status in (401, 403) or "authentication" in name or "permissiondenied" in name:
        return "auth"
    if status == 429 or "ratelimit" in name:
        return "rate_limit"
    return "transient"


def _retry_after_seconds(exc: Exception) -> float | None:
    """Honor a Retry-After header when the API provides one."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("retry-after")
        return float(value) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def _call_anthropic_with_retries(
    client,
    request: dict,
    *,
    base_delay: float = 1.0,
    max_attempts: int = _MAX_API_ATTEMPTS,
):
    """Call client.messages.create with triaged retries.

    WHY the triage: a revoked key on a 500-page run would otherwise burn ~100
    doomed API attempts.  Auth errors abort the whole run immediately
    (ExtractionAbortedError); rate limits back off exponentially honoring
    Retry-After; transient errors retry with exponential backoff.  Returns
    (response, retries_used) or raises ChunkExtractionError when exhausted.
    """
    last_error = "unknown error"
    for attempt in range(max_attempts):
        try:
            return client.messages.create(**request), attempt
        except Exception as exc:
            kind = _classify_api_error(exc)
            last_error = f"{type(exc).__name__}: {exc}"
            if kind == "auth":
                raise ExtractionAbortedError(
                    f"auth/permission error from Anthropic API: {last_error}"
                ) from exc
            if attempt + 1 >= max_attempts:
                break
            delay = _retry_after_seconds(exc) if kind == "rate_limit" else None
            if delay is None:
                delay = base_delay * (2 ** attempt)
            LOGGER.warning(
                "Anthropic %s error (attempt %d/%d), retrying in %.1fs: %s",
                kind, attempt + 1, max_attempts, delay, exc,
            )
            if delay > 0:
                time.sleep(delay)
    raise ChunkExtractionError(last_error, retries_used=max_attempts - 1)


def _strip_markdown_fences(text: str) -> str:
    if "```" not in text:
        return text.strip()
    start_idx = text.find("```")
    first_nl = text.find("\n", start_idx)
    end_idx = text.rfind("```")
    if first_nl != -1 and end_idx > first_nl:
        return text[first_nl + 1 : end_idx].strip()
    return text.strip()


def _request_json_with_reprompt(
    client,
    request: dict,
    *,
    base_delay: float = 1.0,
) -> tuple[dict, int]:
    """Spec §5.4 malformed-JSON ladder: strip fences → parse → re-prompt with
    the malformed output and "valid JSON only" → max 2 re-prompts → raise
    ChunkExtractionError so the caller records the chunk failure.

    Returns (parsed_json, retries_used).
    """
    retries_used = 0
    messages = list(request["messages"])
    last_error: Exception | None = None
    for reprompt in range(_JSON_REPROMPT_LIMIT + 1):
        response, api_retries = _call_anthropic_with_retries(
            client, {**request, "messages": messages}, base_delay=base_delay,
        )
        retries_used += api_retries
        raw = response.content[0].text if response.content else ""
        try:
            return json.loads(_strip_markdown_fences(raw)), retries_used
        except json.JSONDecodeError as exc:
            last_error = exc
            if reprompt >= _JSON_REPROMPT_LIMIT:
                break
            retries_used += 1
            LOGGER.warning(
                "Model returned malformed JSON (%s); re-prompting (%d/%d)",
                exc, reprompt + 1, _JSON_REPROMPT_LIMIT,
            )
            messages = messages + [
                {"role": "assistant", "content": raw or "(empty response)"},
                {"role": "user", "content": _JSON_REPROMPT_INSTRUCTION},
            ]
    raise ChunkExtractionError(
        f"invalid JSON after {_JSON_REPROMPT_LIMIT} re-prompt(s): {last_error}",
        retries_used=retries_used,
    )


def _record_chunk_failure(
    result: ExtractionResult,
    page_start: int,
    page_end: int,
    retries_used: int,
    final_error: str,
    extraction_mode: str,
) -> None:
    """Record a failed chunk in the result metadata (never-suppress-error)."""
    result.extraction_status = "partial"
    result.failed_page_ranges.append(f"{page_start}-{page_end}")
    result.chunk_failures.append(
        {
            "page_start": page_start,
            "page_end": page_end,
            "retries_used": retries_used,
            "final_error": str(final_error)[:500],
            "extraction_mode": extraction_mode,
        }
    )


def _record_run_abort(
    result: ExtractionResult,
    remaining_pages: list[int],
    reason: str,
    extraction_mode: str,
) -> None:
    """Record an aborted tail of pages as one failed range (never silent)."""
    LOGGER.error(
        "Aborting %s run: %s (%d page(s) not processed)",
        extraction_mode, reason, len(remaining_pages),
    )
    result.extraction_status = "partial"
    if remaining_pages:
        _record_chunk_failure(
            result, min(remaining_pages), max(remaining_pages), 0,
            f"not attempted: {reason}", extraction_mode,
        )


# ============================================================================
# Pass 1.5 continued: Sonnet Vision enrichment
# ============================================================================


def _merge_enrichment(stmt: ShallStatement, enrich: dict | None) -> bool:
    """Merge one Sonnet page-enrichment record into a statement.

    Only overwrites a field when Sonnet provides better (longer/nonempty) data.
    """
    if not enrich:
        return False
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
    return True


def _enrich_page_via_vision(
    client,
    doc,
    page_num: int,
    page_stmts: list[ShallStatement],
    dpi: int,
    base_delay: float,
) -> int:
    """Enrich one page's MPR/FCR statements via Sonnet Vision.

    Returns the number of statements enriched.  Raises
    ExtractionAbortedError / ChunkExtractionError on API failure.
    """
    mpr_list_str = ", ".join(f"[{s.mpr_id}]" for s in page_stmts)
    img_b64 = _render_page_to_base64(doc, page_num - 1, dpi)
    request = {
        "model": SONNET_MODEL,
        "max_tokens": 4096,
        "messages": [
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
                    {"type": "text", "text": ENRICHMENT_PROMPT.format(mpr_list=mpr_list_str)},
                ],
            }
        ],
    }
    parsed, _ = _request_json_with_reprompt(client, request, base_delay=base_delay)
    reqs = parsed.get("requirements", []) if isinstance(parsed, dict) else []
    enrichments_by_id = {
        r["mpr_id"]: r for r in reqs if isinstance(r, dict) and "mpr_id" in r
    }
    return sum(
        1 for stmt in page_stmts
        if _merge_enrichment(stmt, enrichments_by_id.get(stmt.mpr_id))
    )


def enrich_with_sonnet(
    result: ExtractionResult,
    pdf_path: Path,
    *,
    api_key: str | None = None,
    dpi: int = 150,
    max_pages: int = 0,
    client=None,
    max_consecutive_failures: int = 3,
    retry_base_delay: float = 1.0,
) -> ExtractionResult:
    """Enrich MPR/FCR statements with Sonnet Vision for better section,
    justification, keywords, and applies_to extraction.

    Failures are logged AND recorded in result.chunk_failures /
    result.extraction_status (spec §5.4/§5.5); auth errors and repeated
    consecutive failures abort the paid loop instead of burning API calls.
    """
    mpr_stmts = [s for s in result.statements if s.mpr_id]
    if not mpr_stmts:
        LOGGER.info("Sonnet enrichment skipped: no MPR/FCR statements")
        return result

    by_page: dict[int, list[ShallStatement]] = {}
    for s in mpr_stmts:
        by_page.setdefault(s.page, []).append(s)
    pages = sorted(by_page.keys())[: max_pages if max_pages > 0 else None]

    LOGGER.info("Sonnet enrichment: %d MPR/FCR across %d pages",
                sum(len(by_page[p]) for p in pages), len(pages))
    _log_run_estimate("Sonnet enrichment", len(pages))

    if client is None:
        client = _get_anthropic_client(api_key)
    doc = fitz.open(pdf_path)
    started = time.time()
    enriched_count, failed_count = _run_enrichment_loop(
        result, client, doc, by_page, pages,
        dpi=dpi,
        max_consecutive_failures=max_consecutive_failures,
        retry_base_delay=retry_base_delay,
    )
    doc.close()
    LOGGER.info(
        "Sonnet enrichment complete: %d/%d enriched, %d failed, status=%s (%.1fs total)",
        enriched_count, len(mpr_stmts), failed_count,
        result.extraction_status, time.time() - started,
    )
    return result


def _run_enrichment_loop(
    result: ExtractionResult,
    client,
    doc,
    by_page: dict[int, list[ShallStatement]],
    pages: list[int],
    *,
    dpi: int,
    max_consecutive_failures: int,
    retry_base_delay: float,
) -> tuple[int, int]:
    """Enrich page by page, recording failures on result; returns
    (enriched_count, failed_statement_count)."""
    enriched_count = failed_count = consecutive_failures = 0
    for i, page_num in enumerate(pages):
        page_stmts = by_page[page_num]
        if page_num - 1 >= len(doc):
            continue
        try:
            enriched = _enrich_page_via_vision(
                client, doc, page_num, page_stmts, dpi, retry_base_delay,
            )
        except ExtractionAbortedError as exc:
            failed_count += sum(len(by_page[p]) for p in pages[i:])
            _record_run_abort(result, pages[i:], str(exc), "vision_enrichment")
            break
        except Exception as exc:  # never suppress: log + record, then decide
            failed_count += len(page_stmts)
            retries = exc.retries_used if isinstance(exc, ChunkExtractionError) else 0
            LOGGER.error("  Page %d enrichment failed: %s", page_num, exc)
            _record_chunk_failure(result, page_num, page_num, retries, str(exc), "vision_enrichment")
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                remaining = pages[i + 1 :]
                failed_count += sum(len(by_page[p]) for p in remaining)
                _record_run_abort(
                    result, remaining,
                    f"aborted after {consecutive_failures} consecutive failures",
                    "vision_enrichment",
                )
                break
        else:
            consecutive_failures = 0
            enriched_count += enriched
            LOGGER.info(
                "  Page %d/%d (p.%d): %d/%d enriched",
                i + 1, len(pages), page_num, enriched, len(page_stmts),
            )
    return enriched_count, failed_count


# ============================================================================
# Pass 1c: Implicit obligation detection
# ============================================================================

IMPLICIT_DETECTION_PROMPT = """You are analyzing a page from a regulatory or contractual document.

Below is the page text. Some explicit obligation statements (using "shall", "must", "required", etc.) have ALREADY been extracted and are listed under ALREADY EXTRACTED.

Your job: find **implicit obligations** — statements that impose a binding requirement on the contractor or system WITHOUT using standard obligation keywords. These are statements that a proposal manager would need to respond to, but that an automated keyword search would miss.

Examples of implicit obligations:
- "Reports are due quarterly" (= contractor shall submit reports quarterly)
- "The system operates at 5V" (= system shall be designed to operate at 5V)
- "All personnel hold a SECRET clearance" (= contractor shall staff only cleared personnel)
- "Testing follows MIL-STD-810" (= contractor shall test per MIL-STD-810)
- "Documentation is maintained in CMMI Level 3 format" (= contractor shall maintain CMMI L3 docs)
- "The program office reviews deliverables within 10 business days" (= deliverables have a 10-day review cycle the contractor must plan around)

Do NOT extract:
- Statements that use shall/must/required/prohibited (already captured)
- Background information, definitions, or scope descriptions
- Statements describing what the government will do (unless they create a contractor obligation)
- Recommendations (should/may)
- Obvious boilerplate or headers

For each implicit obligation found, assess your confidence (0.0-1.0) that this is genuinely a binding requirement rather than informational text.

Return STRICT JSON only:
{{"obligations": [
  {{
    "statement_text": "the exact text from the document",
    "requirement": "what the contractor/system must do (rewritten as an explicit obligation)",
    "subject": "who/what must comply",
    "section": "section number if visible",
    "confidence": 0.0-1.0,
    "keywords": ["keyword1", "keyword2"],
    "context": "brief explanation of why this is binding"
  }}
]}}

Rules:
- Only extract genuinely binding implicit obligations, not informational text.
- Each obligation must be atomic: one requirement per entry.
- Preserve exact source language in statement_text.
- Be conservative — when in doubt, do not extract. False negatives are preferable to false positives.
- Confidence below 0.5 means you're unsure — include it and let the human reviewer decide.
- If no implicit obligations are found, return {{"obligations": []}}.
- Return valid JSON only. No markdown fences, no commentary.\
"""


def _normalize_for_dedup(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for dedup comparison."""
    text = re.sub(r"\s+", " ", text.lower().strip())
    text = re.sub(r"[^\w\s]", "", text)
    return text


def _overlaps_existing(
    new_text: str,
    existing_texts: set[str],
    threshold: float = 0.6,
) -> bool:
    """Check if new_text substantially overlaps any existing statement."""
    new_norm = _normalize_for_dedup(new_text)
    new_words = set(new_norm.split())
    if not new_words:
        return True
    for existing_norm in existing_texts:
        existing_words = set(existing_norm.split())
        if not existing_words:
            continue
        overlap = len(new_words & existing_words)
        smaller = min(len(new_words), len(existing_words))
        if smaller > 0 and overlap / smaller >= threshold:
            return True
    return False


IMPLICIT_CHUNK_SIZE = 5

# WHY 0.6: an implicit obligation is often a light paraphrase of the page
# text; 60% of an 80-char prefix matching contiguously is strong evidence the
# statement came from that page, while anything lower is guesswork we refuse
# to present as a citation.
_PAGE_ATTRIBUTION_MIN_RATIO = 0.6


def _build_implicit_client(api_key: str | None):
    """Construct the Anthropic client used for implicit detection."""
    import os

    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError(
            "anthropic package required for implicit detection. "
            "Run: pip install anthropic"
        )

    import httpx

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError(
            "No API key found. Set ANTHROPIC_API_KEY or pass --api-key"
        )
    return Anthropic(
        api_key=key,
        timeout=httpx.Timeout(
            float(os.environ.get("ORACLE_TIMEOUT_SECONDS", "300")),
            connect=10.0,
        ),
    )


def _implicit_chunk_inputs(
    doc,
    chunk_page_indices: list[int],
    existing_by_page: dict[int, list[ShallStatement]],
) -> tuple[list[tuple[int, str]], list[str]]:
    """Collect (page_number, preprocessed_text) pairs and the already-extracted
    statement summary lines for one chunk."""
    chunk_pages: list[tuple[int, str]] = []
    already_lines: list[str] = []
    for page_idx in chunk_page_indices:
        raw_text = doc[page_idx].get_text()
        if not raw_text or len(raw_text.strip()) < 20:
            continue
        page_num = page_idx + 1
        chunk_pages.append((page_num, _preprocess_page_text(raw_text)))
        for s in existing_by_page.get(page_num, []):
            already_lines.append(
                f"  - [{s.obligation_keyword.upper()}] {s.statement_text[:200]}"
            )
    return chunk_pages, already_lines


def _implicit_prompt_content(
    chunk_pages: list[tuple[int, str]],
    already_lines: list[str],
) -> str:
    page_texts = [f"--- PAGE {num} ---\n{text}" for num, text in chunk_pages]
    already_section = ""
    if already_lines:
        already_section = (
            "\n\nALREADY EXTRACTED (do not re-extract these):\n"
            + "\n".join(already_lines)
        )
    return "\n\n".join(page_texts) + already_section + "\n\n" + IMPLICIT_DETECTION_PROMPT


def _attribute_statement_page(
    stmt_text: str,
    chunk_pages: list[tuple[int, str]],
) -> tuple[int, bool]:
    """Attribute an implicit obligation to a page within its chunk.

    WHY not default to the chunk's first page (old behavior): that fabricated
    citation precision — a reviewer checking "p.6" would find nothing there.
    Exact substring wins; otherwise a difflib longest-block fuzzy match must
    clear _PAGE_ATTRIBUTION_MIN_RATIO, else we return (0, uncertain=True).
    """
    needle = re.sub(r"\s+", " ", stmt_text.lower()).strip()[:80]
    if not needle:
        return 0, True
    best_page, best_score = 0, 0.0
    for page_num, page_text in chunk_pages:
        hay = re.sub(r"\s+", " ", page_text.lower())
        if needle[:50] in hay:
            return page_num, False
        match = difflib.SequenceMatcher(
            None, needle, hay, autojunk=False
        ).find_longest_match(0, len(needle), 0, len(hay))
        score = match.size / max(len(needle), 1)
        if score > best_score:
            best_page, best_score = page_num, score
    if best_score >= _PAGE_ATTRIBUTION_MIN_RATIO:
        return best_page, False
    return 0, True


def _implicit_statement_from_payload(
    ob: dict,
    chunk_pages: list[tuple[int, str]],
    min_confidence: float,
    existing_norm_texts: set[str],
    next_id: int,
) -> ShallStatement | None:
    """Convert one model-emitted obligation dict into a ShallStatement."""
    stmt_text = str(ob.get("statement_text", "")).strip()
    if not stmt_text or len(stmt_text) < 15:
        return None
    confidence = float(ob.get("confidence", 0.5))
    if confidence < min_confidence:
        return None
    # Dedup against existing explicit statements
    if _overlaps_existing(stmt_text, existing_norm_texts):
        return None
    keywords_list = ob.get("keywords", [])
    if isinstance(keywords_list, str):
        keywords_list = [keywords_list]
    page_num, page_uncertain = _attribute_statement_page(stmt_text, chunk_pages)
    return ShallStatement(
        id=next_id,
        page=page_num,
        section=ob.get("section", ""),
        obligation_keyword="(implicit)",
        obligation_type="implicit",
        statement_text=stmt_text,
        subject=ob.get("subject", "(implicit)"),
        requirement=ob.get("requirement", stmt_text),
        context=ob.get("context", ""),
        keywords=keywords_list[:7],
        applies_to=_classify_applicability(stmt_text, ob.get("context", "")),
        confidence=confidence,
        page_uncertain=page_uncertain,
    )


def _append_chunk_statements(
    parsed: dict,
    chunk_pages: list[tuple[int, str]],
    min_confidence: float,
    existing_norm_texts: set[str],
    new_statements: list[ShallStatement],
    next_id: int,
) -> int:
    """Append statements parsed from one chunk payload; returns count added."""
    added = 0
    obligations = parsed.get("obligations", []) if isinstance(parsed, dict) else []
    for ob in obligations:
        if not isinstance(ob, dict):
            continue
        stmt = _implicit_statement_from_payload(
            ob, chunk_pages, min_confidence, existing_norm_texts, next_id + added,
        )
        if stmt is None:
            continue
        new_statements.append(stmt)
        existing_norm_texts.add(_normalize_for_dedup(stmt.statement_text))
        added += 1
    return added


def _implicit_chunk_spans(page_count: int) -> list[tuple[int, int]]:
    """Yield (start, end) index spans of IMPLICIT_CHUNK_SIZE pages.

    WHY advance by CHUNK_SIZE-1: consecutive chunks share one page (parity
    with generic extraction's 1-page overlap) so an obligation split across a
    chunk boundary is seen whole by one of the chunks; _overlaps_existing
    dedups the resulting duplicates.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    while start < page_count:
        end = min(start + IMPLICIT_CHUNK_SIZE, page_count)
        spans.append((start, end))
        start = end - 1 if end < page_count else end
    return spans


def _implicit_chunk_request(
    model: str,
    chunk_pages: list[tuple[int, str]],
    already_lines: list[str],
) -> dict:
    return {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0,
        "messages": [
            {"role": "user", "content": _implicit_prompt_content(chunk_pages, already_lines)}
        ],
    }


def _note_implicit_chunk_failure(
    result: ExtractionResult, exc: Exception, page_lo: int, page_hi: int,
) -> None:
    """Log a chunk failure AND record it in result metadata (never suppress)."""
    retries = exc.retries_used if isinstance(exc, ChunkExtractionError) else 0
    LOGGER.error("  Pages %d–%d: %s", page_lo, page_hi, exc)
    _record_chunk_failure(result, page_lo, page_hi, retries, str(exc), "text_implicit")


def _abort_remaining_implicit(
    result: ExtractionResult, pages_to_process: list[int], from_index: int, reason: str,
) -> None:
    remaining = [idx + 1 for idx in pages_to_process[from_index:]]
    _record_run_abort(result, remaining, reason, "text_implicit")


def _existing_statement_index(
    result: ExtractionResult,
) -> tuple[dict[int, list[ShallStatement]], set[str]]:
    """Index already-extracted statements by page + normalized-text dedup set."""
    by_page: dict[int, list[ShallStatement]] = {}
    for s in result.statements:
        by_page.setdefault(s.page, []).append(s)
    norm_texts = {_normalize_for_dedup(s.statement_text) for s in result.statements}
    return by_page, norm_texts


def _scan_implicit_chunks(
    result: ExtractionResult,
    doc,
    client,
    *,
    model: str,
    pages_to_process: list[int],
    min_confidence: float,
    max_consecutive_failures: int,
    retry_base_delay: float,
) -> list[ShallStatement]:
    """Run the chunked implicit-detection loop, recording failures on result."""
    existing_by_page, existing_norm_texts = _existing_statement_index(result)
    new_statements: list[ShallStatement] = []
    next_id = max((s.id for s in result.statements), default=0) + 1
    consecutive_failures = 0
    for start, end in _implicit_chunk_spans(len(pages_to_process)):
        chunk_indices = pages_to_process[start:end]
        chunk_pages, already_lines = _implicit_chunk_inputs(doc, chunk_indices, existing_by_page)
        if not chunk_pages:
            continue
        page_lo, page_hi = chunk_indices[0] + 1, chunk_indices[-1] + 1
        try:
            parsed, _ = _request_json_with_reprompt(
                client,
                _implicit_chunk_request(model, chunk_pages, already_lines),
                base_delay=retry_base_delay,
            )
        except ExtractionAbortedError as exc:
            _abort_remaining_implicit(result, pages_to_process, start, str(exc))
            break
        except Exception as exc:  # never suppress — log + record in metadata
            _note_implicit_chunk_failure(result, exc, page_lo, page_hi)
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                next_start = end - 1 if end < len(pages_to_process) else end
                _abort_remaining_implicit(result, pages_to_process, next_start,
                                          f"aborted after {consecutive_failures} consecutive chunk failures")
                break
        else:
            consecutive_failures = 0
            added = _append_chunk_statements(
                parsed, chunk_pages, min_confidence,
                existing_norm_texts, new_statements, next_id,
            )
            next_id += added
            LOGGER.info("  Pages %d–%d: found %d implicit obligations", page_lo, page_hi, added)
    return new_statements


def detect_implicit_obligations(
    result: ExtractionResult,
    pdf_path: Path,
    *,
    api_key: str | None = None,
    max_pages: int = 0,
    min_confidence: float = 0.0,
    client=None,
    max_consecutive_failures: int = 3,
    retry_base_delay: float = 1.0,
) -> ExtractionResult:
    """Pass 1c: Detect implicit obligations that lack standard obligation keywords.

    Sends each page chunk to Claude with the already-extracted explicit
    statements, asking it to find binding requirements expressed without
    shall/must/required/prohibited language.  New statements are added with
    obligation_type='implicit' and the confidence score from the LLM.

    Chunk failures are logged AND recorded in result.chunk_failures /
    result.extraction_status (spec §5.4/§5.5).  ``client`` may be injected
    for testing; it must expose ``messages.create``.
    """
    if client is None:
        client = _build_implicit_client(api_key)

    doc = fitz.open(pdf_path)
    pages_to_process = list(range(len(doc)))
    if max_pages and max_pages > 0:
        pages_to_process = pages_to_process[:max_pages]

    LOGGER.info(
        "Pass 1c: detecting implicit obligations across %d pages",
        len(pages_to_process),
    )
    _log_run_estimate("Pass 1c (implicit obligations)", len(pages_to_process))
    started = time.time()

    import os

    new_statements = _scan_implicit_chunks(
        result, doc, client,
        model=os.environ.get("ORACLE_VISION_MODEL", "claude-sonnet-4-6"),
        pages_to_process=pages_to_process,
        min_confidence=min_confidence,
        max_consecutive_failures=max_consecutive_failures,
        retry_base_delay=retry_base_delay,
    )
    doc.close()
    _finalize_implicit_result(result, new_statements, started)
    return result


def _finalize_implicit_result(
    result: ExtractionResult,
    new_statements: list[ShallStatement],
    started: float,
) -> None:
    """Merge new implicit statements into the result and renumber IDs."""
    result.statements.extend(new_statements)
    result.total_statements = len(result.statements)

    implicit_count = sum(1 for s in result.statements if s.obligation_type == "implicit")
    if implicit_count > 0:
        result.by_type["implicit"] = implicit_count

    # Renumber IDs sequentially
    for i, s in enumerate(result.statements, 1):
        s.id = i

    LOGGER.info(
        "Pass 1c complete: %d implicit obligations found, %d chunk failure(s), status=%s (%.1fs)",
        len(new_statements), len(result.chunk_failures),
        result.extraction_status, time.time() - started,
    )


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
                LOGGER.warning(
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
                    LOGGER.warning(
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
            LOGGER.warning("Could not parse LLM JSON payload (prefix=%r)", text[:120])
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
        LOGGER.info("Pass 2 skipped: no statements")
        return result

    total_batches = (total + batch_size - 1) // batch_size
    LOGGER.info(
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
            LOGGER.info(
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
            LOGGER.error("Ollama not available - aborting pass 2")
            break
        except TimeoutError as e:
            failed_count += len(batch)
            consecutive_failures += 1
            LOGGER.error(
                "  Batch %d/%d timeout: %s (%d/%d total)",
                batch_num,
                total_batches,
                e,
                classified_count,
                total,
            )
            if consecutive_failures >= max_consecutive_failures:
                LOGGER.error(
                    "Stopping pass 2 after %d consecutive failures.",
                    consecutive_failures,
                )
                break
        except Exception as e:
            failed_count += len(batch)
            consecutive_failures += 1
            LOGGER.error(
                "  Batch %d/%d failed: %s (%d/%d total)",
                batch_num,
                total_batches,
                e,
                classified_count,
                total,
            )
            if consecutive_failures >= max_consecutive_failures:
                LOGGER.error(
                    "Stopping pass 2 after %d consecutive failures.",
                    consecutive_failures,
                )
                break

    LOGGER.info(
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

    LOGGER.info("Saved: %s", json_path)
    LOGGER.info("Saved: %s", summary_path)
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
    parser.add_argument(
        "--implicit",
        action="store_true",
        help="Run Pass 1c: detect implicit obligations without keyword markers",
    )
    parser.add_argument(
        "--implicit-min-confidence",
        type=float,
        default=0.0,
        help="Minimum confidence for implicit obligations (default: 0.0, keep all)",
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
        LOGGER.info("Filtered to mandatory/prohibition: %d -> %d", before, result.total_statements)

    # Always checkpoint pass 1 immediately so caller gets JSON even if enrichment is slow.
    checkpoint = save_results(result, output_dir)
    LOGGER.info("Pass 1 checkpoint written: %s", checkpoint["json"])

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
        LOGGER.info("Sonnet enrichment checkpoint written")

    # Implicit obligation detection (Pass 1c)
    if args.implicit:
        result = detect_implicit_obligations(
            result,
            pdf_path,
            api_key=args.api_key,
            max_pages=args.max_pages,
            min_confidence=args.implicit_min_confidence,
        )
        save_results(result, output_dir)
        LOGGER.info("Implicit obligation detection checkpoint written")

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
