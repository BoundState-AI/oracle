#!/usr/bin/env python3
"""
Module: oracle.disposition.advisor
Purpose: Stage B — AdvisorService (explain / propose / suggest_closure).

DeterministicAdvisor is the test default (keyless). LiveAdvisor is opt-in
via RDW_ADVISOR_MODEL / Anthropic. All outputs proposed-only; never change
axes without operator attestation. Grounded only in supplied context (D-7).

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from oracle.disposition.actions import ActionRecord
from oracle.disposition.codes import ProposalBand
from oracle.disposition.comments import prohibited_language_hits
from oracle.disposition.decision import evaluate_unit
from oracle.disposition.graph import DependencyGraph
from oracle.disposition.rulepack import RequirementRecord
from oracle.disposition.session import Fact, UnitAxesState

LOGGER = logging.getLogger("oracle.disposition.advisor")

PROMPT_VERSION = "rdw-advisor/v1"


class AdvisorContext(BaseModel):
    """Evidence bundle supplied to the advisor (never model memory)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    shall_text: str
    locator: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    notes: str = ""
    facts: dict[str, str] = Field(default_factory=dict)  # key -> statement
    axes_summary: dict[str, Any] = Field(default_factory=dict)
    blocked_labels: dict[str, str] = Field(default_factory=dict)
    current_label: Optional[str] = None
    why_not_meet: tuple[str, ...] = ()


class ExplainResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    interpretation: str  # labeled *interpretation* at render
    band: ProposalBand = ProposalBand.MEDIUM
    basis: str = ""
    model_id: str = "deterministic"
    prompt_version: str = PROMPT_VERSION
    context_hash: str = ""
    output_hash: str = ""


class ProposeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    band: ProposalBand
    basis: str
    proposed_axes: Optional[dict[str, Any]] = None  # None when LOW / must_not_propose
    proposed_label: Optional[str] = None
    questions: tuple[str, ...] = ()
    model_id: str = "deterministic"
    prompt_version: str = PROMPT_VERSION
    context_hash: str = ""
    output_hash: str = ""
    refused_labels: dict[str, str] = Field(default_factory=dict)


class ClosureSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    actions: tuple[ActionRecord, ...] = ()
    evidence_requests: tuple[str, ...] = ()
    unresolved_dependencies: tuple[str, ...] = ()
    band: ProposalBand = ProposalBand.MEDIUM
    basis: str = ""
    model_id: str = "deterministic"
    prompt_version: str = PROMPT_VERSION
    context_hash: str = ""
    output_hash: str = ""


class AdvisorError(Exception):
    """Advisor refused output (grader / §13.2 / policy)."""


