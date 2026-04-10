"""
Module: oracle.chat_contract
Purpose: Canonical Oracle chat envelope shared by retrieval, formatter,
         and grader stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    status: str
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

    def citations_or_authority(self) -> list[str]:
        return self.citations or self.authority_basis
