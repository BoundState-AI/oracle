#!/usr/bin/env python3
"""
Module: oracle.tailor.advisor
Purpose: Proposes a disposition for one requirement, with its reasoning and
         the questions it cannot answer itself.

The advisor proposes; a qualified engineer disposes. It never records a
decision — `TailorSession.record` is the only path that does, and it is driven
by the human. Per spec §8, a LOW-confidence proposal is not a code with a
caveat: it is OPEN plus the questions that would settle it.

Safety Critical: no — advisory only, per spec D-1
Financially Critical: no

__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from oracle.disposition.codes import (
    DISPOSITION_CODES,
    OPEN_SUBREASONS,
    DispositionCode,
    OPENSubReason,
    ProposalBand,
)
from oracle.tailor.session import Requirement

LOGGER = logging.getLogger("oracle.tailor.advisor")

# WHY Sonnet 5 and not a larger model: this is per-requirement reading and
# classification against a supplied scope, run 115+ times per standard — a
# workload where Sonnet 5 is at or near Opus quality at a fraction of the cost.
# Override with ORACLE_TAILOR_MODEL when a run warrants it.
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 4000


class AdvisorError(Exception):
    """Raised when a proposal cannot be obtained or parsed."""


@dataclass(frozen=True)
class Proposal:
    """One advisory proposal for a single requirement.

    `band` is qualitative triage (§8), never a probability. LOW means the
    advisor declined to propose a substantive code — `code` will be OPEN and
    `questions` carries what a human must answer.
    """

    code: DispositionCode
    band: ProposalBand
    basis: str
    reasoning: str
    questions: tuple[str, ...] = ()
    open_sub_reason: Optional[OPENSubReason] = None
    draft_rationale: str = ""
    evidence_needed: tuple[str, ...] = ()

    @property
    def is_question(self) -> bool:
        """True when the advisor is asking rather than proposing (§8 LOW rule)."""
        return self.band is ProposalBand.LOW


@dataclass(frozen=True)
class Brief:
    """Plain-English orientation on one requirement, ending in a question.

    Shown before any proposal. The user should be able to answer "do we meet
    this?" from the brief alone, without opening the standard — which is the
    difference between a worklist and a helper.
    """

    requires: str
    purpose: str
    satisfied_by: tuple[str, ...] = ()
    question: str = ""
    watch_for: str = ""


class AdvisorBackend(Protocol):
    """Seam for the model call — lets the CLI and tests share one code path."""

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You help a qualified engineer tailor a technical standard, one \
requirement at a time. You propose; they decide. You never record a decision.

Assign exactly one disposition code:

  CW   Complies as written. The declared scope and practice already satisfy this
       requirement as literally stated.
  MI   Meets the intent by alternative means. The literal text is not satisfied,
       but the underlying objective is, by a different control. Requires: what
       the requirement is trying to achieve, the alternative control that
       achieves it, and whether that control is integral or compensating.
  EX   Does not meet the requirement; an exception is requested. Requires the
       reason it cannot be met AND what would close it — the path to compliance,
       or why no path exists and permanent relief is being sought.
  NA   Not applicable. Requires a citation to the specific scope declaration
       that excludes it. "Seems irrelevant" is not a scope citation.
  OPEN Cannot be determined yet. Requires one sub-reason from the closed list.

Banding (this is triage, not probability — never emit a number):
  HIGH   Requirement text is unambiguous, the scope citation is direct, no
         authority dependency, no definitional remap.
  MEDIUM Depends on a referenced table or subparagraph you have not been shown,
         or on a routing decision consistent with another entry.
  LOW    Depends on a scope decision the customer has not made, or on process
         capability not established. PROPOSE NOTHING SUBSTANTIVE: set code to
         OPEN with the applicable sub-reason and put the real question in
         `questions`.

Rules that matter more than being helpful:
- A requirement whose disposition turns on a decision nobody has made is OPEN.
  Guessing it is the failure this tool exists to prevent.
- Do not infer scope. If the declared scope does not address the requirement,
  that is a scope question, not an NA.
- Quote the requirement's own words when they decide the matter.
- Be specific about what would settle an OPEN — name the document, decision, or
  test, not "more information"."""


