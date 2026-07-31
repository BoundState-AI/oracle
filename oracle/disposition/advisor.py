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
    # FR2/AF3: fact keys the dependency graph links to THIS unit — LOW is
    # decided from these, never from a global fact scan.
    relevant_fact_keys: tuple[str, ...] = ()


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
    relevant = tuple(
        sorted(
            {
                e.fact_key
                for e in graph.prerequisites_of(unit.unit_id)
                if e.fact_key
            }
        )
    )
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
        relevant_fact_keys=relevant,
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
        blocked = ctx.blocked_labels
        # FR2/AF3: LOW is decided from UNIT-RELEVANT input-gap facts only.
        # Input-gap keys are customer/authority decisions (§8 LOW definition);
        # plan-presence keys (plan.*) drive not-met proposals, never LOW.
        gap_keys = [
            k
            for k in ctx.relevant_fact_keys
            if k in ("classification.primary", "ceo.identity")
        ]
        unresolved_gaps = [
            k
            for k in gap_keys
            if k not in ctx.facts or "[assumed]" in ctx.facts.get(k, "")
        ]
        is_low = bool(unresolved_gaps) or any(
            "classification_unresolved" in (v or "") for v in blocked.values()
        )
        if is_low:
            gap = unresolved_gaps[0] if unresolved_gaps else "classification.primary"
            q = (
                f"What is the value of {gap} that governs {ctx.unit_id}? "
                "(customer/authority input required)"
            )
            res = ProposeResult(
                unit_id=ctx.unit_id,
                band=ProposalBand.LOW,
                basis=(
                    "§8 LOW: unit-relevant input unresolved "
                    f"({', '.join(unresolved_gaps) or 'classification_unresolved'}) "
                    "— propose nothing"
                ),
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
            verify_proposal_label(axes, label)  # AR1: template must self-agree
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


def finalize_hash(res: Any) -> Any:
    """FR4/INTEG-1: output_hash is computed over the FINAL object, last.

    Convention: hash is computed with output_hash cleared, then set. Nothing
    may mutate the object after this call. Verifiers recompute with the hash
    field cleared and compare.
    """
    cleared = res.model_copy(update={"output_hash": ""})
    return cleared.model_copy(update={"output_hash": output_hash(cleared)})


_ALLOWED_PROPOSAL_AXES = frozenset(
    {
        "applicability",
        "obligated_actor",
        "organization_responsibility",
        "implementation_state",
        "approval_state",
    }
)


def derive_label_from_axes(axes: dict[str, Any]) -> str:
    """AR1: the label a proposal's axes actually map to under §7.1.

    Raises (ValueError/AxisContradiction) when the axes cannot map — callers
    treat that as an invalid proposal.
    """
    from oracle.disposition.export_map import AxisSnapshot, map_axes_to_export_label

    snap = AxisSnapshot(
        applicability=axes.get("applicability", "tbd"),
        obligated_actor=axes.get("obligated_actor"),
        organization_responsibility=axes.get("organization_responsibility", "tbd"),
        implementation_state=axes.get("implementation_state", "tbd"),
        approval_state=axes.get("approval_state", "tbd"),
    )
    return map_axes_to_export_label(snap).value


def verify_proposal_label(
    axes: Optional[dict[str, Any]], label: Optional[str]
) -> None:
    """AR1: shown label and elected axes must be the SAME disposition."""
    if axes is None and label is None:
        return
    if axes is None or label is None:
        raise AdvisorError(
            f"proposal must carry axes and label together (axes={axes!r}, "
            f"label={label!r})"
        )
    derived = derive_label_from_axes(axes)
    if derived != label:
        raise AdvisorError(
            f"proposed_label {label!r} does not match the label its axes "
            f"derive to ({derived!r}) — the operator would attest a different "
            "disposition than shown"
        )


class LiveAdvisor(AdvisorService):
    """
    Anthropic-backed advisor. Opt-in only; never used by tests.

    Env: RDW_ADVISOR_MODEL (fallback ORACLE_BETH_MODEL / claude default).
    propose/suggest_closure request STRUCTURED JSON from the model, validate
    it, strip anything the deterministic gates block, and fall back to the
    DeterministicAdvisor on any parse/validation failure (recorded as such).
    """

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = (
            model_id
            or os.environ.get("RDW_ADVISOR_MODEL")
            or os.environ.get("ORACLE_BETH_MODEL")
            or "claude-sonnet-5"
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
        return finalize_hash(res)

    def _json_block(self, raw: str) -> dict[str, Any]:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise AdvisorError("live advisor returned no JSON object")
        data = json.loads(raw[start : end + 1])
        if not isinstance(data, dict):
            raise AdvisorError("live advisor JSON is not an object")
        return data

    def _fallback(self, det_result: Any) -> Any:
        """Deterministic fallback recorded as such; hash computed LAST."""
        res = det_result.model_copy(
            update={
                "model_id": self.model_id,
                "basis": f"{det_result.basis} [live-fallback:deterministic]",
            }
        )
        return finalize_hash(res)

    def propose(self, ctx: AdvisorContext) -> ProposeResult:
        ch = context_hash(ctx)
        try:
            system = (
                "You are an RDW disposition advisor. Using ONLY the supplied "
                "evidence bundle, return ONE JSON object with keys: band "
                "(HIGH|MEDIUM|LOW), basis (string), proposed_axes (object with "
                "keys among applicability/obligated_actor/"
                "organization_responsibility/implementation_state/"
                "approval_state, or null), proposed_label (string or null), "
                "questions (array of strings). LOW means propose NOTHING "
                "(axes and label null). Never propose a label listed in "
                "blocked_labels. Advisory only (D-1); no compliance claims."
            )
            data = self._json_block(
                self._complete(system, json.dumps(ctx.model_dump(), indent=2))
            )
            band = ProposalBand(str(data.get("band", "MEDIUM")).upper())
            axes = data.get("proposed_axes")
            label = data.get("proposed_label")
            if band == ProposalBand.LOW:
                axes, label = None, None
            if axes is not None:
                if not isinstance(axes, dict) or not set(axes) <= _ALLOWED_PROPOSAL_AXES:
                    raise AdvisorError(f"invalid proposed_axes: {axes!r}")
            if label is not None and label in ctx.blocked_labels:
                # Deterministic gates rule: strip the blocked proposal.
                axes, label = None, None
            # AR1: what is shown must be what the axes elect — no divergence.
            verify_proposal_label(axes, label)
            basis = scrub_advisor_text(str(data.get("basis", "")), ctx.facts)
            questions = tuple(
                scrub_advisor_text(str(q), ctx.facts)
                for q in (data.get("questions") or [])
            )
            res = ProposeResult(
                unit_id=ctx.unit_id,
                band=band,
                basis=basis or "live structured proposal",
                proposed_axes=axes,
                proposed_label=label,
                questions=questions,
                model_id=self.model_id,
                context_hash=ch,
                refused_labels=dict(ctx.blocked_labels),
            )
            return finalize_hash(res)
        except (AdvisorError, ValueError, KeyError, TypeError) as e:
            LOGGER.warning("LiveAdvisor.propose fallback: %s", e)
            return self._fallback(DeterministicAdvisor().propose(ctx))

    def suggest_closure(self, ctx: AdvisorContext) -> ClosureSuggestion:
        ch = context_hash(ctx)
        try:
            system = (
                "You are an RDW closure planner. Using ONLY the supplied "
                "evidence bundle, return ONE JSON object with keys: actions "
                "(array of objects with action_id, title, owner, deliverable, "
                "exit_criteria, priority in critical|high|medium|low, "
                "due_or_trigger, work_package, affected_unit_ids array), "
                "evidence_requests (array of strings), basis (string). Bound "
                "every claim by the supplied facts; state unresolved "
                "dependencies; never claim compliance. Advisory only (D-1)."
            )
            data = self._json_block(
                self._complete(system, json.dumps(ctx.model_dump(), indent=2))
            )
            actions = tuple(
                ActionRecord.model_validate(
                    {**a, "affected_unit_ids": tuple(a.get("affected_unit_ids") or (ctx.unit_id,))}
                )
                for a in (data.get("actions") or [])
            )
            for a in actions:
                scrub_advisor_text(
                    " ".join((a.title, a.deliverable, a.exit_criteria)), ctx.facts
                )
            basis = scrub_advisor_text(str(data.get("basis", "")), ctx.facts)
            evid = tuple(
                scrub_advisor_text(str(x), ctx.facts)
                for x in (data.get("evidence_requests") or [])
            )
            res = ClosureSuggestion(
                unit_id=ctx.unit_id,
                actions=actions,
                evidence_requests=evid,
                unresolved_dependencies=ctx.why_not_meet,
                band=ProposalBand.MEDIUM,
                basis=basis or "live structured closure plan",
                model_id=self.model_id,
                context_hash=ch,
            )
            return finalize_hash(res)
        except (AdvisorError, ValueError, KeyError, TypeError) as e:
            LOGGER.warning("LiveAdvisor.suggest_closure fallback: %s", e)
            return self._fallback(DeterministicAdvisor().suggest_closure(ctx))


def get_advisor(*, live: bool = False) -> AdvisorService:
    if live:
        return LiveAdvisor()
    return DeterministicAdvisor()
