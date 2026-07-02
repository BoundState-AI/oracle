"""
Module: oracle.chat_grader
Purpose: Deterministic safety/grounding gate for formatted Oracle chat output.

__safety_critical__: bool = True — safety gate for prohibited language in compliance output

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from oracle.chat_contract import OracleChatEnvelope

# WHY this gate exists: ORACLE is an advisory system, not a decision authority.
# If the output contains approval/certification language, a user might treat
# the response as an official sign-off rather than a draft recommendation.
# These specific words were chosen because they carry legal weight in NASA/DoD
# contracting — "approved", "certified", and "waived" are formal actions that
# only designated authorities (CO, COR, Safety) can take.
# False-positive refusals are strongly preferred over false-negative approvals.
_PROHIBITED_DECISION_LANGUAGE_PATTERN = re.compile(
    r"\b(?:approved?|approval|certif(?:y|ied|ication)|waiv(?:e|er|ed)|sign-?off|accepted?|greenlight(?:ed)?)\b",
    re.IGNORECASE,
)

# Public alias for cross-module import (used by chat_engine.py).
PROHIBITED_DECISION_LANGUAGE_PATTERN = _PROHIBITED_DECISION_LANGUAGE_PATTERN

# WHY 12: exempt spans must be long enough to be recognizable rule quotes.
# A trivial fragment ("Approved") in evidence must not blanket-exempt real
# Oracle-asserted decision language elsewhere in the response.
_MIN_VERBATIM_SPAN_CHARS = 12


def strip_verbatim_spans(text: str, spans: Iterable[str]) -> str:
    """Remove verbatim source-quote spans from text before language screening.

    WHY: rule text quoted from the pack may legitimately contain words like
    "approval" (e.g. "The process shall be subject to review and approval of
    the RFCB"). Quoting the authority is grounded behavior — only language the
    Oracle asserts in its own voice may trip the prohibited-decision gate.
    Matching is case-insensitive because the renderer may lowercase the first
    letter of an embedded quote.
    """
    stripped = text
    for raw_span in spans:
        span = str(raw_span or "").strip().rstrip(".")
        if len(span) < _MIN_VERBATIM_SPAN_CHARS:
            continue
        stripped = re.sub(re.escape(span), " ", stripped, flags=re.IGNORECASE)
    return stripped


def _evidence_spans(envelope: OracleChatEnvelope) -> list[str]:
    spans: list[str] = []
    for item in envelope.evidence:
        spans.extend((item.statement_text, item.summary))
    return spans


@dataclass
class OracleChatGrade:
    passed: bool
    failures: list[str] = field(default_factory=list)


def grade_chat_response(text: str, envelope: OracleChatEnvelope) -> OracleChatGrade:
    failures: list[str] = []
    text_lower = text.lower()

    if envelope.status != "REFUSE":
        screened = strip_verbatim_spans(text, _evidence_spans(envelope))
        if _PROHIBITED_DECISION_LANGUAGE_PATTERN.search(screened):
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