def context_hash(ctx: AdvisorContext) -> str:
    material = ctx.model_dump_json()
    return f"sha256:{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def output_hash(payload: Any) -> str:
    if hasattr(payload, "model_dump_json"):
        raw = payload.model_dump_json()
    else:
        raw = json.dumps(payload, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def grade_claims_vs_facts(
    text: str,
    facts: dict[str, Fact] | dict[str, str],
) -> list[str]:
    """
    Deterministic grader: refuse drafts that claim compliance/closure when
    the fact ledger does not support it.
    """
    hits: list[str] = []
    low = (text or "").lower()
    # Absolute compliance claims without a confirmed fact
    forbidden_if_unbacked = (
        "fully compliant",
        "completely meets",
        "requirement is met",
        "closed with evidence on file",
    )
    fact_vals = []
    for v in facts.values():
        if isinstance(v, Fact):
            fact_vals.append(v.statement.lower())
        else:
            fact_vals.append(str(v).lower())
    ledger = " ".join(fact_vals)
    for phrase in forbidden_if_unbacked:
        if phrase in low and phrase not in ledger:
            hits.append(f"ungrounded claim: {phrase!r}")
    return hits


def scrub_advisor_text(text: str, facts: dict[str, Fact] | dict[str, str]) -> str:
    """Run §13.2 + grader; raise AdvisorError on refusal."""
    hits = prohibited_language_hits(text)
    if hits:
        raise AdvisorError(f"§13.2 prohibited language: {hits}")
    grade = grade_claims_vs_facts(text, facts)
    if grade:
        raise AdvisorError(f"grader refusal: {grade}")
    return text


def build_context(
    unit: UnitAxesState,
    record: Optional[RequirementRecord],
    facts: dict[str, Fact],
    *,
    graph: Optional[DependencyGraph] = None,
    has_evidence: bool = False,
) -> AdvisorContext:
    graph = graph or DependencyGraph.from_seeds()
    decision = evaluate_unit(
        unit,
        facts=facts,
        graph=graph,
        has_scope_rationale=bool(unit.scope_citation),
        has_evidence_for_meet=has_evidence,
    )
    fact_map = {
        k: (f.statement + (" [assumed]" if f.assumed else ""))
        for k, f in facts.items()
    }
    return AdvisorContext(
        unit_id=unit.unit_id,
        shall_text=record.shall_text if record else "",
        locator=record.locator.model_dump() if record else {},
        rationale=record.rationale if record else "",
        notes=record.notes if record else "",
        facts=fact_map,
        axes_summary={
            "applicability": unit.applicability,
            "obligated_actor": unit.obligated_actor,
            "organization_responsibility": unit.organization_responsibility,
            "implementation_state": unit.implementation_state,
            "approval_state": unit.approval_state,
        },
        blocked_labels=dict(decision.blocked),
        current_label=decision.current_label,
        why_not_meet=decision.blockers_meet,
    )


class AdvisorService(ABC):
    @abstractmethod
    def explain(self, ctx: AdvisorContext) -> ExplainResult: ...

    @abstractmethod
    def propose(self, ctx: AdvisorContext) -> ProposeResult: ...

    @abstractmethod
    def suggest_closure(self, ctx: AdvisorContext) -> ClosureSuggestion: ...


class DeterministicAdvisor(AdvisorService):
    """Template-based advisor for keyless tests and offline use."""

    model_id = "deterministic"

    def explain(self, ctx: AdvisorContext) -> ExplainResult:
        ch = context_hash(ctx)
        parts = [
            f"This requirement ({ctx.unit_id}) asks the organization to satisfy "
            f"the following obligation as written in the standard.",
        ]
        if ctx.rationale:
            parts.append(f"Published rationale: {ctx.rationale[:500]}")
        if ctx.why_not_meet:
            parts.append(
                "Current blockers for Meet: " + "; ".join(ctx.why_not_meet[:5])
            )
        if ctx.facts:
            parts.append(
                "Known project facts considered: "
                + "; ".join(f"{k}={v}" for k, v in list(ctx.facts.items())[:8])
            )
        text = scrub_advisor_text(" ".join(parts), ctx.facts)
        res = ExplainResult(
            unit_id=ctx.unit_id,
            interpretation=text,
            band=ProposalBand.MEDIUM,
            basis="template over pack text + fact ledger",
            model_id=self.model_id,
            context_hash=ch,
        )
        return res.model_copy(update={"output_hash": output_hash(res)})

    def propose(self, ctx: AdvisorContext) -> ProposeResult:
        ch = context_hash(ctx)
        # LOW when classification or critical facts unresolved
        low_markers = (
            "classification_unresolved",
            "classification not provided",
            "unresolved fact",
        )
        fact_blob = " ".join(ctx.facts.values()).lower()
        blocked = ctx.blocked_labels
        is_low = any(m in fact_blob for m in low_markers) or any(
            "classification_unresolved" in (v or "") for v in blocked.values()
        )
        if is_low or ctx.unit_id in {"AMR-17", "AMR-18"} and (
            "classification.primary" not in ctx.facts
            or "not provided" in ctx.facts.get("classification.primary", "").lower()
            or "[assumed]" in ctx.facts.get("classification.primary", "")
        ):
            q = (
                f"What is the primary classification / fracture-control input "
                f"that governs {ctx.unit_id}?"
            )
            res = ProposeResult(
                unit_id=ctx.unit_id,
                band=ProposalBand.LOW,
                basis="§8 LOW: unresolved classification or authority input — propose nothing",
                proposed_axes=None,
                proposed_label=None,
                questions=(q,),
                model_id=self.model_id,
                context_hash=ch,
                refused_labels=dict(blocked),
            )
            return res.model_copy(update={"output_hash": output_hash(res)})

        # EFCP / AMR-14 path → Open/Not Met proposal
        if ctx.unit_id in {"AMR-14", "EFCR-1", "EFCR-2"} or (
            "efcp" in (ctx.shall_text or "").lower()
            and "plan.EFCP" not in ctx.facts
        ):
            axes = {
                "applicability": "yes",
                "obligated_actor": "producer",
                "organization_responsibility": "owner",
                "implementation_state": "not_met",
                "approval_state": "not_required",
            }
            label = "Open/Not Met"
            if label in blocked or "Meet" in blocked:
                # still allow Open/Not Met
                pass
            if "Open/Not Met" in blocked:
                res = ProposeResult(
                    unit_id=ctx.unit_id,
                    band=ProposalBand.LOW,
                    basis=f"blocked: {blocked}",
                    proposed_axes=None,
                    questions=("Which control set applies if EFCP is not present?",),
                    model_id=self.model_id,
                    context_hash=ch,
                    refused_labels=dict(blocked),
                )
                return res.model_copy(update={"output_hash": output_hash(res)})
            res = ProposeResult(
                unit_id=ctx.unit_id,
                band=ProposalBand.HIGH,
                basis="EFCP / control set not confirmed in fact ledger",
                proposed_axes=axes,
                proposed_label=label,
                model_id=self.model_id,
                context_hash=ch,
                refused_labels={k: v for k, v in blocked.items() if k != label},
            )
            return res.model_copy(update={"output_hash": output_hash(res)})

        # Default medium: no axis proposal — ask next clarifying question
        res = ProposeResult(
            unit_id=ctx.unit_id,
            band=ProposalBand.MEDIUM,
            basis="insufficient unique pattern; ask operator",
            proposed_axes=None,
            questions=(
                f"Does {ctx.unit_id} apply to this program/hardware, and who is the obligated actor?",
            ),
            model_id=self.model_id,
            context_hash=ch,
            refused_labels=dict(blocked),
        )
        return res.model_copy(update={"output_hash": output_hash(res)})

    def suggest_closure(self, ctx: AdvisorContext) -> ClosureSuggestion:
        ch = context_hash(ctx)
        actions: list[ActionRecord] = []
        evidence: list[str] = []
        deps = list(ctx.why_not_meet)

        if ctx.unit_id == "AMR-14" or "efcp" in (ctx.shall_text or "").lower():
            actions.append(
                ActionRecord(
                    action_id="EFCP-01",
                    title="Obtain or map EFCP / 6033 control set",
                    owner="program.mp",
                    deliverable="EFCP document or documented mapping to 6033 controls",
                    exit_criteria=(
                        "EFCP identity/revision/approver/date/scope recorded as "
                        "confirmed fact plan.EFCP"
                    ),
                    priority="high",
                    due_or_trigger="before flight-hardware production",
                    work_package="fracture-control",
                    affected_unit_ids=(ctx.unit_id,),
                )
            )
            evidence.append("EFCP document with signature block")
        elif "classification" in " ".join(deps).lower():
            actions.append(
                ActionRecord(
                    action_id="CLASS-01",
                    title="Resolve primary classification inputs",
                    owner="customer.engineering",
                    deliverable="Primary class / fracture-control designation",
                    exit_criteria="classification.primary confirmed fact on ledger",
                    priority="critical",
                    due_or_trigger="prior to NDE credit claims",
                    work_package="classification",
                    affected_unit_ids=(ctx.unit_id,),
                )
            )
        else:
            actions.append(
                ActionRecord(
                    action_id=f"GAP-{ctx.unit_id}",
                    title=f"Close gap for {ctx.unit_id}",
                    owner="producer.quality",
                    deliverable=f"Evidence package for {ctx.unit_id} control implementation",
                    exit_criteria="Qualifying evidence registered and axes re-elected",
                    priority="medium",
                    due_or_trigger="before disposition package release",
                    work_package="general-gap-closure",
                    affected_unit_ids=(ctx.unit_id,),
                )
            )
            evidence.append("Process record or certificate tied to the requirement")

        basis = "ledger-bounded draft actions; operator must attest before commit"
        # Scrub titles/deliverables
        for a in actions:
            scrub_advisor_text(a.title + " " + a.deliverable, ctx.facts)

        res = ClosureSuggestion(
            unit_id=ctx.unit_id,
            actions=tuple(actions),
            evidence_requests=tuple(evidence),
            unresolved_dependencies=tuple(deps),
            band=ProposalBand.MEDIUM,
            basis=basis,
            model_id=self.model_id,
            context_hash=ch,
        )
        return res.model_copy(update={"output_hash": output_hash(res)})


class LiveAdvisor(AdvisorService):
    """
    Anthropic-backed advisor. Opt-in only; never used by tests.

    Env: RDW_ADVISOR_MODEL (fallback ORACLE_BETH_MODEL / claude default).
    """

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = (
            model_id
            or os.environ.get("RDW_ADVISOR_MODEL")
            or os.environ.get("ORACLE_BETH_MODEL")
            or "claude-sonnet-4-20250514"
        )

    def _complete(self, system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise AdvisorError(
                "anthropic package required for LiveAdvisor"
            ) from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AdvisorError("ANTHROPIC_API_KEY not set for LiveAdvisor")
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=self.model_id,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = []
        for block in msg.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts).strip()

    def explain(self, ctx: AdvisorContext) -> ExplainResult:
        ch = context_hash(ctx)
        system = (
            "You are an RDW disposition advisor. Explain what the requirement asks "
            "using ONLY the supplied evidence bundle. Label is interpretation only. "
            "Never claim compliance. Advisory only (D-1)."
        )
        user = json.dumps(ctx.model_dump(), indent=2)
        text = scrub_advisor_text(self._complete(system, user), ctx.facts)
        res = ExplainResult(
            unit_id=ctx.unit_id,
            interpretation=text,
            band=ProposalBand.MEDIUM,
            basis="live model over supplied context",
            model_id=self.model_id,
            context_hash=ch,
        )
        return res.model_copy(update={"output_hash": output_hash(res)})

    def propose(self, ctx: AdvisorContext) -> ProposeResult:
        # Live still must not bypass evaluate_unit blocks — use deterministic
        # for structure, optionally enrich questions via model.
        det = DeterministicAdvisor().propose(ctx)
        return det.model_copy(update={"model_id": self.model_id})

    def suggest_closure(self, ctx: AdvisorContext) -> ClosureSuggestion:
        det = DeterministicAdvisor().suggest_closure(ctx)
        return det.model_copy(update={"model_id": self.model_id})


def get_advisor(*, live: bool = False) -> AdvisorService:
    if live:
        return LiveAdvisor()
    return DeterministicAdvisor()