def build_user_prompt(
    req: Requirement,
    standard_id: str,
    scope_notes: str,
    prior: tuple[tuple[str, str], ...] = (),
    user_answer: str = "",
) -> str:
    """Assemble the per-requirement prompt.

    `prior` carries earlier decisions so paired requirements are dispositioned
    consistently — the same scope question answered two ways across a package
    is a consistency failure, not two independent judgments.
    """
    parts = [
        f"STANDARD: {standard_id}",
        f"REQUIREMENT: {req.tag or req.id}   (section {req.section}"
        + (f", page {req.page}" if req.page else "")
        + ")",
        "",
        "FULL TEXT:",
        req.shall_text or f"{req.subject} shall {req.requirement}",
    ]
    if scope_notes.strip():
        parts += ["", "DECLARED SCOPE (what the organization has committed to):", scope_notes.strip()]
    else:
        parts += [
            "",
            "DECLARED SCOPE: none supplied. Treat any disposition that depends on"
            " scope as OPEN (scope_decision_not_made) rather than assuming one.",
        ]
    if prior:
        parts += ["", "DECISIONS ALREADY MADE (stay consistent with these):"]
        parts += [f"  {uid}: {code}" for uid, code in prior[-12:]]
    if user_answer.strip():
        parts += [
            "",
            "THE ENGINEER'S ANSWER — this is their position, in their words:",
            user_answer.strip(),
            "",
            "Map that answer onto the vocabulary. If they describe doing something"
            " different that achieves the same objective, that is MI, not EX — and"
            " the draft rationale must name the objective and the alternative"
            " control. If they say they do not do it, that is EX, and the draft"
            " must say what would close it. If their answer does not actually"
            " settle the requirement, say so and return OPEN rather than reading"
            " more into it than they said.",
        ]
    else:
        parts += [
            "",
            "The engineer has not answered yet. Propose only what the requirement"
            " and declared scope support on their own.",
        ]
    parts += ["", "Propose a disposition for this requirement."]
    return "\n".join(parts)


PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "enum": sorted(DISPOSITION_CODES)},
        "band": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "basis": {
            "type": "string",
            "description": "One sentence: the structural reason for the band.",
        },
        "reasoning": {
            "type": "string",
            "description": "The analysis, citing the requirement's own words where they decide it.",
        },
        "draft_rationale": {
            "type": "string",
            "description": (
                "Draft rationale the engineer can edit. For MI: intent + alternative"
                " control + whether it is integral or compensating. For EX: why it"
                " cannot be met AND what would close it. For NA: the scope citation."
                " Empty when code is OPEN."
            ),
        },
        "open_sub_reason": {
            "type": "string",
            "enum": sorted(OPEN_SUBREASONS) + [""],
            "description": "Required when code is OPEN; empty string otherwise.",
        },
        "questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What a human must answer. Required when band is LOW.",
        },
        "evidence_needed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific documents, decisions, or tests that would settle this.",
        },
    },
    "required": [
        "code",
        "band",
        "basis",
        "reasoning",
        "draft_rationale",
        "open_sub_reason",
        "questions",
        "evidence_needed",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


@dataclass
class AnthropicBackend:
    """Calls Claude via the Anthropic SDK with a constrained output schema.

    Structured outputs remove the parse-failure mode entirely: the response is
    schema-valid or the call errors, so there is no salvaging of half-parsed
    JSON in a compliance path.
    """

    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    _client: Any = field(default=None, repr=False)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - environment issue
            raise AdvisorError(
                "anthropic package not installed. Run: uv pip install anthropic"
            ) from exc
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            LOGGER.debug("No API key env var; relying on SDK credential resolution")
        self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                # Adaptive thinking is on by default on this model; effort is the
                # depth control. No temperature/top_p — rejected on Sonnet 5.
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            raise AdvisorError(f"model call failed: {exc}") from exc

        if response.stop_reason == "refusal":
            raise AdvisorError("model declined the request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise AdvisorError("proposal truncated — raise MAX_TOKENS")

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text.strip():
            raise AdvisorError("model returned no text content")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdvisorError(f"schema-constrained output was not valid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------


@dataclass
class Advisor:
    """Explains a requirement, then helps land a disposition. Records nothing.

    Two steps, in this order:

      brief()   here is AMR-N, here is what it requires and why it exists,
                do you meet it?
      propose() given the user's answer, here is the code that follows and a
                draft rationale.

    The order matters. Proposing first invites the user to rubber-stamp a code
    for a requirement they have not read; explaining first means the answer is
    theirs and the code follows from it.
    """

    backend: AdvisorBackend
    standard_id: str
    scope_notes: str = ""

    def brief(self, req: Requirement) -> Brief:
        """Orient the user on one requirement and ask whether they meet it."""
        raw = self.backend.complete(
            BRIEF_SYSTEM_PROMPT,
            build_brief_prompt(req, self.standard_id, self.scope_notes),
            BRIEF_SCHEMA,
        )
        return _to_brief(raw)

    def propose(
        self,
        req: Requirement,
        prior: tuple[tuple[str, str], ...] = (),
        user_answer: str = "",
    ) -> Proposal:
        """Turn the user's answer into a disposition and a draft rationale.

        `user_answer` is what they said in their own words. With it, the
        advisor is mapping a stated position onto the vocabulary; without it,
        it is guessing — and guessing is what drives a unit to OPEN.
        """
        raw = self.backend.complete(
            SYSTEM_PROMPT,
            build_user_prompt(req, self.standard_id, self.scope_notes, prior, user_answer),
            PROPOSAL_SCHEMA,
        )
        return _to_proposal(raw)


BRIEF_SYSTEM_PROMPT = """You are orienting a qualified engineer on one requirement \
from a technical standard, so they can answer whether their organization meets it.

Write for someone who has not read the standard and should not have to. Say what \
the requirement actually demands in plain language, and — this is the part that \
matters — what it is FOR. The intent is what makes a "meets intent by alternative \
means" answer possible later, so name the underlying objective, not just the \
literal instruction.

Then ask them one direct question: do you meet it?

Rules:
- Plain English. No standards-speak, no restating the clause verbatim.
- Name the objective behind the requirement, not only the mechanism it specifies.
- `satisfied_by` lists what would concretely demonstrate compliance — documents,
  controls, records, tests. Be specific enough to check against.
- `question` is the single most decision-relevant thing to ask them. If the
  requirement is conditional, ask about the condition first.
- `watch_for` is the trap: the thing people commonly get wrong here, or the
  distinction that changes the answer. Empty if there isn't one.
- Do NOT propose a disposition code. That comes after they answer."""


def build_brief_prompt(req: Requirement, standard_id: str, scope_notes: str) -> str:
    parts = [
        f"STANDARD: {standard_id}",
        f"REQUIREMENT: {req.tag or req.id}   (section {req.section}"
        + (f", page {req.page}" if req.page else "")
        + ")",
        "",
        "FULL TEXT:",
        req.shall_text or f"{req.subject} shall {req.requirement}",
    ]
    if scope_notes.strip():
        parts += ["", "WHAT THIS ORGANIZATION HAS DECLARED:", scope_notes.strip()]
    parts += ["", "Explain this requirement and ask whether they meet it."]
    return "\n".join(parts)


BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requires": {
            "type": "string",
            "description": "What the requirement demands, in plain English. 1-3 sentences.",
        },
        "purpose": {
            "type": "string",
            "description": "What it is FOR — the objective behind it. 1-3 sentences.",
        },
        "satisfied_by": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete things that would demonstrate compliance.",
        },
        "question": {
            "type": "string",
            "description": "One direct question to the user: do you meet it?",
        },
        "watch_for": {
            "type": "string",
            "description": "The common trap or the distinction that changes the answer. May be empty.",
        },
    },
    "required": ["requires", "purpose", "satisfied_by", "question", "watch_for"],
    "additionalProperties": False,
}


