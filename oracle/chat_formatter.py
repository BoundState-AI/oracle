"""
Module: oracle.chat_formatter
Purpose: Oracle-native response formatter that turns a canonical chat envelope
         into operator-facing prose with grounded citations.
"""

from __future__ import annotations

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


def _lead_text(envelope: OracleChatEnvelope, *, allow_draft_answer: bool) -> str:
    if allow_draft_answer and envelope.draft_answer_text.strip():
        return envelope.draft_answer_text.strip()
    if envelope.evidence:
        return envelope.evidence[0].summary
    return ""


def _format_grounded_answer(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
    lines: list[str] = []
    lead = _lead_text(envelope, allow_draft_answer=allow_draft_answer)
    if lead:
        lines.append(lead)
    elif envelope.authority_basis:
        lines.append(f"Grounded answer from {envelope.authority_basis[0]}.")

    if envelope.evidence:
        lines.append("")
        lines.append("Why:")
        for item in envelope.evidence[:3]:
            detail = f"- {item.summary} ({item.citation})"
            if envelope.wants_exact_text and item.statement_text:
                detail += f" Exact text: {item.statement_text}"
            lines.append(detail)

    if envelope.assumptions:
        lines.append("")
        lines.append("Assumptions:")
        for item in envelope.assumptions[:3]:
            lines.append(f"- {item}")

    if envelope.metadata.get("gaps"):
        lines.append("")
        lines.append("Gaps:")
        for item in envelope.metadata["gaps"][:3]:
            lines.append(f"- {item}")

    citations = envelope.citations_or_authority()
    if citations:
        lines.append("")
        lines.append("Citations:")
        for citation in citations:
            lines.append(f"- {citation}")

    if envelope.follow_ups:
        lines.append("")
        lines.append("Next moves:")
        for item in envelope.follow_ups[:3]:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()


def _format_comparison(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
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
            lines.append(f"- {item.summary} ({item.citation})")

    citations = envelope.citations_or_authority()
    if citations:
        lines.append("")
        lines.append("Citations:")
        for citation in citations:
            lines.append(f"- {citation}")

    if envelope.follow_ups:
        lines.append("")
        lines.append("Next moves:")
        for item in envelope.follow_ups[:3]:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()


def _format_review_only(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
    lines = ["Review-only assessment. No authority packs were applied."]
    lead = _lead_text(envelope, allow_draft_answer=allow_draft_answer)
    if lead and lead != lines[0]:
        lines.extend(["", lead])

    if envelope.evidence:
        lines.append("")
        lines.append("Top issues:")
        for item in envelope.evidence[:3]:
            lines.append(f"- {item.summary}")

    if envelope.follow_ups:
        lines.append("")
        lines.append("Next moves:")
        for item in envelope.follow_ups[:3]:
            lines.append(f"- {item}")

    citations = envelope.citations_or_authority()
    if citations:
        lines.append("")
        lines.append("Review basis:")
        for citation in citations:
            lines.append(f"- {citation}")

    return "\n".join(lines).strip()


def _format_insufficient_data(
    envelope: OracleChatEnvelope,
    *,
    allow_draft_answer: bool,
) -> str:
    lines = [
        _lead_text(envelope, allow_draft_answer=allow_draft_answer)
        or "I do not have enough grounded support to answer that from the selected pack context.",
    ]

    if envelope.missing_inputs:
        lines.append("")
        lines.append("What I need to tighten this:")
        for item in envelope.missing_inputs[:4]:
            lines.append(f"- {item}")

    citations = envelope.citations_or_authority()
    if citations:
        lines.append("")
        lines.append("Scope checked:")
        for citation in citations:
            lines.append(f"- {citation}")

    if envelope.follow_ups:
        lines.append("")
        lines.append("Next moves:")
        for item in envelope.follow_ups[:3]:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()
