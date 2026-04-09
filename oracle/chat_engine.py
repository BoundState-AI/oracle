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
_CLAUSE_LOOKUP_PATTERN = re.compile(
    r"\b(?:show|quote|exact|text|verbatim|section|sec\.?|clause|paragraph|para\.?|table|note)\b",
    re.IGNORECASE,
)
_YES_NO_PATTERN = re.compile(r"^(?:if|is|are|can|could|does|do|would|will|should)\b", re.IGNORECASE)
_COMPLIANCE_RISK_PATTERN = re.compile(
    r"\b(?:against|violate|violation|non-?compliant|compliant|allowed|permit|permitted|ok|okay|require|required|must)\b",
    re.IGNORECASE,
)
_SCOPE_PATTERN = re.compile(r"\b(?:scope|change|insert|added?|modify|revision)\b", re.IGNORECASE)
_FUNDING_PATTERN = re.compile(
    r"\b(?:fund|funding|unfunded|cost|budget|charge code|cwbs|psid)\b",
    re.IGNORECASE,
)
_VAGUE_TERM_PATTERN = re.compile(
    r"\b(?:appropriate|adequate|sufficient|timely|reasonable|as needed|as appropriate|where possible|support|supports|optimi[sz]e|minimi[sz]e|robust|user-friendly|efficient)\b",
    re.IGNORECASE,
)
_OWNER_PATTERN = re.compile(
    r"\b(?:contractor|government|team|program|office|manager|engineer|reviewer|operator|system|supplier|vendor|customer|cor|co|tm|ra|ti)\b",
    re.IGNORECASE,
)
_ACTION_PATTERN = re.compile(
    r"\b(?:shall|must|will|should|provide|deliver|submit|update|maintain|complete|implement|notify|document|record|verify|validate|review)\b",
    re.IGNORECASE,
)
_MEASURE_PATTERN = re.compile(
    r"\b(?:within|no later than|at least|at most|maximum|min(?:imum)?|threshold|metric|acceptance|evidence|artifact|deliverable|report|log|record|trace|test|inspection|review criteria|\d+%?|\d+\s*(?:day|days|hour|hours|week|weeks|month|months))\b",
    re.IGNORECASE,
)
_CHANGE_CONTROL_PATTERN = re.compile(
    r"\b(?:change|scope|insert|modify|revision|revise|update|delete|replace|addition)\b",
    re.IGNORECASE,
)
_IMPACT_PATTERN = re.compile(
    r"\b(?:cost|fund|funding|schedule|interface|baseline|configuration|document|drawing|approval|impact|cwbs|psid|artifact)\b",
    re.IGNORECASE,
)
_REVIEW_GOVERNANCE_PATTERN = re.compile(
    r"\b(?:approval|approve|accept|sign-?off|concurrence|waiver|authorize|authorized)\b",
    re.IGNORECASE,
)


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_token(value: str) -> str:
    token = value.lower().strip("._-")
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value.lower())
    out: list[str] = []
    for token in tokens:
        token = _normalize_token(token)
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


def _slug_terms(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(_tokenize(value.replace("_", " ").replace("-", " ")))


def _query_terms(raw_query: str) -> set[str]:
    terms = set(_tokenize(raw_query))
    if _FUNDING_PATTERN.search(raw_query):
        terms.update({"fund", "funding", "cost", "budget", "cwbs", "psid"})
    if _SCOPE_PATTERN.search(raw_query):
        terms.update({"scope", "change", "revision", "tocr"})
    if _COMPLIANCE_RISK_PATTERN.search(raw_query):
        terms.update({"violate", "prohibit", "mandatory", "must", "required"})
    return terms


def _phrase_score(query_terms: set[str], phrase: str) -> int:
    phrase_terms = set(_tokenize(phrase))
    if not phrase_terms:
        return 0
    overlap = query_terms.intersection(phrase_terms)
    if not overlap:
        return 0
    score = len(overlap) * 2
    if overlap == phrase_terms:
        score += 2
    return score


def _is_yes_no_query(query: str) -> bool:
    return bool(_YES_NO_PATTERN.search(query.strip()) or _COMPLIANCE_RISK_PATTERN.search(query))


def _is_clause_lookup_query(query: str) -> bool:
    return bool(
        _CLAUSE_LOOKUP_PATTERN.search(query)
        or _SECTION_PATTERN.search(query)
        or _TABLE_NOTE_PATTERN.search(query)
    )


def _is_scope_funding_query(query: str) -> bool:
    return bool(_SCOPE_PATTERN.search(query) and _FUNDING_PATTERN.search(query))


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
    applies_to: tuple[str, ...]


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
                    applies_to=tuple(_as_str_list(requirement.get("applies_to"))),
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
                        applies_to=tuple(_as_str_list(item.get("applies_to"))),
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
                    applies_to=tuple(_as_str_list(item.get("applies_to"))),
                )
            )

    return ChatPack(
        pack_slug=pack_slug,
        standard_id=standard_id,
        standard_title=standard_title,
        rules=tuple(rules),
    )


