"""
Module: oracle.chat_engine
Purpose: Deterministic Oracle-native pack chat over registered rule packs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oracle.chat_contract import OracleChatEnvelope, OracleEvidenceItem
from oracle.chat_formatter import format_chat_response
from oracle.chat_grader import grade_chat_response
from oracle.cli import load_pack as cli_load_pack

LOGGER = logging.getLogger("oracle.chat")

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
    "selected",
    "table",
    "tell",
    "the",
    "this",
    "to",
    "vs",
    "what",
    "which",
    "with",
    "finish",
    "finishes",
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
_PROHIBITED_DECISION_LANGUAGE_PATTERN = re.compile(
    r"\b(?:approved?|approval|certif(?:y|ied|ication)|waiv(?:e|er|ed)|sign-?off|accepted?|greenlight(?:ed)?)\b",
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


def _has_strong_rule_anchor(
    *,
    query_terms: set[str],
    rule: ChatRule,
    raw_query: str,
    section_match: re.Match[str] | None,
    table_note_match: re.Match[str] | None,
) -> bool:
    if section_match or table_note_match:
        return True
    if _phrase_score(query_terms, rule.subject) >= 4:
        return True
    if _phrase_score(query_terms, rule.requirement) >= 4:
        return True
    if any(_phrase_score(query_terms, keyword) >= 4 for keyword in rule.keywords):
        return True
    if rule.subject and rule.subject.lower() in raw_query.lower():
        return True
    return False


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


def _wants_exact_text(query: str) -> bool:
    return bool(re.search(r"\b(show|quote|exact|verbatim|full text)\b", query, re.IGNORECASE))


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
            strong_anchor = _has_strong_rule_anchor(
                query_terms=query_tokens,
                rule=rule,
                raw_query=raw_query,
                section_match=section_match,
                table_note_match=table_note_match,
            )
            if len(haystack_tokens) < 2 and not strong_anchor:
                continue
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


def _rule_topic(rule: ChatRule) -> str:
    return rule.subject or rule.requirement or rule.statement_text


def _rule_stance(rule: ChatRule) -> str:
    text = " ".join(
        part for part in [rule.obligation_type, rule.obligation_keyword, rule.statement_text, rule.requirement] if part
    ).lower()
    if any(token in text for token in ("shall not", "must not", "prohibit", "not be used", "not use")):
        return "prohibits"
    if rule.obligation_type == "recommendation" or rule.obligation_keyword == "should":
        return "recommends"
    if rule.obligation_type == "permission" or rule.obligation_keyword == "may":
        return "allows"
    return "requires"


def _topic_answer_sentence(query: str, pack: ChatPack, top_matches: list[tuple[ChatRule, int]]) -> str:
    lead_rule = top_matches[0][0]
    lead_summary = _summarize_rule(lead_rule)
    stance = _rule_stance(lead_rule)
    topic = _normalize_space(_rule_topic(lead_rule))

    if _is_scope_funding_query(query):
        return (
            f"{pack.standard_id} routes this kind of scope-and-funding change into formal change control. "
            f"Lead requirement: {lead_summary}"
        )
    if _is_yes_no_query(query):
        if stance == "prohibits":
            return f"No. {lead_summary}"
        if stance == "allows":
            return f"Yes, within the limits of the cited clause. {lead_summary}"
        return f"The selected standard does not read as an informal yes. It {stance} the following: {lead_summary}"
    if _is_clause_lookup_query(query):
        if topic:
            return f"On {topic}, {pack.standard_id} says: {lead_summary}"
        return f"{pack.standard_id} says: {lead_summary}"
    return f"{pack.standard_id} answers this topic with: {lead_summary}"


def _render_grounded_pack_answer(
    *,
    query: str,
    pack: ChatPack,
    top_matches: list[tuple[ChatRule, int]],
) -> str:
    citations = [_citation(rule) for rule, _score in top_matches]
    lines = [_topic_answer_sentence(query, pack, top_matches), ""]

    lines.append("Why:")
    for rule, _score in top_matches[:3]:
        summary = _summarize_rule(rule)
        topic = _normalize_space(rule.subject)
        detail = f"- {summary} ({_citation(rule)})"
        if topic and topic.lower() not in summary.lower():
            detail += f" Topic: {topic}."
        lines.append(detail)

    lines.append("")
    lines.append("Bottom line:")
    if _is_scope_funding_query(query):
        lines.append(
            "Do not treat this as an informal scope insert. The cited clauses point you to formal TOCR/change-control handling with cost and funding data."
        )
    elif _is_yes_no_query(query):
        lines.append(
            "Use the cited clauses as the governing basis for the answer. If your facts differ from the matched topic, narrow the question by clause or section."
        )
    else:
        lines.append(
            "This is the grounded answer from the selected pack, not a final approval or waiver decision."
        )

    lines.append("")
    lines.append("Citations:")
    for citation in citations:
        lines.append(f"- {citation}")
    return "\n".join(lines).strip()


def _render_compare_answer(
    *,
    query: str,
    packs: list[ChatPack],
    findings: list[dict[str, Any]],
) -> str:
    lines = ["Comparison across selected standards.", ""]
    for finding in findings:
        pack = finding["pack"]
        matches = finding["matches"]
        if not matches:
            lines.append(f"{pack.standard_id}: No grounded requirement match found for this topic.")
            lines.append("")
            continue

        lead_rule = matches[0][0]
        lines.append(f"{pack.standard_id}: {_topic_answer_sentence(query, pack, matches)}")
        for rule, _score in matches[:2]:
            lines.append(f"- {_summarize_rule(rule)} ({_citation(rule)})")
        lines.append("")

    lines.append(
        "Use this to compare governing clauses. Oracle still does not issue final sign-off, certification, or waiver decisions."
    )
    return "\n".join(lines).strip()


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
        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query=query,
                intent="review_only",
                selected_packs=[],
                compare_only=False,
                review_only=True,
                missing_inputs=[
                    "Turn off review-only mode if you want a standards comparison.",
                ],
                follow_ups=[
                    "Turn off review-only and compare the selected packs.",
                    "Paste two draft clauses and ask which one is tighter.",
                ],
                draft_answer_text=(
                    "Review-only mode does not compare authority packs. Switch back to authority-grounded mode to compare standards, "
                    "or paste two draft clauses and ask for a wording comparison."
                ),
            )
        )

    findings = _review_only_findings(query)
    if not findings:
        return _emit_envelope(
            OracleChatEnvelope(
                status="PASS",
                query=query,
                intent="review_only",
                selected_packs=[],
                compare_only=False,
                review_only=True,
                follow_ups=[
                    "Review this requirement for ambiguity and missing acceptance criteria: <paste text>",
                    "Rewrite this clause so it is testable and names the responsible actor.",
                ],
                draft_answer_text=(
                    "Review-only assessment. No authority packs were applied. I do not see a strong defect signal from the text you sent, "
                    "but review-only mode is much stronger when you paste the actual requirement, paragraph, or approval language to inspect."
                ),
            )
        )

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

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=query,
            intent="review_only",
            selected_packs=[],
            compare_only=False,
            review_only=True,
            citations=[f"review-only/{category}" for category, _detail in top_findings],
            evidence=[
                OracleEvidenceItem(citation=f"review-only/{category}", summary=detail)
                for category, detail in top_findings
            ],
            follow_ups=[
                "Rewrite this requirement in a tighter, testable form.",
                "Show me the missing approvals, artifacts, and acceptance criteria in this draft.",
            ],
            draft_answer_text="\n".join(lines).strip(),
        )
    )


def _chat_result(
    *,
    status: str,
    response: str,
    citations: list[str],
    follow_ups: list[str],
    selected_packs: list[str],
    compare_only: bool,
    review_only: bool,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ordered_stage_keys = ["gatekeeper", "retrieval", "reasoning", "summary"]
    stages_completed = []
    if stage_artifacts:
        stages_completed = [key for key in ordered_stage_keys if key in stage_artifacts]
    merged_diagnostics = {
        "fallback_used": False,
        "fallback_reason": None,
        "validation_failures": [],
        "stages_completed": stages_completed,
    }
    if diagnostics:
        merged_diagnostics.update(diagnostics)
        if "stages_completed" not in diagnostics:
            merged_diagnostics["stages_completed"] = stages_completed

    result = {
        "envelope_version": "1.0",
        "status": status,
        "answer_text": response,
        "response": response,
        "evidence_assessment": evidence_assessment,
        "citations": citations,
        "follow_ups": follow_ups,
        "selected_packs": selected_packs,
        "compare_only": compare_only,
        "review_only": review_only,
        "advisory_only": True,
        "diagnostics": merged_diagnostics,
    }
    if stage_artifacts:
        result["stage_artifacts"] = stage_artifacts
    return result


def _evidence_item(
    *,
    rule: ChatRule,
    score: int | None = None,
) -> OracleEvidenceItem:
    return OracleEvidenceItem(
        citation=_citation(rule),
        summary=_summarize_rule(rule),
        statement_text=rule.statement_text,
        topic=rule.subject,
        standard_id=rule.standard_id,
        score=score,
    )


def _emit_envelope(envelope: OracleChatEnvelope) -> dict[str, Any]:
    formatted = format_chat_response(envelope, allow_draft_answer=True)
    grade = grade_chat_response(formatted, envelope)

    diagnostics = dict(envelope.diagnostics or {})
    validation_failures = list(diagnostics.get("validation_failures", []))
    if not grade.passed:
        validation_failures.extend(grade.failures)
        diagnostics["fallback_used"] = True
        diagnostics["fallback_reason"] = diagnostics.get("fallback_reason") or "formatter_grader_failure"
        diagnostics["validation_failures"] = validation_failures
        formatted = format_chat_response(envelope, allow_draft_answer=False)
    elif "validation_failures" not in diagnostics:
        diagnostics["validation_failures"] = validation_failures

    return _chat_result(
        status=envelope.status,
        response=formatted,
        citations=envelope.citations_or_authority(),
        follow_ups=envelope.follow_ups,
        selected_packs=envelope.selected_packs,
        compare_only=envelope.compare_only,
        review_only=envelope.review_only,
        evidence_assessment=envelope.evidence_assessment,
        diagnostics=diagnostics,
        stage_artifacts=envelope.stage_artifacts,
    )


def _chat_model_provider() -> str | None:
    explicit = _normalize_space(os.environ.get("ORACLE_CHAT_PROVIDER"))
    if explicit:
        return explicit.lower()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def _reasoning_model_name(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("ORACLE_REASONING_MODEL", "gpt-5.4")
    return os.environ.get("ORACLE_REASONING_MODEL", "claude-sonnet-4-6")


def _summary_model_name(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("ORACLE_SUMMARY_MODEL", "gpt-5.4-mini")
    return os.environ.get("ORACLE_SUMMARY_MODEL", "claude-haiku-4-5-20251001")


def _extract_text_blocks(blocks: Any) -> str:
    text_parts: list[str] = []
    if isinstance(blocks, str):
        return blocks.strip()
    for block in blocks or []:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            text_parts.append(str(block.text))
    return "\n".join(part.strip() for part in text_parts if part.strip()).strip()


def _call_model_json(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
) -> dict[str, Any]:
    if provider == "anthropic":
        import httpx
        from anthropic import Anthropic

        client = Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = _extract_text_blocks(response.content)
    elif provider == "openai":
        import httpx
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if model.startswith(("gpt-5", "o3", "o4")):
            kwargs["max_completion_tokens"] = max_tokens
            kwargs["reasoning_effort"] = os.environ.get("ORACLE_CHAT_REASONING_EFFORT", "medium")
            kwargs["verbosity"] = os.environ.get("ORACLE_CHAT_VERBOSITY", "medium")
        else:
            kwargs["temperature"] = 0.0
            kwargs["max_tokens"] = max_tokens
        response = client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
    else:
        raise RuntimeError(f"Unsupported chat provider: {provider}")

    if not text:
        raise RuntimeError("Chat model returned empty response.")
    return json.loads(text)


def _serialize_rule(rule: ChatRule, score: int | None = None) -> dict[str, Any]:
    payload = {
        "pack_slug": rule.pack_slug,
        "standard_id": rule.standard_id,
        "standard_title": rule.standard_title,
        "rule_id": rule.rule_id,
        "section": rule.section,
        "page": rule.page,
        "obligation_type": rule.obligation_type,
        "statement_text": rule.statement_text,
        "requirement": rule.requirement,
        "subject": rule.subject,
        "keywords": list(rule.keywords),
        "applies_to": list(rule.applies_to),
        "display_citation": _citation(rule),
    }
    if score is not None:
        payload["score"] = score
    return payload


def _llm_reasoning_system_prompt() -> str:
    return (
        "You are the Oracle reasoning stage. "
        "You reason only over the retrieved rules provided by the caller. "
        "Do not invent requirements. Do not issue approval, waiver, certification, or sign-off decisions. "
        "Return strict JSON with keys: direct_answer, bottom_line, why, governing_citations, gaps, follow_ups, per_pack_findings. "
        "governing_citations must only contain exact display_citation strings from the input payload. "
        "why and gaps must be arrays of concise strings. "
        "per_pack_findings must be an array of objects with keys standard_id, finding, citations."
    )


def _llm_summary_system_prompt() -> str:
    return (
        "You are the Oracle summary stage. "
        "Convert the reasoning payload into concise operator guidance. "
        "Lead with the direct answer or bottom line. "
        "Do not invent claims or citations. "
        "Return strict JSON with keys: answer_text, citations, follow_ups. "
        "citations must be a subset of the provided governing citations. "
        "follow_ups must be short operator prompts."
    )


def _allowed_citations_from_retrieval(retrieval: dict[str, Any]) -> set[str]:
    citations: set[str] = set()
    if retrieval.get("compare_mode"):
        for finding in retrieval.get("pack_findings", []):
            for rule, _score in finding.get("matches", []):
                citations.add(_citation(rule))
    else:
        for rule, _score in retrieval.get("matches", []):
            citations.add(_citation(rule))
    return citations


def _maybe_run_llm_reasoning(
    *,
    query: str,
    gatekeeper: dict[str, Any],
    retrieval: dict[str, Any],
) -> dict[str, Any] | None:
    provider = _chat_model_provider()
    if not provider:
        return None

    payload: dict[str, Any] = {
        "query": query,
        "intent": gatekeeper["intent"],
        "compare_mode": gatekeeper["compare_mode"],
        "filters": gatekeeper["filters"],
        "packs_queried": retrieval["packs_queried"],
    }
    if retrieval.get("compare_mode"):
        payload["matches_by_pack"] = [
            {
                "pack_slug": finding["pack"].pack_slug,
                "standard_id": finding["pack"].standard_id,
                "matches": [_serialize_rule(rule, score) for rule, score in finding["matches"]],
            }
            for finding in retrieval.get("pack_findings", [])
        ]
    else:
        payload["matches"] = [
            _serialize_rule(rule, score) for rule, score in retrieval.get("matches", [])
        ]

    try:
        result = _call_model_json(
            provider=provider,
            model=_reasoning_model_name(provider),
            system_prompt=_llm_reasoning_system_prompt(),
            user_message=json.dumps(payload, indent=2),
            max_tokens=int(os.environ.get("ORACLE_CHAT_REASONING_MAX_TOKENS", "2400")),
        )
    except Exception as exc:
        LOGGER.warning("Oracle reasoning model failed; using deterministic reasoning: %s", exc)
        return None

    allowed_citations = _allowed_citations_from_retrieval(retrieval)
    governing = [
        item for item in result.get("governing_citations", []) if isinstance(item, str) and item in allowed_citations
    ]
    if not governing:
        return None

    return {
        "provider": provider,
        "model": _reasoning_model_name(provider),
        "direct_answer": _normalize_space(result.get("direct_answer")),
        "bottom_line": _normalize_space(result.get("bottom_line")),
        "why": [item for item in result.get("why", []) if _normalize_space(item)],
        "gaps": [item for item in result.get("gaps", []) if _normalize_space(item)],
        "governing_citations": governing,
        "follow_ups": [item for item in result.get("follow_ups", []) if _normalize_space(item)][:3],
        "per_pack_findings": [
            {
                "standard_id": _normalize_space(item.get("standard_id")),
                "finding": _normalize_space(item.get("finding")),
                "citations": [
                    citation
                    for citation in item.get("citations", [])
                    if isinstance(citation, str) and citation in allowed_citations
                ],
            }
            for item in result.get("per_pack_findings", [])
            if isinstance(item, dict)
        ],
    }


def _maybe_run_llm_summary(
    *,
    query: str,
    gatekeeper: dict[str, Any],
    llm_reasoning: dict[str, Any],
) -> dict[str, Any] | None:
    provider = _chat_model_provider()
    if not provider:
        return None

    payload = {
        "query": query,
        "intent": gatekeeper["intent"],
        "compare_mode": gatekeeper["compare_mode"],
        "reasoning": llm_reasoning,
    }
    try:
        result = _call_model_json(
            provider=provider,
            model=_summary_model_name(provider),
            system_prompt=_llm_summary_system_prompt(),
            user_message=json.dumps(payload, indent=2),
            max_tokens=int(os.environ.get("ORACLE_CHAT_SUMMARY_MAX_TOKENS", "1200")),
        )
    except Exception as exc:
        LOGGER.warning("Oracle summary model failed; using deterministic summary: %s", exc)
        return None

    allowed = set(llm_reasoning["governing_citations"])
    citations = [
        item for item in result.get("citations", []) if isinstance(item, str) and item in allowed
    ]
    answer_text = _normalize_space(result.get("answer_text"))
    if not answer_text or not citations:
        return None
    return {
        "provider": provider,
        "model": _summary_model_name(provider),
        "answer_text": answer_text,
        "citations": citations,
        "follow_ups": [
            item for item in result.get("follow_ups", []) if _normalize_space(item)
        ][:3],
    }


def _validate_llm_reasoning_output(
    llm_reasoning: dict[str, Any],
    retrieval: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if not _normalize_space(llm_reasoning.get("direct_answer")) and not _normalize_space(
        llm_reasoning.get("bottom_line")
    ):
        failures.append("stage_3_missing_answer")

    allowed_citations = _allowed_citations_from_retrieval(retrieval)
    governing = llm_reasoning.get("governing_citations", [])
    if not governing:
        failures.append("stage_3_missing_citations")
    elif any(citation not in allowed_citations for citation in governing):
        failures.append("stage_3_unknown_citation")

    for field in ("why", "gaps", "follow_ups"):
        value = llm_reasoning.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            failures.append(f"stage_3_invalid_{field}")

    per_pack = llm_reasoning.get("per_pack_findings", [])
    if per_pack and not isinstance(per_pack, list):
        failures.append("stage_3_invalid_per_pack_findings")
    elif isinstance(per_pack, list):
        for item in per_pack:
            if not isinstance(item, dict):
                failures.append("stage_3_invalid_per_pack_findings")
                break
            citations = item.get("citations", [])
            if not isinstance(citations, list) or any(citation not in allowed_citations for citation in citations):
                failures.append("stage_3_invalid_per_pack_citations")
                break

    return failures


def _validate_llm_summary_output(
    llm_summary: dict[str, Any],
    llm_reasoning: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    answer_text = _normalize_space(llm_summary.get("answer_text"))
    if not answer_text:
        failures.append("stage_4_missing_answer")
    elif _PROHIBITED_DECISION_LANGUAGE_PATTERN.search(answer_text):
        failures.append("stage_4_prohibited_decision_language")

    allowed_citations = set(llm_reasoning.get("governing_citations", []))
    citations = llm_summary.get("citations", [])
    if not citations:
        failures.append("stage_4_missing_citations")
    elif any(citation not in allowed_citations for citation in citations):
        failures.append("stage_4_unknown_citation")

    follow_ups = llm_summary.get("follow_ups", [])
    if follow_ups and (
        not isinstance(follow_ups, list) or any(not isinstance(item, str) for item in follow_ups)
    ):
        failures.append("stage_4_invalid_follow_ups")

    return failures


def _gatekeep_query(query: str, pack_names: list[str], compare_only: bool) -> dict[str, Any]:
    if _APPROVAL_PATTERN.search(query):
        return {
            "status": "REFUSE",
            "intent": None,
            "normalized_query": query,
            "selected_packs": list(pack_names),
            "compare_mode": compare_only,
            "filters": {
                "section": _SECTION_PATTERN.search(query).group(1)
                if _SECTION_PATTERN.search(query)
                else None,
                "table_note": (
                    f"table {_TABLE_NOTE_PATTERN.search(query).group(1)} note {_TABLE_NOTE_PATTERN.search(query).group(2)}"
                    if _TABLE_NOTE_PATTERN.search(query)
                    else None
                ),
            },
            "refusal_category": "approval",
            "refusal_reason": (
                "Oracle can surface governing clauses and evidence paths, but it does not issue final approval, "
                "certification, waiver, or sign-off decisions."
            ),
        }

    if not pack_names:
        return {
            "status": "INSUFFICIENT_DATA",
            "intent": None,
            "normalized_query": query,
            "selected_packs": [],
            "compare_mode": compare_only,
            "filters": {"section": None, "table_note": None},
            "refusal_category": None,
            "refusal_reason": None,
            "error": "Select at least one authority pack before chatting. Oracle stays grounded in the packs you pick.",
        }

    intent = "general"
    if compare_only or _COMPARE_PATTERN.search(query):
        intent = "comparison"
    elif _is_clause_lookup_query(query):
        intent = "clause_lookup"
    elif _is_yes_no_query(query):
        intent = "yes_no"

    section_match = _SECTION_PATTERN.search(query)
    table_note_match = _TABLE_NOTE_PATTERN.search(query)

    return {
        "status": "PASS",
        "intent": intent,
        "normalized_query": query,
        "selected_packs": list(pack_names),
        "compare_mode": bool(compare_only or intent == "comparison"),
        "filters": {
            "section": _normalize_space(section_match.group(1)) if section_match else None,
            "table_note": (
                f"table {table_note_match.group(1)} note {table_note_match.group(2)}"
                if table_note_match
                else None
            ),
        },
        "refusal_category": None,
        "refusal_reason": None,
    }


def _retrieve_chat_context(gatekeeper: dict[str, Any], pack_dir: Path) -> dict[str, Any]:
    selected_packs = gatekeeper["selected_packs"]
    query = gatekeeper["normalized_query"]
    compare_mode = bool(gatekeeper["compare_mode"])
    packs_queried: list[dict[str, Any]] = []
    loaded_packs: list[ChatPack] = []

    for pack_name in selected_packs:
        try:
            pack = load_chat_pack(pack_name, pack_dir)
        except Exception as exc:
            packs_queried.append(
                {
                    "pack_slug": pack_name,
                    "load_status": "error",
                    "load_error": str(exc),
                }
            )
            continue

        loaded_packs.append(pack)
        packs_queried.append(
            {
                "pack_slug": pack.pack_slug,
                "standard_id": pack.standard_id,
                "standard_title": pack.standard_title,
                "load_status": "ok",
            }
        )

    if not loaded_packs:
        return {
            "status": "INSUFFICIENT_DATA",
            "error": "None of the selected packs could be loaded for Oracle chat.",
            "packs_queried": packs_queried,
            "compare_mode": compare_mode,
        }

    if len(loaded_packs) > 1 and not compare_mode:
        return {
            "status": "INSUFFICIENT_DATA",
            "error": (
                "Multiple packs are selected. Narrow to one pack for clause lookup or turn on compare mode to chat across selected standards."
            ),
            "packs_queried": packs_queried,
            "compare_mode": compare_mode,
            "loaded_packs": loaded_packs,
        }

    if compare_mode:
        pack_findings: list[dict[str, Any]] = []
        for pack in loaded_packs[:2]:
            matches = _dedupe_rules(_rank_rules(query, pack.rules), 3)
            pack_findings.append({"pack": pack, "matches": matches})

        if not any(item["matches"] for item in pack_findings):
            return {
                "status": "INSUFFICIENT_DATA",
                "error": "I did not find grounded requirement matches for that topic in the selected standards.",
                "packs_queried": packs_queried,
                "compare_mode": True,
                "pack_findings": pack_findings,
            }

        return {
            "status": "PASS",
            "packs_queried": packs_queried,
            "compare_mode": True,
            "pack_findings": pack_findings,
        }

    pack = loaded_packs[0]
    matches = _rank_rules(query, pack.rules)
    if not matches:
        return {
            "status": "INSUFFICIENT_DATA",
            "error": (
                f"I found {pack.standard_id}, but I did not find a grounded requirement match for that topic. "
                "Narrow this by section, table note, appendix, or part family."
            ),
            "packs_queried": packs_queried,
            "compare_mode": False,
            "pack": pack,
            "matches": [],
        }

    return {
        "status": "PASS",
        "packs_queried": packs_queried,
        "compare_mode": False,
        "pack": pack,
        "matches": matches,
    }


def _reason_about_chat_context(query: str, gatekeeper: dict[str, Any], retrieval: dict[str, Any]) -> dict[str, Any]:
    if retrieval["compare_mode"]:
        pack_reasoning: list[dict[str, Any]] = []
        for finding in retrieval["pack_findings"]:
            pack = finding["pack"]
            top_matches = finding["matches"]
            pack_reasoning.append(
                {
                    "pack": pack,
                    "top_matches": top_matches,
                    "evidence_assessment": "supported" if top_matches else "insufficient_data",
                    "bottom_line": (
                        f"{pack.standard_id} contains grounded rules for this topic."
                        if top_matches
                        else f"{pack.standard_id} did not surface grounded rules for this topic."
                    ),
                }
            )
        return {
            "status": "PASS",
            "answer_type": "comparison",
            "pack_reasoning": pack_reasoning,
            "retrieval_coverage": "partial"
            if any(item.get("load_status") == "error" for item in retrieval["packs_queried"])
            else "complete",
        }

    pack = retrieval["pack"]
    matches = retrieval["matches"]
    top_matches = _dedupe_rules(matches, 5 if gatekeeper["intent"] == "clause_lookup" else 3)
    return {
        "status": "PASS",
        "answer_type": "lookup" if gatekeeper["intent"] == "clause_lookup" else gatekeeper["intent"],
        "pack": pack,
        "top_matches": top_matches,
        "evidence_assessment": "supported",
        "retrieval_coverage": "complete",
        "bottom_line": (
            "If the scope insertion changes the work and carries cost or funding consequences, the retrieved rules point you into formal TOCR handling."
            if _is_scope_funding_query(query)
            else (
                f"{pack.standard_id} contains grounded rules that answer this question."
                if gatekeeper["intent"] != "clause_lookup"
                else f"{pack.standard_id} contains grounded governing clauses for this topic."
            )
        ),
        "gaps": (
            ["The question does not say whether the cost impact was formally documented."]
            if _is_scope_funding_query(query)
            else []
        ),
    }


def _build_single_pack_synthesis(
    query: str,
    pack: ChatPack,
    matches: list[tuple[ChatRule, int]],
    *,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    top_matches = _dedupe_rules(matches, 3)
    citations = [_citation(rule) for rule, _score in top_matches]
    follow_ups = [
        f"Show me the exact clause text for {citations[0]}.",
        f"What would make this compliant under {pack.standard_id}?",
    ]
    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=query,
            intent="lookup",
            selected_packs=[pack.pack_slug],
            compare_only=False,
            review_only=False,
            authority_basis=[pack.standard_id],
            citations=citations,
            evidence=[_evidence_item(rule=rule, score=score) for rule, score in top_matches],
            follow_ups=follow_ups,
            draft_answer_text=_render_grounded_pack_answer(
                query=query,
                pack=pack,
                top_matches=top_matches,
            ),
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
            metadata={
                "gaps": (
                    ["The question may need a narrower clause or section reference if your facts differ from the matched rule topic."]
                    if not _is_yes_no_query(query)
                    else []
                ),
            },
            wants_exact_text=_wants_exact_text(query),
        )
    )


def _compare_packs(
    message: str,
    packs: list[ChatPack],
    *,
    pack_findings: list[dict[str, Any]] | None = None,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    citations: list[str] = []
    findings = pack_findings or [{"pack": pack, "matches": _dedupe_rules(_rank_rules(message, pack.rules), 3)} for pack in packs]
    for finding in findings:
        for rule, _score in finding["matches"]:
            citation = _citation(rule)
            citations.append(citation)
    first = packs[0]
    follow_ups = [
        f"Which clause is stricter between {packs[0].standard_id} and {packs[1].standard_id}?",
        f"Show the exact governing text from {first.standard_id}.",
    ]
    evidence: list[OracleEvidenceItem] = []
    for finding in findings:
        pack = finding["pack"]
        matches = finding["matches"]
        for rule, score in matches[:2]:
            evidence.append(_evidence_item(rule=rule, score=score))
        if not matches:
            evidence.append(
                OracleEvidenceItem(
                    citation=pack.standard_id,
                    summary="No grounded requirement match found for this topic.",
                    standard_id=pack.standard_id,
                )
            )

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS" if citations else "INSUFFICIENT_DATA",
            query=message,
            intent="comparison",
            selected_packs=[pack.pack_slug for pack in packs],
            compare_only=True,
            review_only=False,
            authority_basis=[pack.standard_id for pack in packs],
            citations=citations or [pack.standard_id for pack in packs],
            evidence=evidence,
            follow_ups=follow_ups,
            draft_answer_text=_render_compare_answer(
                query=message,
                packs=packs,
                findings=findings,
            ),
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
        )
    )


def _build_clause_lookup_answer(
    query: str,
    pack: ChatPack,
    top_matches: list[tuple[ChatRule, int]],
    *,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    citations: list[str] = []
    for rule, _score in top_matches:
        citation = _citation(rule)
        citations.append(citation)

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=query,
            intent="clause_lookup",
            selected_packs=[pack.pack_slug],
            compare_only=False,
            review_only=False,
            authority_basis=[pack.standard_id],
            citations=citations,
            evidence=[_evidence_item(rule=rule, score=score) for rule, score in top_matches],
            follow_ups=[
                f"Show the exact requirement text from {citations[0]}.",
                f"List the top requirements in {pack.standard_id} for this topic.",
            ],
            draft_answer_text=_render_grounded_pack_answer(
                query=query,
                pack=pack,
                top_matches=top_matches,
            ),
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
            wants_exact_text=_wants_exact_text(query),
        )
    )


def _build_llm_guided_answer(
    *,
    llm_reasoning: dict[str, Any],
    llm_summary: dict[str, Any] | None,
    selected_packs: list[str],
    compare_only: bool,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any],
) -> dict[str, Any]:
    response_lines: list[str] = []
    if llm_summary:
        response_lines.append(llm_summary["answer_text"])
    else:
        if llm_reasoning.get("direct_answer"):
            response_lines.append(llm_reasoning["direct_answer"])
        if llm_reasoning.get("bottom_line"):
            response_lines.append(llm_reasoning["bottom_line"])
        if llm_reasoning.get("why"):
            response_lines.append("")
            response_lines.append("Why:")
            for item in llm_reasoning["why"][:3]:
                response_lines.append(f"- {item}")
        if llm_reasoning.get("gaps"):
            response_lines.append("")
            response_lines.append("Gaps:")
            for item in llm_reasoning["gaps"][:2]:
                response_lines.append(f"- {item}")
        if compare_only and llm_reasoning.get("per_pack_findings"):
            response_lines.append("")
            response_lines.append("Per pack:")
            for item in llm_reasoning["per_pack_findings"]:
                if item.get("standard_id") and item.get("finding"):
                    response_lines.append(f"- {item['standard_id']}: {item['finding']}")

    citations = llm_summary["citations"] if llm_summary else llm_reasoning["governing_citations"]
    follow_ups = (
        llm_summary["follow_ups"]
        if llm_summary and llm_summary.get("follow_ups")
        else llm_reasoning.get("follow_ups", [])
    )
    evidence: list[OracleEvidenceItem] = []
    retrieval = (stage_artifacts or {}).get("retrieval", {})
    match_groups = retrieval.get("matches_by_pack") or []
    for group in match_groups:
        for item in group.get("matches", [])[:2]:
            evidence.append(
                OracleEvidenceItem(
                    citation=item.get("display_citation", ""),
                    summary=item.get("requirement") or item.get("statement_text") or "",
                    statement_text=item.get("statement_text", ""),
                    topic=item.get("subject", ""),
                    standard_id=item.get("standard_id", ""),
                    score=item.get("score"),
                )
            )

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=(stage_artifacts or {}).get("gatekeeper", {}).get("normalized_query", ""),
            intent="comparison" if compare_only else "lookup",
            selected_packs=selected_packs,
            compare_only=compare_only,
            review_only=False,
            authority_basis=[],
            citations=citations,
            evidence=evidence,
            follow_ups=follow_ups,
            draft_answer_text="\n".join(line for line in response_lines if line is not None).strip(),
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
        )
    )


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
        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query="",
                intent="review_only" if review_only else "lookup",
                selected_packs=pack_names,
                compare_only=compare_only,
                review_only=review_only,
                missing_inputs=[
                    "A question, requirement, or draft clause to inspect.",
                ],
                draft_answer_text=(
                    "Oracle needs a question, requirement, or draft clause to inspect."
                    if review_only
                    else "Oracle needs a standards question to answer."
                ),
            )
        )

    if review_only:
        return _answer_review_only(query, compare_only)

    gatekeeper = _gatekeep_query(query, pack_names, compare_only)
    if gatekeeper["status"] == "REFUSE":
        return _emit_envelope(
            OracleChatEnvelope(
                status="REFUSE",
                query=query,
                intent="refusal",
                selected_packs=gatekeeper["selected_packs"],
                compare_only=bool(gatekeeper["compare_mode"]),
                review_only=False,
                draft_answer_text=gatekeeper["refusal_reason"],
                diagnostics={},
                stage_artifacts={"gatekeeper": gatekeeper},
            )
        )
    if gatekeeper["status"] == "INSUFFICIENT_DATA":
        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query=query,
                intent="lookup",
                selected_packs=gatekeeper["selected_packs"],
                compare_only=bool(gatekeeper["compare_mode"]),
                review_only=False,
                missing_inputs=[
                    "Select at least one authority pack for authority-grounded chat."
                ],
                draft_answer_text=gatekeeper["error"],
                stage_artifacts={"gatekeeper": gatekeeper},
            )
        )

    retrieval = _retrieve_chat_context(gatekeeper, pack_dir)
    if retrieval["status"] == "INSUFFICIENT_DATA":
        loaded_packs = retrieval.get("loaded_packs", [])
        follow_ups: list[str] = []
        citations: list[str] = []
        if loaded_packs:
            follow_ups = [
                f"Compare {loaded_packs[0].standard_id} and {loaded_packs[1].standard_id}.",
                f"Limit this question to {loaded_packs[0].standard_id}.",
            ]
            citations = [pack.standard_id for pack in loaded_packs[:2]]
        elif retrieval.get("pack"):
            pack = retrieval["pack"]
            follow_ups = [
                f"Show me the exact section in {pack.standard_id}.",
                f"List the top requirements in {pack.standard_id} for this topic.",
            ]
            citations = [pack.standard_id]

        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query=query,
                intent=gatekeeper["intent"],
                selected_packs=gatekeeper["selected_packs"],
                compare_only=bool(gatekeeper["compare_mode"]),
                review_only=False,
                authority_basis=citations,
                citations=citations,
                missing_inputs=[
                    "A narrower topic, section, table note, appendix, or a different selected pack."
                ],
                follow_ups=follow_ups,
                draft_answer_text=retrieval["error"],
                stage_artifacts={"gatekeeper": gatekeeper, "retrieval": retrieval},
            )
        )

    reasoning = _reason_about_chat_context(query, gatekeeper, retrieval)
    stage_artifacts = {
        "gatekeeper": gatekeeper,
        "retrieval": {
            "compare_mode": retrieval["compare_mode"],
            "packs_queried": retrieval["packs_queried"],
            "matches": [
                _serialize_rule(rule, score) for rule, score in retrieval.get("matches", [])
            ],
            "matches_by_pack": [
                {
                    "pack_slug": finding["pack"].pack_slug,
                    "standard_id": finding["pack"].standard_id,
                    "matches": [_serialize_rule(rule, score) for rule, score in finding["matches"]],
                }
                for finding in retrieval.get("pack_findings", [])
            ],
        },
        "reasoning": {
            "answer_type": reasoning["answer_type"],
            "retrieval_coverage": reasoning["retrieval_coverage"],
            "evidence_assessment": reasoning.get("evidence_assessment"),
        },
    }
    diagnostics: dict[str, Any] = {
        "fallback_used": False,
        "fallback_reason": None,
        "validation_failures": [],
    }
    chat_provider = _chat_model_provider()

    llm_reasoning = None
    llm_summary = None
    if gatekeeper["intent"] != "clause_lookup":
        llm_reasoning = _maybe_run_llm_reasoning(
            query=query,
            gatekeeper=gatekeeper,
            retrieval=retrieval,
        )
        if llm_reasoning:
            reasoning_failures = _validate_llm_reasoning_output(llm_reasoning, retrieval)
            if reasoning_failures:
                diagnostics["fallback_used"] = True
                diagnostics["fallback_reason"] = "stage_3_validation_failure"
                diagnostics["validation_failures"].extend(reasoning_failures)
                llm_reasoning = None
            else:
                stage_artifacts["reasoning"]["llm_provider"] = llm_reasoning["provider"]
                stage_artifacts["reasoning"]["llm_model"] = llm_reasoning["model"]
                llm_summary = _maybe_run_llm_summary(
                    query=query,
                    gatekeeper=gatekeeper,
                    llm_reasoning=llm_reasoning,
                )
                if llm_summary:
                    summary_failures = _validate_llm_summary_output(llm_summary, llm_reasoning)
                    if summary_failures:
                        diagnostics["fallback_used"] = True
                        diagnostics["fallback_reason"] = "stage_4_validation_failure"
                        diagnostics["validation_failures"].extend(summary_failures)
                        llm_summary = None
                    else:
                        stage_artifacts["summary"] = {
                            "llm_provider": llm_summary["provider"],
                            "llm_model": llm_summary["model"],
                        }
                else:
                    diagnostics["fallback_used"] = True
                    diagnostics["fallback_reason"] = "stage_4_failure"
        elif chat_provider:
            diagnostics["fallback_used"] = True
            diagnostics["fallback_reason"] = "stage_3_failure"

    if reasoning["answer_type"] == "comparison":
        if llm_reasoning:
            return _build_llm_guided_answer(
                llm_reasoning=llm_reasoning,
                llm_summary=llm_summary,
                selected_packs=gatekeeper["selected_packs"][:2],
                compare_only=True,
                evidence_assessment=reasoning.get("evidence_assessment"),
                diagnostics=diagnostics,
                stage_artifacts=stage_artifacts,
            )
        return _compare_packs(
            query,
            [item["pack"] for item in reasoning["pack_reasoning"]],
            pack_findings=[
                {"pack": item["pack"], "matches": item["top_matches"]}
                for item in reasoning["pack_reasoning"]
            ],
            evidence_assessment=reasoning.get("evidence_assessment"),
            diagnostics=diagnostics,
            stage_artifacts=stage_artifacts,
        )

    pack = reasoning["pack"]
    top_matches = reasoning["top_matches"]
    if gatekeeper["intent"] == "clause_lookup":
        return _build_clause_lookup_answer(
            query,
            pack,
            top_matches,
            evidence_assessment=reasoning.get("evidence_assessment"),
            diagnostics=diagnostics,
            stage_artifacts=stage_artifacts,
        )

    if llm_reasoning:
        return _build_llm_guided_answer(
            llm_reasoning=llm_reasoning,
            llm_summary=llm_summary,
            selected_packs=[pack.pack_slug],
            compare_only=False,
            evidence_assessment=reasoning.get("evidence_assessment"),
            diagnostics=diagnostics,
            stage_artifacts=stage_artifacts,
        )

    return _build_single_pack_synthesis(
        query,
        pack,
        top_matches,
        evidence_assessment=reasoning.get("evidence_assessment"),
        diagnostics=diagnostics,
        stage_artifacts=stage_artifacts,
    )
