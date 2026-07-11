"""
Module: oracle.chat_contract
Purpose: Canonical Oracle chat envelope shared by retrieval, formatter,
         and grader stages.

__safety_critical__: bool = True — the envelope status drives REFUSE handling
and grading; a malformed status would silently bypass both gates.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: True
"""

from __future__ import annotations

__safety_critical__: bool = True

from dataclasses import dataclass, field
from typing import Any, Literal

OracleChatStatus = Literal["PASS", "REFUSE", "INSUFFICIENT_DATA"]

# WHY a runtime tuple next to the Literal: dataclasses do not validate Literal
# annotations at runtime, and a typo'd status (e.g. "REFUSED") would skip the
# REFUSE branch in the formatter AND the grader's prohibited-language gate.
# Fail closed at construction instead.
_ALLOWED_STATUSES: tuple[str, ...] = ("PASS", "REFUSE", "INSUFFICIENT_DATA")


@dataclass(frozen=True)
class OracleEvidenceItem:
    citation: str
    summary: str
    statement_text: str = ""
    topic: str = ""
    standard_id: str = ""
    score: int | None = None


@dataclass
class OracleChatEnvelope:
    status: OracleChatStatus
    query: str
    intent: str
    selected_packs: list[str] = field(default_factory=list)
    compare_only: bool = False
    review_only: bool = False
    advisory_only: bool = True
    authority_basis: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    evidence: list[OracleEvidenceItem] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    draft_answer_text: str = ""
    evidence_assessment: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    stage_artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    wants_exact_text: bool = False

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_STATUSES:
            raise ValueError(
                f"Invalid Oracle chat envelope status {self.status!r}; "
                f"expected one of {_ALLOWED_STATUSES}."
            )

    def citations_or_authority(self) -> list[str]:
        return self.citations or self.authority_basis