def _citation(rule: ChatRule) -> str:
    section = f" section {rule.section}" if rule.section else ""
    page = f" (p. {rule.page})" if rule.page else ""
    return f"{rule.standard_id}{section}{page}"


def _rank_rules(raw_query: str, rules: tuple[ChatRule, ...]) -> list[tuple[ChatRule, int]]:
    query_tokens = _query_terms(raw_query)
    section_match = _SECTION_PATTERN.search(raw_query)
    table_note_match = _TABLE_NOTE_PATTERN.search(raw_query)
    ranked: list[tuple[ChatRule, int]] = []
    yes_no_query = _is_yes_no_query(raw_query)
    scope_funding_query = _is_scope_funding_query(raw_query)

    for rule in rules:
        searchable_parts = [
            rule.statement_text,
            rule.subject,
            rule.requirement,
            rule.section,
            *rule.keywords,
            *rule.applies_to,
        ]
        haystack_tokens = query_tokens.intersection(set(_tokenize(" ".join(searchable_parts))))
        score = len(haystack_tokens) * 3
        score += _phrase_score(query_tokens, rule.subject)
        score += _phrase_score(query_tokens, rule.requirement)
        score += sum(_phrase_score(query_tokens, keyword) for keyword in rule.keywords)
        score += sum(_phrase_score(query_tokens, applies) for applies in rule.applies_to)

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
        if rule.obligation_type == "prohibition" and any(
            token in raw_query.lower() for token in ("avoid", "prohibit", "shall not", "not use")
        ):
            score += 2
        if yes_no_query and rule.obligation_type in {"mandatory", "prohibition"}:
            score += 2
        if scope_funding_query:
            applies_to_terms = set(_slug_terms(" ".join(rule.applies_to)))
            rule_terms = set(_tokenize(" ".join([rule.subject, rule.requirement, *rule.keywords])))
            if {"scope", "change"}.intersection(rule_terms.union(applies_to_terms)):
                score += 6
            if {"fund", "funding", "cost", "cwbs", "psid"}.intersection(rule_terms.union(applies_to_terms)):
                score += 6
            if "tocr" in rule_terms.union(applies_to_terms):
                score += 4

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


def _dedupe_rules(matches: list[tuple[ChatRule, int]], limit: int) -> list[tuple[ChatRule, int]]:
    seen: set[str] = set()
    deduped: list[tuple[ChatRule, int]] = []
    for rule, score in matches:
        key = f"{rule.section}|{rule.requirement}|{rule.statement_text}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append((rule, score))
        if len(deduped) >= limit:
            break
    return deduped


def _summarize_rule(rule: ChatRule) -> str:
    if rule.requirement:
        return rule.requirement.rstrip(".") + "."
    return rule.statement_text.rstrip(".") + "."


def _review_only_findings(query: str) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []

    if _VAGUE_TERM_PATTERN.search(query):
        findings.append(
            (
                "ambiguity",
                "The wording uses vague qualifiers like 'appropriate', 'sufficient', or 'as needed' without a measurable boundary.",
            )
        )

    if _ACTION_PATTERN.search(query) and not _OWNER_PATTERN.search(query):
        findings.append(
            (
                "omission",
                "The draft names an action but not a clear accountable actor, so ownership is easy to dispute later.",
            )
        )

    if _ACTION_PATTERN.search(query) and not _MEASURE_PATTERN.search(query):
        findings.append(
            (
                "testability",
                "The requirement is hard to verify because it does not name acceptance criteria, a deadline, or an observable artifact.",
            )
        )

    if _REVIEW_GOVERNANCE_PATTERN.search(query):
        findings.append(
            (
                "governance",
                "The text invokes approval or acceptance, but it should also name the approving role and the entry or exit criteria for that decision.",
            )
        )

    if _CHANGE_CONTROL_PATTERN.search(query) and not _IMPACT_PATTERN.search(query):
        findings.append(
            (
                "scope",
                "The text changes scope or baselines without saying what downstream approvals, artifacts, funding, cost, or schedule impacts must be updated.",
            )
        )

    return findings


