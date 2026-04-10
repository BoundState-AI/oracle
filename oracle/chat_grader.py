"""
Module: oracle.chat_grader
Purpose: Deterministic safety/grounding gate for formatted Oracle chat output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from oracle.chat_contract import OracleChatEnvelope

_PROHIBITED_DECISION_LANGUAGE_PATTERN = re.compile(
    r"\b(?:approved?|approval|certif(?:y|ied|ication)|waiv(?:e|er|ed)|sign-?off|accepted?|greenlight(?:ed)?)\b",
    re.IGNORECASE,
)


@dataclass
class OracleChatGrade:
    passed: bool
    failures: list[str] = field(default_factory=list)


def grade_chat_response(text: str, envelope: OracleChatEnvelope) -> OracleChatGrade:
    failures: list[str] = []
    text_lower = text.lower()

    citations = envelope.citations_or_authority()
    if citations:
        missing = [citation for citation in citations if citation.lower() not in text_lower]
        if missing:
            failures.append("missing_citations")

    if envelope.status != "REFUSE" and _PROHIBITED_DECISION_LANGUAGE_PATTERN.search(text):
        failures.append("prohibited_decision_language")

    if envelope.status == "INSUFFICIENT_DATA" and envelope.missing_inputs:
        keywords_found = 0
        for item in envelope.missing_inputs:
            words = [word for word in str(item).lower().split() if len(word) > 3]
            if any(word in text_lower for word in words):
                keywords_found += 1
        if keywords_found == 0:
            failures.append("missing_inputs_not_surfaced")

    if envelope.review_only and "review-only" not in text_lower:
        failures.append("review_only_not_labeled")

    if envelope.compare_only:
        standard_ids = {item.standard_id for item in envelope.evidence if item.standard_id}
        if standard_ids and any(standard_id.lower() not in text_lower for standard_id in standard_ids):
            failures.append("comparison_missing_standard")

    return OracleChatGrade(passed=not failures, failures=failures)
