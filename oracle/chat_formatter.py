"""
Module: oracle.chat_formatter
Purpose: Oracle-native response formatter that turns a canonical chat envelope
         into operator-facing prose with grounded citations.

__safety_critical__: bool = True — produces the operator-facing compliance
prose; its allow_draft_answer=False mode is the grader's fallback surface.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

from oracle.chat_contract import OracleChatEnvelope


def format_chat_response(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool = True,
) -> str:
    if envelope.status == "REFUSE":
        return envelope.draft_answer_text.strip()

    if envelope.review_only:
        return _format_review_only(envelope, allow_draft_answer=allow_draft_answer)
    if envelope.compare_only:
        return _format_comparison(envelope, allow_draft_answer=allow_draft_answer)
    if envelope.status == "INSUFFICIENT_DATA":
        return _format_insufficient_data(envelope, allow_draft_answer=allow_draft_answer)
    return _format_grounded_answer(envelope, allow_draft_answer=allow_draft_answer)


def _draft_text(envelope: OracleChatEnvelope, *, allow_draft_answer: bool) -> str:
    if allow_draft_answer and envelope.draft_answer_text.strip():
        return envelope.draft_answer_text.strip()
    return ""


def _lead_text(envelope: OracleChatEnvelope, *, allow_draft_answer: bool) -> str:
    draft = _draft_text(envelope, allow_draft_answer=allow_draft_answer)
    if draft:
        return draft
    if envelope.evidence:
        return envelope.evidence[0].summary
    return ""


def _format_grounded_answer(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
    draft = _draft_text(envelope, allow_draft_answer=allow_draft_answer)
    if draft:
        return draft

    lines: list[str] = []
    lead = _lead_text(envelope, allow_draft_answer=allow_draft_answer)
    if lead:
        lines.append(lead)
    elif envelope.authority_basis:
        lines.append(f"Grounded answer from {envelope.authority_basis[0]}.")

    if len(envelope.evidence) > 1:
        lines.append("")
        lines.append("Also relevant here:")
        for item in envelope.evidence[1:3]:
            detail = f"- {item.summary}"
            if envelope.wants_exact_text and item.statement_text:
                detail += f" Exact text: {item.statement_text}"
            lines.append(detail)

    if envelope.assumptions:
        lines.append("")
        lines.append("Assumptions I am using:")
        for item in envelope.assumptions[:3]:
            lines.append(f"- {item}")

    if envelope.metadata.get("gaps"):
        lines.append("")
        lines.append("What may still need tightening:")
        for item in envelope.metadata["gaps"][:3]:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()


def _format_comparison(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
    draft = _draft_text(envelope, allow_draft_answer=allow_draft_answer)
    if draft:
        return draft

    lines: list[str] = ["Comparison across selected standards."]
    lead = _lead_text(envelope, allow_draft_answer=allow_draft_answer)
    if lead:
        lines.extend(["", lead])

    grouped: dict[str, list] = {}
    for item in envelope.evidence:
        grouped.setdefault(item.standard_id or "Selected standard", []).append(item)

    for standard_id, items in grouped.items():
        lines.append("")
        lines.append(f"{standard_id}:")
        for item in items[:2]:
            lines.append(f"- {item.summary}")

    return "\n".join(lines).strip()


def _format_review_only(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
    draft = _draft_text(envelope, allow_draft_answer=allow_draft_answer)
    if draft:
        return draft

    lines = ["Review-only assessment. No authority packs were applied."]
    lead = _lead_text(envelope, allow_draft_answer=allow_draft_answer)
    if lead and lead != lines[0]:
        lines.extend(["", lead])

    if envelope.evidence:
        lines.append("")
        lines.append("Top issues:")
        for item in envelope.evidence[:3]:
            lines.append(f"- {item.summary}")

    return "\n".join(lines).strip()


def _format_insufficient_data(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
    draft = _draft_text(envelope, allow_draft_answer=allow_draft_answer)
    if draft:
        return draft

    lines = [
        _lead_text(envelope, allow_draft_answer=allow_draft_answer)
        or "I do not have enough grounded support to answer that from the selected pack context.",
    ]

    if envelope.missing_inputs:
        lines.append("")
        lines.append("What I need to tighten this:")
        for item in envelope.missing_inputs[:4]:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()
