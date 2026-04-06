#!/usr/bin/env python3
"""
Adapt shall-extractor JSON into a GPCM-style requirement rule pack.

The adapter keeps the core extractor fields, enriches them from the source
PDF, strips repeated boilerplate, and emits a self-describing rule pack JSON.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


TAG_RE = re.compile(r"\[(MPR|FCR)\s+(\d+)\]", re.IGNORECASE)
TAG_VALUE_RE = re.compile(r"\b(MPR|FCR)\s+(\d+)\b", re.IGNORECASE)
SECTION_RE = re.compile(r"^\d+(?:\.\d+)*(?:[a-z](?:\(\d+\))?)?$", re.IGNORECASE)
OBLIGATION_RE = re.compile(
    r"\b(shall not|shall|must not|must|required|may not)\b", re.IGNORECASE
)
RATIONALE_RE = re.compile(r"\[Rationale:\s*(.*?)\]", re.IGNORECASE | re.DOTALL)
HEADER_PATTERNS = (
    re.compile(r"^NASA-STD-", re.IGNORECASE),
    re.compile(r"^APPROVED FOR PUBLIC RELEASE", re.IGNORECASE),
    re.compile(r"^Controlled by:", re.IGNORECASE),
    re.compile(r"^\d+\s+of\s+\d+$"),
    re.compile(r"^Section$", re.IGNORECASE),
    re.compile(r"^Section Title$", re.IGNORECASE),
    re.compile(r"^Requirement Statement$", re.IGNORECASE),
    re.compile(r"^Requirement in this Standard$", re.IGNORECASE),
    re.compile(r"^Justification$", re.IGNORECASE),
    re.compile(r"^Applicable\s+\(Yes or No\)$", re.IGNORECASE),
    re.compile(r"^If No, Enter Rationale$", re.IGNORECASE),
    re.compile(r"^Description$", re.IGNORECASE),
)
META_REQUIREMENT_PATTERNS = (
    re.compile(r"\bword\s+[\"“]?shall", re.IGNORECASE),
    re.compile(r"\bdenotes expected outcome\b", re.IGNORECASE),
    re.compile(r"\bthese requirements use the word\b", re.IGNORECASE),
    re.compile(r"\brecommended but not required\b", re.IGNORECASE),
    re.compile(r"\bat the time of publication\b", re.IGNORECASE),
)

KEYWORD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("materials", re.compile(r"\bmaterials?\b", re.IGNORECASE)),
    ("processes", re.compile(r"\bprocess(?:es)?\b", re.IGNORECASE)),
    ("hardware", re.compile(r"\bhardware\b", re.IGNORECASE)),
    ("spaceflight", re.compile(r"\bspaceflight\b", re.IGNORECASE)),
    ("testing", re.compile(r"\btest(?:ing|ed|s)?\b", re.IGNORECASE)),
    ("inspection", re.compile(r"\binspect(?:ion|ed|ions)?\b", re.IGNORECASE)),
    ("verification", re.compile(r"\bverif(?:y|ies|ication)\b", re.IGNORECASE)),
    ("compliance", re.compile(r"\bcompli(?:ance|es|ed|y)\b", re.IGNORECASE)),
    ("corrosion", re.compile(r"\bcorrosi(?:on|ve)\b", re.IGNORECASE)),
    ("hydrogen", re.compile(r"\bhydrogen\b", re.IGNORECASE)),
    ("oxygen", re.compile(r"\boxygen\b", re.IGNORECASE)),
    ("fracture", re.compile(r"\bfracture\b", re.IGNORECASE)),
    ("welding", re.compile(r"\bweld(?:ing|ed|s)?\b", re.IGNORECASE)),
    ("bonding", re.compile(r"\bbond(?:ed|ing|s)?\b", re.IGNORECASE)),
    ("coating", re.compile(r"\bcoatings?\b", re.IGNORECASE)),
    ("contamination", re.compile(r"\bcontamin(?:ation|ants?)\b", re.IGNORECASE)),
    ("flammability", re.compile(r"\bflammab(?:ility|le)\b", re.IGNORECASE)),
    ("embrittlement", re.compile(r"\bembrittlement\b", re.IGNORECASE)),
    ("MUA", re.compile(r"\bMUAs?\b", re.IGNORECASE)),
    ("MIUL", re.compile(r"\bMIUL\b", re.IGNORECASE)),
    ("NDE", re.compile(r"\bNDE\b", re.IGNORECASE)),
    ("COTS", re.compile(r"\bCOTS\b", re.IGNORECASE)),
    ("drawing", re.compile(r"\bdrawings?\b", re.IGNORECASE)),
    ("specification", re.compile(r"\bspecifications?\b", re.IGNORECASE)),
    ("manufacturing", re.compile(r"\bmanufactur(?:e|ing|ed)\b", re.IGNORECASE)),
    ("qualification", re.compile(r"\bqualif(?:ication|y|ied)\b", re.IGNORECASE)),
    ("traceability", re.compile(r"\btraceability\b", re.IGNORECASE)),
]

APPLIES_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("human_rated", re.compile(r"\bhuman[- ]rated\b", re.IGNORECASE)),
    ("mission_critical", re.compile(r"\bmission[- ]critical\b", re.IGNORECASE)),
    ("oxygen_systems", re.compile(r"\boxygen\b", re.IGNORECASE)),
    ("hydrogen_systems", re.compile(r"\bhydrogen\b", re.IGNORECASE)),
    ("fracture_critical", re.compile(r"\bfracture\b", re.IGNORECASE)),
    ("composite_bonded", re.compile(r"\b(composite|bonded)\b", re.IGNORECASE)),
    ("metallic", re.compile(r"\bmetallic\b", re.IGNORECASE)),
]

VISION_MODEL = "claude-sonnet-4-5-20250929"
CONTINUATION_TAIL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "by",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
CONTINUATION_START_WORDS = {
    "accordance",
    "advice",
    "all",
    "applications",
    "company",
    "containment",
    "coordinating",
    "design",
    "engineering",
    "first-article",
    "flammability",
    "following",
    "hardware",
    "historical",
    "maintained",
    "materials",
    "mechanical",
    "metallurgically",
    "mission-critical",
    "most",
    "nonconforming",
    "offgassing",
    "particular",
    "potential",
    "prevent",
    "process",
    "requirements",
    "separate",
    "stabilized",
    "suitable",
    "tracking",
    "withstanding",
}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize_line(text: str) -> str:
    return normalize_space(text).lower()


def line_is_header(line: str) -> bool:
    text = normalize_space(line)
    if not text:
        return True
    if text.isdigit():
        return True
    return any(pattern.search(text) for pattern in HEADER_PATTERNS)


def make_keyword_prefix(text: str, words: int = 6) -> str:
    return " ".join(normalize_line(text).split()[:words])


def looks_like_meta_requirement(text: str) -> bool:
    normalized = normalize_space(text)
    return any(pattern.search(normalized) for pattern in META_REQUIREMENT_PATTERNS)


def extract_tag(text: str) -> str | None:
    match = TAG_RE.search(text or "")
    if not match:
        return None
    return f"{match.group(1).upper()} {match.group(2)}"


def normalize_source_tag(text: str) -> str | None:
    tagged = extract_tag(text)
    if tagged:
        return tagged
    match = TAG_VALUE_RE.search(text or "")
    if not match:
        return None
    return f"{match.group(1).upper()} {match.group(2)}"


def strip_leading_tag(text: str) -> str:
    return normalize_space(TAG_RE.sub("", text or "", count=1))


def extract_tag_number(tag: str | None) -> int:
    if not tag:
        return 0
    match = re.search(r"(\d+)$", tag)
    return int(match.group(1)) if match else 0


def build_page_bundle(pdf_path: Path) -> tuple[list[dict[str, Any]], set[str], dict[str, str]]:
    doc = fitz.open(pdf_path)
    raw_pages: list[dict[str, Any]] = []
    line_counts: Counter[str] = Counter()

    for page_index, page in enumerate(doc):
        raw_text = page.get_text("text")
        raw_lines = [normalize_space(line) for line in raw_text.splitlines()]
        for line in raw_lines:
            normalized = normalize_line(line)
            if normalized and not line_is_header(line):
                line_counts[normalized] += 1
        raw_pages.append(
            {
                "page": page_index + 1,
                "raw_text": raw_text,
                "raw_lines": raw_lines,
            }
        )

    frequent_lines = {line for line, count in line_counts.items() if count >= 5}
    pages: list[dict[str, Any]] = []
    inline_rationales: dict[str, str] = {}

    for page in raw_pages:
        cleaned_lines = [
            line
            for line in page["raw_lines"]
            if normalize_line(line) not in frequent_lines and not line_is_header(line)
        ]
        raw_text = page["raw_text"]
        for match in RATIONALE_RE.finditer(raw_text):
            rationale = normalize_space(match.group(1))
            if not rationale:
                continue
            prior_tags = list(TAG_RE.finditer(raw_text[: match.start()]))
            if prior_tags:
                tag_match = prior_tags[-1]
                inline_rationales[f"{tag_match.group(1).upper()} {tag_match.group(2)}"] = rationale
        pages.append(
            {
                "page": page["page"],
                "raw_text": raw_text,
                "lines": cleaned_lines,
                "norm_text": normalize_line(" ".join(cleaned_lines)),
            }
        )

    doc.close()
    return pages, frequent_lines, inline_rationales


def build_tag_blocks(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tag_blocks: list[dict[str, Any]] = []
    for page in pages:
        lines = page["lines"]
        index = 0
        while index < len(lines):
            match = TAG_RE.search(lines[index])
            if not match:
                index += 1
                continue

            section = ""
            for probe in range(max(0, index - 3), index):
                if SECTION_RE.match(lines[probe]):
                    section = lines[probe]

            collected = [lines[index]]
            cursor = index + 1
            while cursor < len(lines):
                line = lines[cursor]
                if TAG_RE.search(line):
                    break
                if SECTION_RE.match(line) and len(collected) > 1:
                    break
                collected.append(line)
                cursor += 1

            block_text = normalize_space(" ".join(collected))
            if not OBLIGATION_RE.search(strip_leading_tag(block_text)):
                index = cursor
                continue

            tag_blocks.append(
                {
                    "tag": f"{match.group(1).upper()} {match.group(2)}",
                    "page": page["page"],
                    "section": section,
                    "text": block_text,
                }
            )
            index = cursor
    return tag_blocks


def candidate_pages(
    statement: dict[str, Any],
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = normalize_space(statement.get("statement_text", ""))
    if not text:
        return []
    prefix = make_keyword_prefix(text)
    section = normalize_space(statement.get("section", ""))
    statement_page = int(statement.get("page") or 0)

    out: list[dict[str, Any]] = []
    for page in pages:
        if page["page"] == statement_page:
            out.append(page)
            continue
        if section and section in page["raw_text"]:
            out.append(page)
            continue
        if prefix and prefix in page["norm_text"]:
            out.append(page)
    if out:
        return out
    return pages


def score_candidate(target: str, candidate: str) -> float:
    target_norm = normalize_line(target)
    candidate_norm = normalize_line(candidate)
    if not target_norm or not candidate_norm:
        return 0.0
    if target_norm in candidate_norm or candidate_norm in target_norm:
        ratio = 1.0
    else:
        ratio = SequenceMatcher(None, target_norm, candidate_norm).ratio()
    length_penalty = abs(len(target_norm) - len(candidate_norm)) / max(len(target_norm), 1)
    return ratio - (length_penalty * 0.03)


def find_requirement_match(
    target_text: str,
    page: dict[str, Any],
) -> tuple[int, int, float] | None:
    lines = page["lines"]
    target_norm = normalize_space(target_text)
    prefix = make_keyword_prefix(target_text)
    best: tuple[int, int, float] | None = None

    for start in range(len(lines)):
        preview = normalize_line(" ".join(lines[start : start + 2]))
        if prefix and prefix not in preview and prefix not in page["norm_text"]:
            continue

        joined = ""
        for end in range(start, min(len(lines), start + 12)):
            joined = normalize_space(f"{joined} {lines[end]}")
            if len(joined) < 30:
                continue
            if not OBLIGATION_RE.search(joined):
                continue

            score = score_candidate(target_norm, joined)
            if score < 0.78:
                continue

            if best is None or score > best[2]:
                best = (start, end, score)

    return best


def clean_justification(text: str) -> str:
    cleaned = normalize_space(text)
    cleaned = re.sub(r"^\[?Rationale:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.rstrip("]")
    cleaned = normalize_space(cleaned)
    return cleaned


def extract_following_justification(lines: list[str], end: int) -> str:
    collected: list[str] = []
    for index in range(end + 1, len(lines)):
        line = lines[index]
        if not line:
            if collected:
                break
            continue
        if TAG_RE.search(line):
            break
        if SECTION_RE.match(line) and collected:
            break
        collected.append(line)
        if len(" ".join(collected)) >= 1800:
            break

    return clean_justification(" ".join(collected))


def extract_block_tag(lines: list[str], start: int, end: int) -> str | None:
    nearby = " ".join(lines[max(0, start - 1) : min(len(lines), end + 2)])
    return extract_tag(nearby)


def locate_source_block(
    statement: dict[str, Any],
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    target_text = normalize_space(statement.get("statement_text", ""))
    best_match: dict[str, Any] | None = None

    for page in candidate_pages(statement, pages):
        match = find_requirement_match(target_text, page)
        if not match:
            continue
        start, end, score = match
        tag = extract_block_tag(page["lines"], start, end)
        justification = extract_following_justification(page["lines"], end)
        block_text = normalize_space(" ".join(page["lines"][start : end + 1]))
        candidate = {
            "page": page["page"],
            "score": score,
            "tag": tag,
            "justification": justification,
            "block_text": block_text,
        }
        if best_match is None or candidate["score"] > best_match["score"]:
            best_match = candidate

    return best_match or {
        "page": statement.get("page"),
        "score": 0.0,
        "tag": None,
        "justification": "",
        "block_text": target_text,
    }


def preprocess_statements(statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    processed: list[dict[str, Any]] = []
    for statement in statements:
        text = normalize_space(statement.get("statement_text", ""))
        if not text:
            continue
        processed.append(
            {
                "raw": statement,
                "norm_text": normalize_line(strip_leading_tag(text)),
                "prefix": make_keyword_prefix(strip_leading_tag(text)),
            }
        )
    return processed


def best_statement_for_block(
    block: dict[str, Any],
    statements: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    tagless_block = strip_leading_tag(block["text"])
    prefix = make_keyword_prefix(tagless_block)
    section = normalize_space(block.get("section", ""))
    candidates = [
        item
        for item in statements
        if (prefix and prefix in item["norm_text"])
        or (section and normalize_space(item["raw"].get("section", "")) == section)
        or int(item["raw"].get("page") or 0) == int(block["page"])
    ]
    if not candidates:
        candidates = statements

    best_statement: dict[str, Any] | None = None
    best_score = 0.0
    for item in candidates:
        score = score_candidate(tagless_block, item["raw"]["statement_text"])
        if score > best_score:
            best_statement = item["raw"]
            best_score = score
    return best_statement, best_score


def extract_justification_from_block_text(block_text: str, statement_text: str) -> str:
    text = strip_leading_tag(block_text)
    target = strip_leading_tag(statement_text)
    lower_text = text.lower()
    lower_target = target.lower()
    if lower_target and lower_target in lower_text:
        start = lower_text.find(lower_target)
        remainder = text[start + len(target) :]
        return clean_justification(remainder)
    return ""


def derive_shall_text(block_text: str, statement_text: str, justification: str) -> str:
    block_requirement = strip_leading_tag(block_text)
    if justification:
        lower_block = block_requirement.lower()
        lower_justification = justification.lower()
        if lower_justification in lower_block:
            split_at = lower_block.find(lower_justification)
            candidate = normalize_space(block_requirement[:split_at]).rstrip(".")
            if candidate:
                return candidate
    return strip_leading_tag(statement_text)


def split_subject_requirement(shall_text: str) -> tuple[str, str]:
    match = OBLIGATION_RE.search(shall_text)
    if not match:
        return "", normalize_space(shall_text)
    subject = normalize_space(shall_text[: match.start()]).rstrip(",")
    requirement = normalize_space(shall_text[match.end() :]).lstrip(",")
    if len(subject) < 2:
        subject = "(implicit)"
    return subject, requirement


def _normalized_requirement_id(value: Any) -> str:
    """Emit schema-compliant requirement ids in the final rule pack."""
    if value is None:
        return ""
    return str(value)


def build_tagged_requirements(
    statements: list[dict[str, Any]],
    tag_blocks: list[dict[str, Any]],
    frequent_lines: set[str],
    inline_rationales: dict[str, str],
) -> list[dict[str, Any]]:
    processed_statements = preprocess_statements(statements)
    blocks_by_tag: dict[str, list[dict[str, Any]]] = {}
    for block in tag_blocks:
        blocks_by_tag.setdefault(block["tag"], []).append(block)

    requirements: list[dict[str, Any]] = []
    for tag, blocks in sorted(blocks_by_tag.items(), key=lambda item: extract_tag_number(item[0])):
        best_requirement: dict[str, Any] | None = None
        best_score = 0.0

        for block in blocks:
            statement, score = best_statement_for_block(block, processed_statements)
            if not statement:
                continue
            if is_boilerplate_statement(statement.get("statement_text", ""), frequent_lines):
                continue
            if looks_like_meta_requirement(statement.get("statement_text", "")):
                continue

            shall_text = strip_leading_tag(statement.get("statement_text", ""))
            justification = extract_justification_from_block_text(block["text"], shall_text)
            if not justification and tag in inline_rationales:
                justification = clean_justification(inline_rationales[tag])
            shall_text = derive_shall_text(block["text"], shall_text, justification)
            subject, requirement_text = split_subject_requirement(shall_text)

            if justification:
                score += 0.1
            if block.get("section"):
                score += 0.05

            context = normalize_space(statement.get("context", ""))
            requirement = {
                "id": _normalized_requirement_id(statement.get("id")),
                "source_tag": tag,
                "section": normalize_space(statement.get("section", "")) or normalize_space(block.get("section", "")),
                "shall_text": shall_text,
                "subject": subject,
                "requirement": requirement_text,
                "context": context,
                "page": block["page"],
                "justification": justification,
                "keywords": extract_keywords(shall_text, context, justification),
                "applies_to": classify_applies_to(shall_text, context, justification),
                "mua_relevant": bool(re.search(r"\bMUA\b", shall_text, re.IGNORECASE)),
            }

            if best_requirement is None or score > best_score:
                best_requirement = requirement
                best_score = score

        if best_requirement is not None:
            requirements.append(best_requirement)

    return requirements


def extract_keywords(statement_text: str, context_text: str, justification: str) -> list[str]:
    pool = " ".join([statement_text, context_text, justification])
    found: list[tuple[int, str]] = []

    for keyword, pattern in KEYWORD_PATTERNS:
        match = pattern.search(pool)
        if match:
            found.append((match.start(), keyword))

    found.sort(key=lambda item: item[0])
    ordered = [keyword for _, keyword in found]
    deduped: list[str] = []
    for keyword in ordered:
        if keyword not in deduped:
            deduped.append(keyword)

    return deduped[:5]


def classify_applies_to(statement_text: str, context_text: str, justification: str) -> list[str]:
    pool = " ".join([statement_text, context_text, justification])
    matches = [
        value for value, pattern in APPLIES_RULES if pattern.search(pool)
    ]
    if not matches:
        return ["all_programs"]

    deduped: list[str] = []
    for value in matches:
        if value not in deduped:
            deduped.append(value)
    return deduped


def is_boilerplate_statement(text: str, frequent_lines: set[str]) -> bool:
    normalized = normalize_line(text)
    return normalized in frequent_lines


def enrich_statement(
    statement: dict[str, Any],
    pages: list[dict[str, Any]],
    frequent_lines: set[str],
    inline_rationales: dict[str, str],
) -> dict[str, Any] | None:
    shall_text = normalize_space(statement.get("statement_text", ""))
    if not shall_text:
        return None
    if is_boilerplate_statement(shall_text, frequent_lines):
        return None
    if looks_like_meta_requirement(shall_text):
        return None

    source = locate_source_block(statement, pages)
    source_tag = source["tag"]
    justification = source["justification"]
    if not justification and source_tag and source_tag in inline_rationales:
        justification = clean_justification(inline_rationales[source_tag])

    context = normalize_space(statement.get("context", ""))
    keywords = extract_keywords(shall_text, context, justification)
    applies_to = classify_applies_to(shall_text, context, justification)
    mua_relevant = bool(re.search(r"\bMUA\b", shall_text, re.IGNORECASE))

    return {
        "id": _normalized_requirement_id(statement.get("id")),
        "source_tag": source_tag,
        "section": normalize_space(statement.get("section", "")),
        "shall_text": shall_text,
        "subject": normalize_space(statement.get("subject", "")),
        "requirement": normalize_space(statement.get("requirement", "")),
        "context": context,
        "page": source.get("page") or statement.get("page"),
        "justification": justification,
        "keywords": keywords,
        "applies_to": applies_to,
        "mua_relevant": mua_relevant,
    }


def dedupe_requirements(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}

    for requirement in requirements:
        key = normalize_line(requirement["shall_text"])
        score = 0
        if requirement.get("section"):
            score += 2
        if requirement.get("source_tag"):
            score += 2
        if requirement.get("justification"):
            score += 4
        if requirement.get("applies_to") != ["all_programs"]:
            score += 1
        requirement["_score"] = score

        current = best_by_key.get(key)
        if current is None or requirement["_score"] > current["_score"]:
            best_by_key[key] = requirement

    deduped = list(best_by_key.values())
    for requirement in deduped:
        requirement.pop("_score", None)

    deduped.sort(
        key=lambda item: (
            extract_tag_number(item.get("source_tag")),
            normalize_space(item.get("section", "")),
            int(item.get("id") or 0),
        )
    )
    return deduped


def parse_model_json(response_text: str) -> dict[str, Any]:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[start:end]).strip()

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return {"error": "No JSON object found in response", "raw_response": response_text}

    json_str = text[start_idx : end_idx + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        return {
            "error": f"JSON parse error: {exc}",
            "raw_response": response_text,
        }


def split_leading_sentence(text: str) -> tuple[str, str]:
    cleaned = normalize_space(text)
    if not cleaned:
        return "", ""

    match = re.search(r"(?<=[.!?])\s+", cleaned)
    if not match:
        return cleaned, ""

    lead = normalize_space(cleaned[: match.start()])
    remainder = normalize_space(cleaned[match.end() :])
    return lead, remainder


def repair_continuation_from_justification(requirement: dict[str, Any]) -> bool:
    shall_text = normalize_space(requirement.get("shall_text", ""))
    justification = normalize_space(requirement.get("justification", ""))
    if not shall_text or not justification:
        return False

    last_word = re.sub(r"[^A-Za-z-]+", "", shall_text.split()[-1]).lower() if shall_text.split() else ""
    first_word = re.sub(r"[^A-Za-z-]+", "", justification.split()[0]).lower() if justification.split() else ""
    starts_like_continuation = justification[:1].islower() or first_word in CONTINUATION_START_WORDS
    ends_like_continuation = shall_text.endswith(",") or last_word in CONTINUATION_TAIL_WORDS
    if not (starts_like_continuation and ends_like_continuation):
        return False

    lead, remainder = split_leading_sentence(justification)
    if not lead:
        return False

    joiner = "" if shall_text.endswith((",", "(", "/")) else " "
    new_shall = normalize_space(f"{shall_text}{joiner}{lead}")
    if new_shall == shall_text:
        return False

    requirement["shall_text"] = new_shall
    subject, requirement_text = split_subject_requirement(new_shall)
    requirement["subject"] = subject
    requirement["requirement"] = requirement_text
    requirement["justification"] = remainder
    requirement["keywords"] = extract_keywords(
        requirement.get("shall_text", ""),
        requirement.get("context", ""),
        requirement.get("justification", ""),
    )
    requirement["applies_to"] = classify_applies_to(
        requirement.get("shall_text", ""),
        requirement.get("context", ""),
        requirement.get("justification", ""),
    )
    requirement["mua_relevant"] = bool(
        re.search(r"\bMUA\b", requirement.get("shall_text", ""), re.IGNORECASE)
    )
    return True


def vision_repair_reasons(requirement: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    shall_text = normalize_space(requirement.get("shall_text", ""))
    justification = normalize_space(requirement.get("justification", ""))
    last_word = re.sub(r"[^A-Za-z-]+", "", shall_text.split()[-1]).lower() if shall_text.split() else ""

    if not justification:
        reasons.append("missing_justification")
    if "[" in shall_text or "Rationale:" in shall_text:
        reasons.append("inline_rationale")
    if shall_text.endswith(","):
        reasons.append("trailing_comma")
    if shall_text.endswith("Selection, Control, and") or shall_text.endswith("Materials and"):
        reasons.append("truncated_phrase")
    if last_word in CONTINUATION_TAIL_WORDS and len(shall_text) >= 60:
        reasons.append("tail_word")

    return reasons


def render_page_png(doc: fitz.Document, page_number: int, dpi: int) -> str:
    page = doc[page_number - 1]
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return base64.b64encode(pix.tobytes("png")).decode("utf-8")


def build_vision_prompt(
    standard_id: str,
    page_number: int,
    page_targets: list[dict[str, Any]],
) -> str:
    lines = [
        f"Extract the full requirement statement and justification from {standard_id}.",
        f"The first image is page {page_number}; a second image may be page {page_number + 1} for row continuation.",
        "Only return the requested requirement tags.",
        "",
        "Return STRICT JSON with this shape:",
        '{',
        '  "requirements": [',
        '    {',
        '      "source_tag": "MPR 22",',
        '      "section": "3.2.4",',
        '      "shall_text": "Programs shall apply ...",',
        '      "justification": "..."',
        "    }",
        "  ]",
        "}",
        "",
        "Rules:",
        "- Only include the requested tags.",
        "- `shall_text` must contain the full requirement statement only, without the bracketed tag.",
        "- Put only the rationale/justification text in `justification`.",
        "- If a table row wraps across lines or onto the next page, reconstruct the complete statement.",
        "- Preserve subsection letters and numbered sub-items when they belong to the requirement statement.",
        "- Do not invent text. Use an empty string if the justification is not visible.",
        "- Return valid JSON only. No markdown fences.",
        "",
        "Requested tags and current extraction hints:",
    ]

    for target in page_targets:
        lines.append(
            f'- {target["source_tag"]} | section="{target.get("section", "")}" '
            f'| shall_text="{target.get("shall_text", "")}" '
            f'| justification="{target.get("justification", "")}" '
            f'| repair_reasons={", ".join(target["_vision_reasons"])}'
        )

    return "\n".join(lines)


def page_window_for_tag(page_text: str, tag: str, before: int = 4, after: int = 14) -> str:
    lines = [normalize_space(line) for line in page_text.splitlines()]
    tag_re = re.compile(
        rf"\[{re.escape(tag.split()[0])}\s+{re.escape(tag.split()[1])}\]",
        re.IGNORECASE,
    )
    windows: list[str] = []
    for index, line in enumerate(lines):
        if tag_re.search(line):
            start = max(0, index - before)
            end = min(len(lines), index + after)
            windows.append("\n".join(lines[start:end]))
    return "\n\n".join(windows)


def local_tag_window(page_text: str, tag: str, after: int = 8) -> str:
    return page_window_for_tag(page_text, tag, before=0, after=after)


def select_tag_pages_for_vision(doc: fitz.Document, tag: str, max_pages: int = 3) -> tuple[list[int], int | None]:
    tag_re = re.compile(
        rf"\[{re.escape(tag.split()[0])}\s+{re.escape(tag.split()[1])}\]",
        re.IGNORECASE,
    )
    candidates: list[tuple[int, int]] = []
    primary_page: int | None = None

    for page_index, page in enumerate(doc):
        raw_text = page.get_text("text")
        if not tag_re.search(raw_text):
            continue

        window = page_window_for_tag(raw_text, tag)
        local_window = local_tag_window(raw_text, tag)
        score = 0
        if OBLIGATION_RE.search(local_window):
            score += 6
            if primary_page is None and len(normalize_space(local_window)) >= 60:
                primary_page = page_index + 1
        if "[Rationale:" in raw_text or "Rationale:" in window:
            score += 8
        if "Table of Contents" in raw_text or "Description" in window and "Section" in window:
            score -= 8
        if "shall" in local_window.lower():
            score += 2
        if page_index + 1 > 20:
            score += 1

        candidates.append((score, page_index + 1))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected = [page for _, page in candidates[:max_pages]]
    return selected, primary_page


def maybe_add_continuation_pages(doc: fitz.Document, tag: str, pages: list[int]) -> list[int]:
    expanded = list(pages)
    for page_number in list(pages):
        page_text = doc[page_number - 1].get_text("text")
        local_window = normalize_space(local_tag_window(page_text, tag, after=10))
        if not local_window:
            continue
        if local_window[-1] in ".!?]":
            continue
        next_page = page_number + 1
        if next_page <= len(doc) and next_page not in expanded:
            expanded.append(next_page)
    return expanded


def load_6016_yaml_shall_fallbacks() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[1]
    yaml_path = repo_root / "mira" / "compliance" / "data" / "mprs_6016c.yaml"
    if not yaml_path.exists():
        return {}

    text = yaml_path.read_text(encoding="utf-8")
    entry_re = re.compile(
        r"^\s*-\s*mpr_number:\s*(\d+)\s*$([\s\S]*?)(?=^\s*-\s*mpr_number:\s*\d+\s*$|\Z)",
        re.MULTILINE,
    )
    shall_re = re.compile(r'^\s*shall_text:\s*"([^"]+)"', re.MULTILINE)
    out: dict[str, str] = {}
    for match in entry_re.finditer(text):
        number = int(match.group(1))
        entry_text = match.group(2)
        shall_match = shall_re.search(entry_text)
        if shall_match:
            out[f"MPR {number}"] = normalize_space(shall_match.group(1))
    return out


def apply_local_6016_shall_fallbacks(requirements: list[dict[str, Any]], standard_id: str) -> int:
    if standard_id.upper() != "NASA-STD-6016C":
        return 0

    fallbacks = load_6016_yaml_shall_fallbacks()
    repaired = 0
    for requirement in requirements:
        tag = requirement.get("source_tag")
        fallback = fallbacks.get(tag or "")
        if not fallback:
            continue

        current = normalize_space(requirement.get("shall_text", ""))
        if not current.endswith((" of.", " for.")):
            continue

        requirement["shall_text"] = fallback
        subject, requirement_text = split_subject_requirement(fallback)
        requirement["subject"] = subject
        requirement["requirement"] = requirement_text
        requirement["keywords"] = extract_keywords(
            requirement.get("shall_text", ""),
            requirement.get("context", ""),
            requirement.get("justification", ""),
        )
        requirement["applies_to"] = classify_applies_to(
            requirement.get("shall_text", ""),
            requirement.get("context", ""),
            requirement.get("justification", ""),
        )
        requirement["mua_relevant"] = bool(
            re.search(r"\bMUA\b", requirement.get("shall_text", ""), re.IGNORECASE)
        )
        repaired += 1
    return repaired


def build_targeted_tag_prompt(
    standard_id: str,
    requirement: dict[str, Any],
    pages: list[int],
) -> str:
    return "\n".join(
        [
            f"Extract one requirement record for {requirement['source_tag']} from {standard_id}.",
            f"Attached pages may include the main requirement page, an appendix rationale page, or a table-of-contents/reference hit: {', '.join(str(page) for page in pages)}.",
            "Combine them into one canonical record.",
            "",
            "Return STRICT JSON only:",
            "{",
            '  "source_tag": "MPR 12",',
            '  "section": "4.1.1.1",',
            '  "shall_text": "Programs shall apply ...",',
            '  "justification": "..."',
            "}",
            "",
            "Rules:",
            "- Extract only the requested tag.",
            "- Use the full requirement statement as `shall_text`, without the bracketed tag.",
            "- If one page contains the requirement and another page contains appendix rationale text, combine them.",
            "- If a later appendix page repeats a shortened requirement row followed by narrative text, treat the narrative text as the justification.",
            "- If a page is only table of contents or a cross-reference mention, ignore it.",
            "- Keep standard titles complete when visible; do not leave a trailing fragment like 'Requirements for.' unless that is all that is visible.",
            "- Return an empty string for `justification` only if no actual rationale is visible on any attached page.",
            "- Return valid JSON only. No markdown fences.",
            "",
            "Current extraction hint:",
            f"section={requirement.get('section', '')}",
            f"shall_text={requirement.get('shall_text', '')}",
            f"justification={requirement.get('justification', '')}",
        ]
    )


def apply_vision_repairs(
    requirements: list[dict[str, Any]],
    source_pdf: Path,
    standard_id: str,
    model: str,
    dpi: int,
) -> tuple[list[dict[str, Any]], int]:
    targets_by_page: dict[int, list[dict[str, Any]]] = {}
    for requirement in requirements:
        reasons = vision_repair_reasons(requirement)
        if not reasons:
            continue
        requirement["_vision_reasons"] = reasons
        targets_by_page.setdefault(int(requirement["page"]), []).append(requirement)

    if not targets_by_page:
        return requirements, 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required when --use-sonnet-vision is enabled")

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package is required when --use-sonnet-vision is enabled") from exc

    client = Anthropic(api_key=api_key)
    doc = fitz.open(source_pdf)
    by_tag = {
        requirement.get("source_tag"): requirement
        for requirement in requirements
        if requirement.get("source_tag")
    }
    repaired_tags: set[str] = set()

    try:
        total_pages = len(doc)
        for page_number in sorted(targets_by_page):
            page_targets = targets_by_page[page_number]
            prompt = build_vision_prompt(standard_id, page_number, page_targets)
            content: list[dict[str, Any]] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": render_page_png(doc, page_number, dpi),
                    },
                },
                {
                    "type": "text",
                    "text": f"[Page {page_number}]",
                },
            ]
            if page_number < total_pages:
                content.extend(
                    [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": render_page_png(doc, page_number + 1, dpi),
                            },
                        },
                        {
                            "type": "text",
                            "text": f"[Page {page_number + 1}]",
                        },
                    ]
                )
            content.append({"type": "text", "text": prompt})

            response = client.messages.create(
                model=model,
                max_tokens=4096,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            )

            if not response.content:
                continue

            parsed = parse_model_json(response.content[0].text)
            for candidate in parsed.get("requirements", []):
                tag = normalize_source_tag(candidate.get("source_tag", ""))
                if not tag or tag not in by_tag:
                    continue

                requirement = by_tag[tag]
                shall_text = normalize_space(candidate.get("shall_text", ""))
                justification = clean_justification(candidate.get("justification", ""))
                section = normalize_space(candidate.get("section", ""))

                if shall_text:
                    requirement["shall_text"] = shall_text
                    subject, requirement_text = split_subject_requirement(shall_text)
                    requirement["subject"] = subject
                    requirement["requirement"] = requirement_text
                    repaired_tags.add(tag)

                if section:
                    requirement["section"] = section
                    repaired_tags.add(tag)

                if justification:
                    requirement["justification"] = justification
                    repaired_tags.add(tag)

                requirement["keywords"] = extract_keywords(
                    requirement.get("shall_text", ""),
                    requirement.get("context", ""),
                    requirement.get("justification", ""),
                )
                requirement["applies_to"] = classify_applies_to(
                    requirement.get("shall_text", ""),
                    requirement.get("context", ""),
                    requirement.get("justification", ""),
                )
                requirement["mua_relevant"] = bool(
                    re.search(r"\bMUA\b", requirement.get("shall_text", ""), re.IGNORECASE)
                )
    finally:
        doc.close()
        for requirement in requirements:
            requirement.pop("_vision_reasons", None)

    return requirements, len(repaired_tags)


def apply_targeted_tag_vision_repairs(
    requirements: list[dict[str, Any]],
    source_pdf: Path,
    standard_id: str,
    model: str,
    dpi: int,
) -> tuple[list[dict[str, Any]], int]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required when --use-sonnet-vision is enabled")

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package is required when --use-sonnet-vision is enabled") from exc

    doc = fitz.open(source_pdf)
    client = Anthropic(api_key=api_key)
    repaired = 0

    try:
        for requirement in requirements:
            reasons = vision_repair_reasons(requirement)
            if not reasons:
                continue

            tag = requirement.get("source_tag")
            if not tag:
                continue

            pages, primary_page = select_tag_pages_for_vision(doc, tag)
            if not pages:
                continue
            pages = maybe_add_continuation_pages(doc, tag, pages)

            prompt = build_targeted_tag_prompt(standard_id, requirement, pages)
            content: list[dict[str, Any]] = []
            for page_number in pages:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": render_page_png(doc, page_number, dpi),
                        },
                    }
                )
                content.append({"type": "text", "text": f"[Page {page_number}]"})
            content.append({"type": "text", "text": prompt})

            response = client.messages.create(
                model=model,
                max_tokens=2048,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            )
            if not response.content:
                continue

            parsed = parse_model_json(response.content[0].text)
            candidate = parsed if "source_tag" in parsed else {}
            parsed_tag = normalize_source_tag(candidate.get("source_tag", ""))
            if parsed_tag != tag:
                continue

            changed = False
            shall_text = normalize_space(candidate.get("shall_text", ""))
            justification = clean_justification(candidate.get("justification", ""))
            section = normalize_space(candidate.get("section", ""))

            if shall_text and shall_text != requirement.get("shall_text", ""):
                requirement["shall_text"] = shall_text
                subject, requirement_text = split_subject_requirement(shall_text)
                requirement["subject"] = subject
                requirement["requirement"] = requirement_text
                changed = True

            if justification and justification != requirement.get("justification", ""):
                requirement["justification"] = justification
                changed = True

            if section and section != requirement.get("section", ""):
                requirement["section"] = section
                changed = True

            if primary_page and primary_page != requirement.get("page"):
                requirement["page"] = primary_page
                changed = True

            if changed:
                requirement["keywords"] = extract_keywords(
                    requirement.get("shall_text", ""),
                    requirement.get("context", ""),
                    requirement.get("justification", ""),
                )
                requirement["applies_to"] = classify_applies_to(
                    requirement.get("shall_text", ""),
                    requirement.get("context", ""),
                    requirement.get("justification", ""),
                )
                requirement["mua_relevant"] = bool(
                    re.search(r"\bMUA\b", requirement.get("shall_text", ""), re.IGNORECASE)
                )
                repaired += 1
    finally:
        doc.close()

    return requirements, repaired


def build_rule_pack(
    source_extract: Path,
    source_pdf: Path,
    standard_id: str,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    rule_pack_id = f"gpcm-rulepack-{standard_id.lower().replace('.', '').replace('/', '-').replace(' ', '-')}"
    return {
        "schema_version": "gpcm_rulepack/v1",
        "rule_pack_id": rule_pack_id,
        "standard_id": standard_id,
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_document": str(source_pdf),
        "source_extract": str(source_extract),
        "total_requirements": len(requirements),
        "requirements": requirements,
    }


def infer_source_pdf(input_json: Path) -> Path | None:
    stem = input_json.stem
    suffix = "_shall_statements"
    if not stem.endswith(suffix):
        return None
    candidate = input_json.with_name(f"{stem[:-len(suffix)]}.pdf")
    return candidate if candidate.exists() else None


def infer_standard_id(source_pdf: Path | None, input_json: Path) -> str | None:
    candidates = []
    if source_pdf is not None:
        candidates.append(source_pdf.stem)
        candidates.append(source_pdf.name)
    candidates.append(input_json.stem)
    candidates.append(input_json.name)

    for text in candidates:
        match = re.search(r"NASA[-_ ]STD[-_ ](\d{4})([A-Z])", text, re.IGNORECASE)
        if match:
            return f"NASA-STD-{match.group(1)}{match.group(2).upper()}"

        match = re.search(r"\b(\d{4})\s*rev\s*([A-Z])\b", text, re.IGNORECASE)
        if match:
            return f"NASA-STD-{match.group(1)}{match.group(2).upper()}"

        match = re.search(r"\b(\d{4})([A-Z])\b", text, re.IGNORECASE)
        if match:
            return f"NASA-STD-{match.group(1)}{match.group(2).upper()}"

    return None


def default_output_json(input_json: Path, standard_id: str) -> Path:
    slug = standard_id.lower().replace(".", "").replace("/", "-").replace(" ", "_")
    return input_json.with_name(f"gpcm_rulepack_{slug}.json")


def run_adapter(
    input_json: Path,
    source_pdf: Path,
    standard_id: str,
    output_json: Path,
    use_sonnet_vision: bool = False,
    vision_model: str = VISION_MODEL,
    vision_dpi: int = 200,
) -> dict[str, Any]:
    extracted = json.loads(input_json.read_text(encoding="utf-8"))
    pages, frequent_lines, inline_rationales = build_page_bundle(source_pdf)
    tag_blocks = build_tag_blocks(pages)
    tagged_requirements = build_tagged_requirements(
        statements=extracted.get("statements", []),
        tag_blocks=tag_blocks,
        frequent_lines=frequent_lines,
        inline_rationales=inline_rationales,
    )

    if tagged_requirements:
        requirements = tagged_requirements
    else:
        enriched: list[dict[str, Any]] = []
        for statement in extracted.get("statements", []):
            requirement = enrich_statement(
                statement,
                pages,
                frequent_lines,
                inline_rationales,
            )
            if requirement:
                enriched.append(requirement)
        requirements = dedupe_requirements(enriched)

    continuation_repairs = sum(
        1 for requirement in requirements if repair_continuation_from_justification(requirement)
    )
    if continuation_repairs:
        print(f"Continuation repaired: {continuation_repairs}")

    if use_sonnet_vision:
        requirements, repaired_count = apply_vision_repairs(
            requirements=requirements,
            source_pdf=source_pdf,
            standard_id=standard_id,
            model=vision_model,
            dpi=vision_dpi,
        )
        if repaired_count:
            print(f"Vision repaired: {repaired_count}")

        post_vision_continuation_repairs = sum(
            1 for requirement in requirements if repair_continuation_from_justification(requirement)
        )
        if post_vision_continuation_repairs:
            print(f"Post-vision continuation repaired: {post_vision_continuation_repairs}")

        requirements, targeted_repaired_count = apply_targeted_tag_vision_repairs(
            requirements=requirements,
            source_pdf=source_pdf,
            standard_id=standard_id,
            model=vision_model,
            dpi=vision_dpi,
        )
        if targeted_repaired_count:
            print(f"Targeted tag vision repaired: {targeted_repaired_count}")

        post_targeted_continuation_repairs = sum(
            1 for requirement in requirements if repair_continuation_from_justification(requirement)
        )
        if post_targeted_continuation_repairs:
            print(f"Post-targeted continuation repaired: {post_targeted_continuation_repairs}")

        local_fallback_repaired = apply_local_6016_shall_fallbacks(requirements, standard_id)
        if local_fallback_repaired:
            print(f"Local 6016 fallback repaired: {local_fallback_repaired}")

    rule_pack = build_rule_pack(input_json, source_pdf, standard_id, requirements)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(rule_pack, indent=2, ensure_ascii=False), encoding="utf-8")
    return rule_pack


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adapt shall-extractor output into a GPCM requirement rule pack."
    )
    parser.add_argument(
        "input_json_positional",
        nargs="?",
        help="Path to shall_extractor JSON output (shorthand mode)",
    )
    parser.add_argument("--input-json", help="Path to shall_extractor JSON output")
    parser.add_argument("--source-pdf", help="Path to the source PDF")
    parser.add_argument("--standard-id", help="Standard identifier, e.g. NASA-STD-6016C")
    parser.add_argument("--output-json", help="Path to output rule pack JSON")
    parser.add_argument(
        "--use-sonnet-vision",
        action="store_true",
        help="Repair weak requirement rows with targeted Anthropic Sonnet vision calls",
    )
    parser.add_argument(
        "--vision-model",
        default=VISION_MODEL,
        help=f"Anthropic model to use with --use-sonnet-vision (default: {VISION_MODEL})",
    )
    parser.add_argument(
        "--vision-dpi",
        type=int,
        default=200,
        help="Page render DPI for Sonnet vision repair",
    )
    args = parser.parse_args()

    input_json_arg = args.input_json or args.input_json_positional
    if not input_json_arg:
        parser.error("Provide --input-json or a positional JSON path")

    input_json = Path(input_json_arg)
    source_pdf = Path(args.source_pdf) if args.source_pdf else infer_source_pdf(input_json)
    if source_pdf is None:
        parser.error("Could not infer source PDF. Pass --source-pdf explicitly.")

    standard_id = args.standard_id or infer_standard_id(source_pdf, input_json)
    if standard_id is None:
        parser.error("Could not infer standard ID. Pass --standard-id explicitly.")

    output_json = Path(args.output_json) if args.output_json else default_output_json(input_json, standard_id)

    rule_pack = run_adapter(
        input_json=input_json,
        source_pdf=source_pdf,
        standard_id=standard_id,
        output_json=output_json,
        use_sonnet_vision=args.use_sonnet_vision,
        vision_model=args.vision_model,
        vision_dpi=args.vision_dpi,
    )

    print(f"Rule pack:   {output_json}")
    print(f"Requirements: {rule_pack['total_requirements']}")


if __name__ == "__main__":
    main()