def _to_brief(raw: dict[str, Any]) -> Brief:
    requires = str(raw.get("requires", "")).strip()
    if not requires:
        raise AdvisorError("brief did not describe the requirement")
    return Brief(
        requires=requires,
        purpose=str(raw.get("purpose", "")).strip(),
        satisfied_by=tuple(s for s in raw.get("satisfied_by") or () if str(s).strip()),
        question=str(raw.get("question", "")).strip(),
        watch_for=str(raw.get("watch_for", "")).strip(),
    )


def _to_proposal(raw: dict[str, Any]) -> Proposal:
    """Validate the model's structured output into a Proposal.

    Enforces the §8 LOW rule here rather than trusting the prompt: a LOW band
    that arrived carrying a substantive code is downgraded to OPEN, because the
    whole point of LOW is that no code should be proposed.
    """
    try:
        code = DispositionCode(raw["code"])
        band = ProposalBand(raw["band"])
    except (KeyError, ValueError) as exc:
        raise AdvisorError(f"unusable proposal from model: {exc}") from exc

    sub_raw = (raw.get("open_sub_reason") or "").strip()
    sub = OPENSubReason(sub_raw) if sub_raw in OPEN_SUBREASONS else None
    questions = tuple(q for q in raw.get("questions") or () if str(q).strip())

    if band is ProposalBand.LOW and code is not DispositionCode.OPEN:
        LOGGER.info(
            "LOW band proposed %s; downgrading to OPEN per §8 (propose nothing on LOW)",
            code,
        )
        code = DispositionCode.OPEN
        sub = sub or OPENSubReason.SCOPE_DECISION_NOT_MADE

    if code is DispositionCode.OPEN and sub is None:
        sub = OPENSubReason.SCOPE_DECISION_NOT_MADE

    return Proposal(
        code=code,
        band=band,
        basis=str(raw.get("basis", "")).strip(),
        reasoning=str(raw.get("reasoning", "")).strip(),
        questions=questions,
        open_sub_reason=sub,
        draft_rationale=str(raw.get("draft_rationale", "")).strip(),
        evidence_needed=tuple(
            e for e in raw.get("evidence_needed") or () if str(e).strip()
        ),
    )
