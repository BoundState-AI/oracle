"""
Module: oracle.chat_engine
Purpose: Deterministic Oracle-native pack chat over registered rule packs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oracle.cli import load_pack as cli_load_pack

_STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "can",
    "clause",
    "compare",
    "comparison",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "paragraph",
    "part",
    "say",
    "section",
    "show",
    "standard",
    "table",
    "tell",
    "the",
    "this",
    "to",
    "vs",
    "what",
    "which",
    "with",
}

_SECTION_PATTERN = re.compile(
    r"\b(?:section|sec\.?|clause|paragraph|para\.?)\s+([A-Z]?\d+(?:\.\d+)*(?:[a-z](?:\(\d+\))?)?)\b",
    re.IGNORECASE,
)
_TABLE_NOTE_PATTERN = re.compile(
    r"\btable\s+([IVXLCDM]+|\d+)\s+note\s+(\d+)\b",
    re.IGNORECASE,
)
_COMPARE_PATTERN = re.compile(r"\b(?:compare|comparison|versus|vs\.?)\b", re.IGNORECASE)
_APPROVAL_PATTERN = re.compile(
    r"\b(?:approve\s+this|certify|sign\s+off|waive|final\s+disposition)\b",
    re.IGNORECASE,
)


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value.lower())
    out: list[str] = []
    for token in tokens:
        if token in _STOP_WORDS:
            continue
        if len(token) <= 1:
            continue
        out.append(token)
    return out


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_normalize_space(item) for item in value if _normalize_space(item)]
    return []


def _coerce_page(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = _normalize_space(value)
    if not text:
        return None
    match = re.match(r"(\d+)", text)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class ChatRule:
    pack_slug: str
    standard_id: str
    standard_title: str
    rule_id: str
    section: str
    page: int | None
    obligation_type: str
    obligation_keyword: str
    statement_text: str
    subject: str
    requirement: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class ChatPack:
    pack_slug: str
    standard_id: str
    standard_title: str
    rules: tuple[ChatRule, ...]


def load_chat_pack(pack_name: str, pack_dir: Path) -> ChatPack:
    pack_data, resolved = cli_load_pack(pack_name, pack_dir)
    schema_version = str(pack_data.get("schema_version") or "")
    pack_slug = resolved
    standard_id = _normalize_space(pack_data.get("standard_id") or resolved)
    standard_title = _normalize_space(
        pack_data.get("standard_title") or pack_data.get("source_document") or standard_id
    )
    rules: list[ChatRule] = []

    if schema_version == "gpcm_rulepack/v1" or pack_data.get("requirements"):
        for requirement in pack_data.get("requirements", []):
            if not isinstance(requirement, dict):
                continue
            text = _normalize_space(requirement.get("shall_text"))
            if not text:
                continue
            rules.append(
                ChatRule(
                    pack_slug=pack_slug,
                    standard_id=standard_id,
                    standard_title=standard_title,
                    rule_id=_normalize_space(requirement.get("id")) or "unknown",
                    section=_normalize_space(requirement.get("section")),
                    page=_coerce_page(requirement.get("page")),
                    obligation_type="mandatory",
                    obligation_keyword="shall",
                    statement_text=text,
                    subject=_normalize_space(requirement.get("subject")),
                    requirement=_normalize_space(requirement.get("requirement")),
                    keywords=tuple(_as_str_list(requirement.get("keywords"))),
                )
            )
    elif schema_version == "far_rulepack/v1" or pack_data.get("parts"):
        for part_key, part_rules in pack_data.get("parts", {}).items():
            if not isinstance(part_rules, list):
                continue
            for item in part_rules:
                if not isinstance(item, dict):
                    continue
                text = _normalize_space(item.get("statement_text"))
                if not text:
                    continue
                section = _normalize_space(item.get("section")) or f"Part {part_key}"
                rules.append(
                    ChatRule(
                        pack_slug=pack_slug,
                        standard_id=standard_id,
                        standard_title=standard_title,
                        rule_id=_normalize_space(item.get("id")) or "unknown",
                        section=section,
                        page=_coerce_page(item.get("page")),
                        obligation_type=_normalize_space(item.get("obligation_type")).lower() or "mandatory",
                        obligation_keyword=_normalize_space(item.get("obligation_keyword")).lower() or "shall",
                        statement_text=text,
                        subject=_normalize_space(item.get("subject")),
                        requirement=_normalize_space(item.get("requirement")),
                        keywords=tuple(_as_str_list(item.get("keywords"))),
                    )
                )
    else:
        for item in pack_data.get("rules", []):
            if not isinstance(item, dict):
                continue
            text = _normalize_space(item.get("statement_text"))
            if not text:
                continue
            rules.append(
                ChatRule(
                    pack_slug=pack_slug,
                    standard_id=standard_id,
                    standard_title=standard_title,
                    rule_id=_normalize_space(item.get("rule_id")) or "unknown",
                    section=_normalize_space(item.get("section")),
                    page=_coerce_page(item.get("page")),
                    obligation_type=_normalize_space(item.get("obligation_type")).lower() or "mandatory",
                    obligation_keyword=_normalize_space(item.get("obligation_keyword")).lower() or "shall",
                    statement_text=text,
                    subject=_normalize_space(item.get("subject")),
                    requirement=_normalize_space(item.get("requirement")),
                    keywords=tuple(_as_str_list(item.get("keywords"))),
                )
            )

    return ChatPack(
        pack_slug=pack_slug,
        standard_id=standard_id,
        standard_title=standard_title,
        rules=tuple(rules),
    )


def _citation(rule: ChatRule) -> str:
    section = f" §{rule.section}" if rule.section else ""
    page = f" (p. {rule.page})" if rule.page else ""
    return f"{rule.standard_id}{section}{page}"


def _rank_rules(raw_query: str, rules: tuple[ChatRule, ...]) -> list[tuple[ChatRule, int]]:
    query_tokens = set(_tokenize(raw_query))
    section_match = _SECTION_PATTERN.search(raw_query)
    table_note_match = _TABLE_NOTE_PATTERN.search(raw_query)
    ranked: list[tuple[ChatRule, int]] = []

    for rule in rules:
        haystack_tokens = query_tokens.intersection(
            set(_tokenize(" ".join([rule.statement_text, rule.subject, rule.requirement, *rule.keywords])))
        )
        score = len(haystack_tokens) * 3

        if section_match:
            requested = _normalize_space(section_match.group(1)).lower()
            if requested and requested in rule.section.lower():
                score += 8

        if table_note_match:
            requested = f"table {table_note_match.group(1)} note {table_note_match.group(2)}".lower()
            if requested in rule.section.lower():
                score += 10

        if rule.section and rule.section.lower() in raw_query.lower():
            score += 4
        if rule.subject and rule.subject.lower() in raw_query.lower():
            score += 4
        if rule.obligation_type == "prohibition" and any(token in raw_query.lower() for token in ("avoid", "prohibit", "shall not", "not use")):
            score += 2

        if score > 0:
            ranked.append((rule, score))

    ranked.sort(
        key=lambda item: (
            -item[1],
            item[0].page if item[0].page is not None else 10_000,
            item[0].section,
            item[0].rule_id,
        )
    )
    return ranked


def _compare_packs(message: str, packs: list[ChatPack]) -> dict[str, Any]:
    lines = ["Oracle comparison across selected standards:", ""]
    citations: list[str] = []
    for pack in packs:
        matches = _rank_rules(message, pack.rules)[:3]
        lines.append(f"{pack.standard_id}:")
        if not matches:
            lines.append("  No grounded requirement match found for this topic.")
            lines.append("")
            continue
        for rule, _score in matches:
            citation = _citation(rule)
            citations.append(citation)
            lines.append(f"  - {citation}")
            lines.append(f"    {rule.statement_text}")
        lines.append("")

    lines.append(
        "Use this as a clause-level comparison aid. Oracle does not issue final sign-off, certification, or waiver decisions."
    )
    first = packs[0]
    follow_ups = [
        f"Which clause is stricter between {packs[0].standard_id} and {packs[1].standard_id}?",
        f"Show the exact governing text from {first.standard_id}.",
    ]
    return {
        "status": "PASS" if citations else "INSUFFICIENT_DATA",
        "response": "\n".join(lines).strip(),
        "citations": citations,
        "follow_ups": follow_ups,
        "selected_packs": [pack.pack_slug for pack in packs],
        "compare_only": True,
        "advisory_only": True,
    }


def answer_query(
    *,
    message: str,
    pack_names: list[str],
    pack_dir: Path,
    compare_only: bool = False,
) -> dict[str, Any]:
    query = _normalize_space(message)
    if not query:
        return {
            "status": "INSUFFICIENT_DATA",
            "response": "Oracle needs a standards question to answer.",
            "citations": [],
            "follow_ups": [],
            "selected_packs": pack_names,
            "compare_only": compare_only,
            "advisory_only": True,
        }

    if _APPROVAL_PATTERN.search(query):
        return {
            "status": "REFUSE",
            "response": (
                "Oracle can surface governing clauses and evidence paths, but it does not issue final approval, "
                "certification, waiver, or sign-off decisions."
            ),
            "citations": [],
            "follow_ups": [],
            "selected_packs": pack_names,
            "compare_only": compare_only,
            "advisory_only": True,
        }

    if not pack_names:
        return {
            "status": "INSUFFICIENT_DATA",
            "response": (
                "Select at least one authority pack before chatting. Oracle stays grounded in the packs you pick."
            ),
            "citations": [],
            "follow_ups": [],
            "selected_packs": [],
            "compare_only": compare_only,
            "advisory_only": True,
        }

    packs = [load_chat_pack(pack_name, pack_dir) for pack_name in pack_names]
    if len(packs) > 1 and not compare_only and not _COMPARE_PATTERN.search(query):
        return {
            "status": "INSUFFICIENT_DATA",
            "response": (
                "Multiple packs are selected. Narrow to one pack for clause lookup or turn on compare mode to chat across selected standards."
            ),
            "citations": [],
            "follow_ups": [
                f"Compare {packs[0].standard_id} and {packs[1].standard_id}.",
                f"Limit this question to {packs[0].standard_id}.",
            ],
            "selected_packs": [pack.pack_slug for pack in packs],
            "compare_only": compare_only,
            "advisory_only": True,
        }

    if len(packs) > 1 and (compare_only or _COMPARE_PATTERN.search(query)):
        return _compare_packs(query, packs[:2])

    pack = packs[0]
    matches = _rank_rules(query, pack.rules)
    if not matches:
        return {
            "status": "INSUFFICIENT_DATA",
            "response": (
                f"I found {pack.standard_id}, but I did not find a grounded requirement match for that topic. "
                "Narrow this by section, table note, appendix, or part family."
            ),
            "citations": [pack.standard_id],
            "follow_ups": [
                f"Show me the exact section in {pack.standard_id}.",
                f"List the top requirements in {pack.standard_id} for this topic.",
            ],
            "selected_packs": [pack.pack_slug],
            "compare_only": False,
            "advisory_only": True,
        }

    top_matches = matches[:5]
    lines = [
        f"Oracle matched {len(top_matches)} governing requirement(s) in {pack.standard_id}.",
        "",
    ]
    citations: list[str] = []
    for idx, (rule, _score) in enumerate(top_matches, start=1):
        citation = _citation(rule)
        citations.append(citation)
        lines.append(f"{idx}. {citation}")
        lines.append(f"   {rule.statement_text}")
        if rule.requirement and rule.requirement != rule.statement_text:
            lines.append(f"   Practical meaning: {rule.requirement}")
        if rule.subject:
            lines.append(f"   Topic: {rule.subject}")
        lines.append("")
    lines.append(
        "If you want a tighter answer, ask for a specific section, table note, appendix, or compare it against another selected standard."
    )

    return {
        "status": "PASS",
        "response": "\n".join(lines).strip(),
        "citations": citations,
        "follow_ups": [
            f"Show the exact requirement text from {citations[0]}.",
            f"List the top requirements in {pack.standard_id} for this topic.",
        ],
        "selected_packs": [pack.pack_slug],
        "compare_only": False,
        "advisory_only": True,
    }
