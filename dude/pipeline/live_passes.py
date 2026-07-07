#!/usr/bin/env python3
"""
Module: dude.pipeline.live_passes
Purpose: Live LLM implementations of the pass protocols (spec v0.1
         §32–33, v0.2 I12), behind the ModelRouter.

Contract discipline:
  - Every pass demands strict JSON and validates it against a Pydantic
    parse model. One retry with the parse error fed back; then a
    refusal. A pass never returns fabricated or partial-silent output.
  - Observations must cite a capture id from the provided list — a
    record citing an unknown source is rejected VISIBLY (counted in a
    refusal), enforcing "no orphan facts" against the model itself.
  - Model records carry created_by=model and are therefore excluded
    from the evidence fingerprint by construction (v0.2 I5) and require
    user confirmation before accrual (I6).
  - The adversary attaches annotations by SUPERSEDING hypotheses
    (same lineage, new id) — it never rewrites content (I10).

Safety Critical: True — pass output feeds decisions; fabrication or
silent truncation here is fabricated epistemics.
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import json
import logging
import uuid
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dude.data import (
    ConfidenceBand,
    CreatedBy,
    HarmClass,
)
from dude.data.enums import AccessLevel, Pursuit
from dude.data import (
    Hypothesis,
    HypothesisArchetype,
    Interpretation,
    Observation,
    Provenance,
    Refusal,
    SourceType,
    Unknown,
    UnknownImportance,
)
from dude.data.hypotheses import AdversaryAnnotation
from dude.pipeline.passes import PassOutput, PassSet
from dude.pipeline.router import ChatModel, ModelCallError, ModelRouter, resolve_router
from dude.store.jsonl import CaseBundle

LOGGER = logging.getLogger("dude.pipeline.live_passes")

_RETRIES = 2

SYSTEM_PREAMBLE = (
    "You are a pass inside DUDE, an evidence-aware decision engine. "
    "Observation is not inference. A coherent story is not proof. "
    "Trauma does not invalidate telemetry. Refer to the person as 'Dude' "
    "in every statement — never 'the user' or 'the author'. Return ONLY "
    "the requested JSON object — no prose, no markdown fences."
)

SEPARATOR_RULES = (
    "Separate the capture text into observations (claims directly "
    "supported by a capture — cite its id) and interpretations (claims "
    "that go beyond what is directly supported). Never weaken, split, or "
    "re-interpret an explicit user assertion because a quoted fragment "
    "inside it is lexically ambiguous: the user's stated proposition is "
    "the observation; any ambiguity of an embedded quote may be recorded "
    "as a separate interpretation, never as a demotion of the assertion "
    "itself."
)

UNKNOWNS_RULES = (
    "List the missing information required to resolve the "
    "interpretations. An unknown is not automatically a task, and "
    "uncertainty is never turned into surveillance. Classify each: "
    "importance (low/medium/high = decision relevance), user_access "
    "(high = answerable from the user's own records or direct legitimate "
    "questions; low = would require other people's communications, "
    "systems, logs, or monitoring), pursuit (pursue = worth a narrow "
    "legitimate step; hold = matters but wait; do_not_chase = real but "
    "inaccessible — name it and leave it)."
)

HYPOTHESES_RULES = (
    "Titles must be neutral propositions about the world, never verdicts "
    "('correctly identifies', 'real leak') and never assessments of the "
    "user's psychology. Decompose compound claims — contact occurred, it "
    "was deliberate, the motive — into separate hypotheses rather than "
    "stacking them in one. Safety state is not a causal hypothesis: never "
    "emit a hypothesis whose content is a safety assessment; if an "
    "archetype has no credible instance, use not_credible_here."
)

P = TypeVar("P", bound=BaseModel)


class _ParseModel(BaseModel):
    # WHY extra="ignore" here (unlike every DudeModel contract): these
    # models parse LLM output, not our data. An unknown key from a model
    # is noise to tolerate, not a defect to refuse over — refusing on
    # extras cost a production hypotheses pass its second retry. The
    # extra="forbid" rule applies at our API boundary, which this is not.
    model_config = ConfigDict(extra="ignore")


class _ObservationOut(_ParseModel):
    statement: str
    source_capture_id: str
    excerpt: str = ""


class _SeparatorOut(_ParseModel):
    observations: list[_ObservationOut] = Field(default_factory=list)
    interpretations: list[str] = Field(default_factory=list)


class _UnknownOut(_ParseModel):
    statement: str
    importance: UnknownImportance = UnknownImportance.MEDIUM
    user_access: AccessLevel = AccessLevel.MEDIUM
    pursuit: Pursuit = Pursuit.UNCLASSIFIED


class _UnknownsOut(_ParseModel):
    unknowns: list[_UnknownOut] = Field(default_factory=list)


class _HypothesisOut(_ParseModel):
    title: str
    description: str
    archetype: HypothesisArchetype
    harm_class: HarmClass = HarmClass.NONE
    falsifiers: list[str] = Field(default_factory=list)
    not_credible_here: bool = False


class _HypothesesOut(_ParseModel):
    hypotheses: list[_HypothesisOut] = Field(default_factory=list)


class _AttackOut(_ParseModel):
    hypothesis_id: str
    attack: str
    unsupported_links: list[str] = Field(default_factory=list)


class _AdversaryOut(_ParseModel):
    attacks: list[_AttackOut] = Field(default_factory=list)


def _call_json(
    chat: ChatModel, pass_name: str, system: str, user: str, parse_model: type[P]
) -> tuple[P | None, list[Refusal]]:
    """One strict-JSON model call with a single corrective retry, then a
    refusal. Fail closed: no partial parse ever escapes."""
    prompt = user
    for attempt in range(_RETRIES + 1):
        try:
            raw = chat.complete(system, prompt)
            return parse_model.model_validate(json.loads(_strip_fences(raw))), []
        except ModelCallError as exc:
            return None, [Refusal(pass_name=pass_name, reason=str(exc))]
        except (ValueError, ValidationError) as exc:
            LOGGER.warning("%s: invalid JSON (attempt %d): %s", pass_name, attempt, exc)
            prompt = (
                f"{user}\n\nYour previous reply was invalid: {exc}\n"
                "Return ONLY the corrected JSON object, minified, with no "
                "fields beyond the schema and every description under 40 "
                "words."
            )
    return None, [
        Refusal(
            pass_name=pass_name,
            reason="Model returned invalid JSON after retry; no output used.",
        )
    ]


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _case_material(bundle: CaseBundle) -> str:
    lines = [f"CASE: {bundle.case.title}"]
    lines += [f"CAPTURE {c.id}: {c.text}" for c in bundle.captures]
    lines += [f"EVENT: {e.description}" for e in bundle.events]
    lines += [f"USER INTERPRETATION: {i.statement}" for i in bundle.interpretations]
    return "\n".join(lines)


class LiveSeparator:
    """P2: observation/inference separation. Observations must cite a
    capture id; citations the model invents are rejected visibly."""

    pass_name = "separator"

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    def run(self, bundle: CaseBundle) -> PassOutput:
        # Idempotence: only captures no observation cites yet get extracted
        # (re-running on cited captures appended duplicate observations in
        # production). Same rationale as LiveHypotheses.
        cited = {
            p.source_id for o in bundle.observations for p in o.provenance
        }
        known = {c.id for c in bundle.captures if c.id not in cited}
        if not known:
            return PassOutput()
        parsed, refusals = _call_json(
            self._chat,
            self.pass_name,
            SYSTEM_PREAMBLE,
            SEPARATOR_RULES
            + " JSON: "
            '{"observations": [{"statement", "source_capture_id", '
            '"excerpt"}], "interpretations": ["..."]}\n\n'
            + _case_material(bundle),
            _SeparatorOut,
        )
        if parsed is None:
            return PassOutput(refusals=refusals)
        observations, rejected = [], 0
        for out in parsed.observations:
            if out.source_capture_id not in known:
                rejected += 1
                continue
            observations.append(
                Observation(
                    case_id=bundle.case.id,
                    statement=out.statement,
                    provenance=[
                        Provenance(
                            source_type=SourceType.USER_STATEMENT,
                            source_id=out.source_capture_id,
                            excerpt=out.excerpt or None,
                        )
                    ],
                    created_by=CreatedBy.MODEL,
                )
            )
        if rejected:
            refusals.append(
                Refusal(
                    pass_name=self.pass_name,
                    reason=f"Rejected {rejected} observation(s) citing unknown "
                    "sources (no orphan facts).",
                )
            )
        interpretations = [
            Interpretation(
                case_id=bundle.case.id, statement=s, created_by=CreatedBy.MODEL
            )
            for s in parsed.interpretations
        ]
        return PassOutput(
            observations=observations,
            interpretations=interpretations,
            refusals=refusals,
        )


class LiveUnknowns:
    pass_name = "unknowns"

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    def run(self, bundle: CaseBundle) -> PassOutput:
        # Idempotence: unknowns stand until resolved; regenerating each run
        # appended near-duplicates in production.
        if bundle.unknowns:
            return PassOutput()
        parsed, refusals = _call_json(
            self._chat,
            self.pass_name,
            SYSTEM_PREAMBLE,
            UNKNOWNS_RULES
            + ' JSON: {"unknowns": [{"statement", "importance": '
            '"low|medium|high", "user_access": "low|medium|high", '
            '"pursuit": "pursue|hold|do_not_chase"}]}\n\n'
            + _case_material(bundle),
            _UnknownsOut,
        )
        if parsed is None:
            return PassOutput(refusals=refusals)
        return PassOutput(
            unknowns=[
                Unknown(
                    case_id=bundle.case.id,
                    statement=u.statement,
                    importance=u.importance,
                    user_access=u.user_access,
                    # Machine-enforced, not prompt-enforced: uncertainty
                    # never becomes surveillance. LOW access clamps to
                    # DO_NOT_CHASE regardless of what the model said.
                    pursuit=(
                        Pursuit.DO_NOT_CHASE
                        if u.user_access is AccessLevel.LOW
                        else u.pursuit
                    ),
                )
                for u in parsed.unknowns
            ],
            refusals=refusals,
        )


class LiveHypotheses:
    """P4: competing causal models. All archetypes must be attempted;
    an archetype with no honest instance is returned with
    not_credible_here=true, never fabricated (review revision 14). The
    adversarial-cause archetype is verified present for interpersonal
    material (v0.2 I9) — its absence is a visible refusal."""

    pass_name = "hypotheses"

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    def run(self, bundle: CaseBundle) -> PassOutput:
        # WHY idempotence: regenerating on every run appends duplicate
        # hypotheses, which mutates the scope fingerprint and breaks the
        # anti-rumination gate (found in production). Existing live
        # hypotheses stand; users add new ones explicitly.
        if any(h.is_live() for h in bundle.hypotheses):
            return PassOutput()
        parsed, refusals = _call_json(
            self._chat,
            self.pass_name,
            SYSTEM_PREAMBLE,
            "Generate competing causal explanations. Attempt each archetype: "
            "user_favored, boring, mixed_cause, missing_variable, "
            "adversarial_cause (someone deliberately engineering the "
            "ambiguity). If an archetype has no credible instance, still "
            "return it with not_credible_here=true and say why in the "
            "description — never fabricate false balance. "
            + HYPOTHESES_RULES
            + " harm_class is "
            "catastrophic_to_user when the hypothesis, if true, means "
            "ongoing danger or irreversible harm to the user. Every credible "
            "hypothesis needs falsifiers (what evidence would change it). "
            "Keep every description under 40 words. "
            'JSON: {"hypotheses": [{"title", "description", "archetype", '
            '"harm_class": "none|recoverable|catastrophic_to_user", '
            '"falsifiers": [], "not_credible_here": false}]}\n\n'
            + _case_material(bundle),
            _HypothesesOut,
        )
        if parsed is None:
            return PassOutput(refusals=refusals)
        returned = {h.archetype for h in parsed.hypotheses}
        if HypothesisArchetype.ADVERSARIAL_CAUSE not in returned:
            refusals.append(
                Refusal(
                    pass_name=self.pass_name,
                    reason="Model omitted the mandatory adversarial-cause "
                    "archetype (v0.2 I9); hypothesis set is incomplete.",
                )
            )
        return PassOutput(
            hypotheses=[
                Hypothesis(
                    case_id=bundle.case.id,
                    title=h.title,
                    description=h.description,
                    archetype=h.archetype,
                    harm_class=h.harm_class,
                    band=ConfidenceBand.UNRESOLVED,
                    falsifiers=h.falsifiers,
                    not_credible_here=h.not_credible_here,
                    created_by=CreatedBy.MODEL,
                )
                for h in parsed.hypotheses
            ],
            refusals=refusals,
        )


class LiveAdversary:
    """P5: attack every live hypothesis in both directions (v0.1 §34).
    Attacks attach as annotations on superseding copies — same lineage,
    new id, content untouched (v0.2 I10)."""

    pass_name = "adversary"

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    def run(self, bundle: CaseBundle) -> PassOutput:
        # Idempotence: each hypothesis is attacked once. Re-attacking every
        # run stacked duplicate annotations in production; a superseded or
        # newly added hypothesis arrives annotation-free and gets attacked.
        live = [h for h in bundle.hypotheses if h.is_live() and not h.annotations]
        if not live:
            return PassOutput()
        listing = "\n".join(
            f"HYPOTHESIS {h.id} [{h.archetype.value}]: {h.title} — {h.description}"
            for h in live
        )
        parsed, refusals = _call_json(
            self._chat,
            self.pass_name,
            SYSTEM_PREAMBLE
            + " You are the adversary. Attack in BOTH directions: attack "
            "threat narratives AND attack dismissive/it's-just-anxiety "
            "narratives. Trauma does not invalidate telemetry.",
            "Attack each hypothesis: what is assumed, which causal links "
            "are unsupported, what boring or adversarial explanation "
            'survives. JSON: {"attacks": [{"hypothesis_id", "attack", '
            '"unsupported_links": []}]}\n\n'
            + listing
            + "\n\n"
            + _case_material(bundle),
            _AdversaryOut,
        )
        if parsed is None:
            return PassOutput(refusals=refusals)
        by_id = {h.id: h for h in live}
        superseding: dict[str, Hypothesis] = {}
        rejected = 0
        for attack in parsed.attacks:
            target = by_id.get(attack.hypothesis_id)
            if target is None:
                rejected += 1
                continue
            revised = superseding.get(target.id) or target.model_copy(
                update={"id": uuid.uuid4().hex, "supersedes": target.id}
            )
            revised.annotations.append(
                AdversaryAnnotation(
                    attack=attack.attack,
                    unsupported_links=attack.unsupported_links,
                    created_by=CreatedBy.MODEL,
                )
            )
            superseding[target.id] = revised
        if rejected:
            refusals.append(
                Refusal(
                    pass_name=self.pass_name,
                    reason=f"Rejected {rejected} attack(s) citing unknown "
                    "hypothesis ids.",
                )
            )
        return PassOutput(hypotheses=list(superseding.values()), refusals=refusals)


def build_live_passes(router: ModelRouter) -> PassSet:
    """Live builder passes on the primary; adversary live only when a
    DISTINCT provider exists, otherwise it stays a visible stub refusal
    (v0.1 §55 — no same-provider self-certification)."""
    adversary = LiveAdversary(router.adversary) if router.adversary else None
    return PassSet(
        separator=LiveSeparator(router.primary),
        unknowns=LiveUnknowns(router.primary),
        hypotheses=LiveHypotheses(router.primary),
        adversary=adversary,
    )


def resolve_passes() -> PassSet:
    """The production PassSet: live when the environment has keys,
    all-stub (visible refusals, no network) otherwise."""
    router = resolve_router()
    if router is None:
        return PassSet()
    return build_live_passes(router)
