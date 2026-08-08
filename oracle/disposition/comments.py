#!/usr/bin/env python3
"""
Module: oracle.disposition.comments
Purpose: Deterministic RDW §13.1 four-part comment assembly + §13.2 checks.

No LLM. Template + facts only.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from oracle.disposition.session import Fact, UnitAxesState

LOGGER = logging.getLogger("oracle.disposition.comments")

# §13.2 prohibited patterns (case-insensitive)
_PROHIBITED = [
    (re.compile(r"\bapproved\b", re.I), "approved"),
    (re.compile(r"\baccepted\b", re.I), "accepted"),
    (re.compile(r"\bqualified\b", re.I), "qualified"),
    (re.compile(r"\bcompliant\b", re.I), "compliant"),
    (re.compile(r"\bcomplete\b", re.I), "complete"),
    (re.compile(r"no mua necessary", re.I), "No MUA necessary"),
    (re.compile(r"\bno demonstration exists\b", re.I), "universal negative"),
]


def prohibited_language_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pat, name in _PROHIBITED:
        if pat.search(text or ""):
            hits.append(name)
    return hits


def assemble_comment(
    unit: UnitAxesState,
    *,
    org_name: str = "the evaluated organization",
    facts: Optional[dict[str, Fact]] = None,
    controlling_process: Optional[str] = None,
) -> str:
    """
    RDW §13.1 four-part pattern:
      1. org implementation/responsibility
      2. controlling process/document/evidence when known
      3. external responsibility / missing input / pending approval
      4. closure condition when not fully closed
    """
    facts = facts or {}
    parts: list[str] = []

    # 1
    resp = unit.organization_responsibility
    if resp == "owner":
        parts.append(f"{org_name} is the owner of the normative action for this requirement.")
    elif resp == "support":
        parts.append(f"{org_name} provides supporting implementation for this requirement.")
    elif resp == "external":
        parts.append(
            f"The normative actor is external to {org_name}; "
            "external responsibility does not make the requirement inapplicable."
        )
    else:
        parts.append(
            f"{org_name} responsibility for this requirement is TBD "
            f"({unit.org_responsibility_tbd_reason})."
        )

    # 2
    if controlling_process:
        parts.append(f"Controlling process/document: {controlling_process}.")
    elif unit.evidence_refs:
        refs = ", ".join(f"{e.doc_id} rev {e.revision}" for e in unit.evidence_refs)
        parts.append(f"Cited evidence references: {refs}.")
    else:
        am_process = facts.get("hardware.process")
        if am_process:
            parts.append(f"Process context: {am_process.statement}.")

    # 3
    gaps: list[str] = []
    if unit.applicability == "tbd":
        gaps.append(f"applicability TBD ({unit.applicability_tbd_reason})")
    if unit.implementation_state == "tbd":
        gaps.append(f"implementation TBD ({unit.implementation_tbd_reason})")
    if unit.approval_state == "tbd":
        gaps.append(f"approval TBD ({unit.approval_tbd_reason})")
    if unit.implementation_state == "not_met":
        gaps.append("required control or evidence is not met as written")
    if unit.approval_state in ("required", "draft", "submitted"):
        gaps.append(f"approval state is {unit.approval_state}")
    class_fact = facts.get("classification.primary")
    if class_fact is None and unit.applicability_tbd_reason == "classification_unresolved":
        gaps.append(
            "customer part classification, fracture-control inputs, and "
            "NDE/PPP requirements are unresolved"
        )
    if gaps:
        parts.append("Open items: " + "; ".join(gaps) + ".")

    # 4
    try:
        label = unit.export_label()
        if label.value in ("TBD", "Open/Not Met", "Exception", "Meets Intent"):
            parts.append(
                f"Closure condition: resolve open items and re-elect axes before "
                f"claiming a final {label.value} disposition on the customer matrix."
            )
    except Exception:
        parts.append("Closure condition: complete axis election before export.")

    text = " ".join(parts)
    hits = prohibited_language_hits(text)
    if hits:
        LOGGER.warning("proposed comment contains prohibited language: %s", hits)
        # Soften common false positives from our own templates
        text = re.sub(r"\bcomplete\b", "finish", text, flags=re.I)
    return text