def _answer_review_only(query: str, compare_only: bool) -> dict[str, Any]:
    if compare_only:
        return {
            "status": "INSUFFICIENT_DATA",
            "response": (
                "Review-only mode does not compare authority packs. Switch back to authority-grounded mode to compare standards, "
                "or paste two draft clauses and ask for a wording comparison."
            ),
            "citations": [],
            "follow_ups": [
                "Turn off review-only and compare the selected packs.",
                "Paste two draft clauses and ask which one is tighter.",
            ],
            "selected_packs": [],
            "compare_only": False,
            "review_only": True,
            "advisory_only": True,
        }

    findings = _review_only_findings(query)
    if not findings:
        return {
            "status": "PASS",
            "response": (
                "Review-only assessment. No authority packs were applied.\n\n"
                "I do not see a strong defect signal from the text you sent, but review-only mode is much stronger when you paste the actual requirement, paragraph, or approval language to inspect.\n\n"
                "What I would test next:\n"
                "- Name the accountable actor.\n"
                "- Add measurable acceptance criteria or required artifacts.\n"
                "- State any approval path, timing, and downstream update obligations."
            ),
            "citations": [],
            "follow_ups": [
                "Review this requirement for ambiguity and missing acceptance criteria: <paste text>",
                "Rewrite this clause so it is testable and names the responsible actor.",
            ],
            "selected_packs": [],
            "compare_only": False,
            "review_only": True,
            "advisory_only": True,
        }

    top_findings = findings[:3]
    lines = [
        "Review-only assessment. No authority packs were applied.",
        "",
        "Top issues in the draft wording:",
    ]
    for idx, (_category, detail) in enumerate(top_findings, start=1):
        lines.append(f"{idx}. {detail}")
    lines.extend(
        [
            "",
            "Bottom line:",
            "This reads more like direction than an enforceable requirement. Tighten the actor, trigger, measurable outcome, and any approval or change-control gates.",
        ]
    )

    return {
        "status": "PASS",
        "response": "\n".join(lines).strip(),
        "citations": [f"review-only/{category}" for category, _detail in top_findings],
        "follow_ups": [
            "Rewrite this requirement in a tighter, testable form.",
            "Show me the missing approvals, artifacts, and acceptance criteria in this draft.",
        ],
        "selected_packs": [],
        "compare_only": False,
        "review_only": True,
        "advisory_only": True,
    }


def _build_single_pack_synthesis(
    query: str,
    pack: ChatPack,
    matches: list[tuple[ChatRule, int]],
) -> dict[str, Any]:
    top_matches = _dedupe_rules(matches, 3)
    citations = [_citation(rule) for rule, _score in top_matches]
    lines: list[str] = []

    if _is_yes_no_query(query):
        lines.append("Likely yes.")
        if _is_scope_funding_query(query):
            lines.append(
                "A scope change without corresponding funding or cost handling looks inconsistent with the selected standard's required TOCR process."
            )
        else:
            lines.append(
                f"Based on the matched clauses in {pack.standard_id}, this looks inconsistent with the required process."
            )
    else:
        lines.append(f"Grounded answer from {pack.standard_id}.")

    lines.append("")
    if _is_scope_funding_query(query):
        lines.append(
            "I am interpreting 'do not fund it' as missing funding-source data or an unaddressed cost impact."
        )
        lines.append("")

    lines.append("Why:")
    for rule, _score in top_matches:
        lines.append(f"- {_summarize_rule(rule)} ({_citation(rule)})")

    lines.append("")
    lines.append("Bottom line:")
    if _is_scope_funding_query(query):
        lines.append(
            "If the scope insertion changes the work and carries cost or funding consequences, J-21 points you into the TOCR path with cost-impact disclosure, funding/CWBS data, and the full approval chain."
        )
    elif _is_yes_no_query(query):
        lines.append(
            "Treat this as a compliance issue unless the change is routed through the process the cited clauses require."
        )
    else:
        lines.append("Use the cited clauses below as the governing support for the answer.")

    follow_ups = [
        f"Show me the exact clause text for {citations[0]}.",
        f"What would make this compliant under {pack.standard_id}?",
    ]
    return {
        "status": "PASS",
        "response": "\n".join(lines).strip(),
        "citations": citations,
        "follow_ups": follow_ups,
        "selected_packs": [pack.pack_slug],
        "compare_only": False,
        "review_only": False,
        "advisory_only": True,
    }


def _compare_packs(message: str, packs: list[ChatPack]) -> dict[str, Any]:
    lines = ["Oracle comparison across selected standards:", ""]
    citations: list[str] = []
    for pack in packs:
        matches = _dedupe_rules(_rank_rules(message, pack.rules), 3)
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
        "review_only": False,
        "advisory_only": True,
    }


def answer_query(
    *,
    message: str,
    pack_names: list[str],
    pack_dir: Path,
    compare_only: bool = False,
    review_only: bool = False,
) -> dict[str, Any]:
    query = _normalize_space(message)
    if not query:
        return {
            "status": "INSUFFICIENT_DATA",
            "response": (
                "Oracle needs a question, requirement, or draft clause to inspect."
                if review_only
                else "Oracle needs a standards question to answer."
            ),
            "citations": [],
            "follow_ups": [],
            "selected_packs": pack_names,
            "compare_only": compare_only,
            "review_only": review_only,
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
            "review_only": review_only,
            "advisory_only": True,
        }

    if review_only:
        return _answer_review_only(query, compare_only)

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
            "review_only": False,
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
            "review_only": False,
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
            "review_only": False,
            "advisory_only": True,
        }

    if not _is_clause_lookup_query(query):
        return _build_single_pack_synthesis(query, pack, matches)

    top_matches = _dedupe_rules(matches, 5)
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
        "review_only": False,
        "advisory_only": True,
    }
