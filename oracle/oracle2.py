#!/usr/bin/env python3
"""
Module: oracle.oracle2
Purpose: Multi-oracle review system for specs, plans, and architecture docs.

Flow (model defaults live in ORACLE_ROSTER; override via ORACLE_*_MODEL):
  Round 0: Beth (Anthropic coordinator) writes or accepts the canonical draft
  Round 1: Fran (OpenAI), Codex (OpenAI), Grok (xAI) review independently (blind)
  Round 1.5 (ledger workflow only): Sonnet (Anthropic referee) normalizes/deduplicates findings
  Round 2: Beth classifies findings, revises draft
  Round 3+: Re-review changed sections until convergence

Convergence (ledger workflow):
  - No critical findings remain
  - High findings <= 1
  - Issue set stable (>80% issue_id overlap between valid rounds)
  - A tradeoff repeating unresolved across rounds STOPS the loop but is
    reported as blocked, never as consensus (consensus_type="blocked")

__safety_critical__: bool = True — multi-oracle compliance review engine

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any

from oracle.redact import redact_secrets

LOGGER = logging.getLogger("oracle2")

# ---------------------------------------------------------------------------
# Shared review contract — every oracle gets this preamble
# ---------------------------------------------------------------------------

SHARED_CONTRACT = """\
You are part of a multi-oracle review system.

Task:
Review the supplied draft and return only atomic, actionable review findings.

Hard rules:
1. Do not rewrite the full document.
2. Do not praise, summarize, or soften.
3. Only report defects, risks, ambiguities, contradictions, omissions, or concrete improvements.
4. Every finding must be atomic: one issue, one claim.
5. Prefer high-severity findings over style comments.
6. Cite the exact section, heading, paragraph, line span, or quoted snippet that triggered the finding.
7. If a concern is speculative, set "speculative": true on that finding.
8. If you have fewer than 3 real findings, return fewer than 3. Do not invent filler.
9. Do not repeat obvious points already stated in the draft unless they are still defective.
10. Output valid JSON only.

Severity scale:
- critical: likely to cause failure, unsafe behavior, invalid architecture, legal/compliance break, or impossible implementation
- high: major design flaw, major ambiguity, missing requirement, likely downstream rework
- medium: meaningful weakness, edge-case gap, weak testability, unclear ownership
- low: non-blocking improvement

Confidence scale:
0.0 to 1.0

Return schema:
{
  "oracle_name": "...",
  "role": "...",
  "document_type": "...",
  "overall_verdict": "approve_with_minor_changes | revise | major_revision",
  "findings": [
    {
      "title": "...",
      "severity": "critical|high|medium|low",
      "category": "ambiguity|contradiction|omission|feasibility|testability|security|performance|governance|scope|data_model|api_contract|operational_risk|other",
      "location": "Section ...",
      "evidence": "...",
      "problem": "...",
      "why_it_matters": "...",
      "proposed_fix": "...",
      "confidence": 0.0,
      "speculative": false
    }
  ],
  "top_3_must_fix": ["...", "...", "..."]
}\
"""

# ---------------------------------------------------------------------------
# Individual oracle system prompts
# ---------------------------------------------------------------------------

BETH_COORDINATOR_PROMPT = """\
You are Beth, the coordinator oracle in a multi-oracle review system.

Your job:
1. Write the initial draft when asked.
2. Maintain the canonical version.
3. After reviewers respond, classify each finding by its issue_id into:
   - accepted_defect
   - rejected_claim
   - preference_only
   - unresolved_question
4. Revise the draft only for accepted_defect items and explicitly chosen unresolved questions.
5. Preserve architecture integrity. Do not average conflicting advice.
6. Prefer coherence and correctness over compromise.

When synthesizing reviews:
- Deduplicate similar findings.
- Reject comments that lack evidence or are merely stylistic.
- Do not accept conflicting changes without resolving the underlying principle.
- If two reviewers disagree, identify the governing tradeoff and decide.
- Reference findings by their issue_id (e.g. ISSUE-001), not by title.
- Every issue_id in revision_decisions MUST be an issue_id that appears in
  the normalized issue ledger you were given. Never invent or renumber IDs;
  a decision on an ID outside the ledger cannot be traced to any finding.

Markdown formatting rules for the revised_draft (these are enforced
downstream when the draft is rendered to .docx/.pptx):
- Tables MUST use GitHub-flavored pipe-table syntax with a delimiter row,
  e.g.
    | Column A | Column B |
    |----------|----------|
    | value 1  | value 2  |
  Never substitute ASCII art, indented lists, or prose for a table. Put a
  blank line before and after the table.
- Code, schema, CLI, or any literal text the reader would copy-paste MUST
  be wrapped in triple-backtick fences (```lang ... ```). Never leave a
  class/function/snippet as an indented or bare paragraph — the renderer
  only recognizes fenced blocks as code.
- Headings use ATX style (# / ## / ###); keep depth at or below ###.
- Bullet lists use "- ", numbered lists use "1. "; indent nested items
  by 2 spaces per level.

CRITICAL: Include the full revised draft text in the "revised_draft" field.
If no revision is needed, set "revised_draft" to null.

Output JSON only:
{
  "oracle_name": "Beth",
  "role": "coordinator",
  "revision_decisions": [
    {
      "issue_id": "ISSUE-001",
      "decision": "accepted_defect|rejected_claim|preference_only|unresolved_question",
      "reason": "..."
    }
  ],
  "architectural_risks_remaining": ["..."],
  "revised_sections": ["..."],
  "open_questions": ["..."],
  "revised_draft": "Full revised document text here, or null if no changes needed"
}\
"""

BETH_MANUAL_SYNTHESIS_PROMPT = """\
You are Beth on Opus 4.8 high, acting as BoundState's normalizer, bundler,
and spec revisor.

You are replicating Joe's manual Oracle workflow:
1. Joe and Beth develop a preliminary spec.
2. Blind outside reviewers each review the spec independently.
3. Beth reads the raw review bundle, applies judgment, revises the spec,
   and decides whether another round is worth it.

Your job:
- Identify serious, non-duplicative issues from the blind reviews.
- Bundle related feedback into a small number of themes.
- Reject weak, speculative, stylistic, preference-only, or low-risk nitpicks.
  List each rejected/merged reviewer finding in dropped_findings with a
  reason — never silently discard a finding.
- Preserve the spec's core intent unless a reviewer found a real blocker.
- Revise the spec only where the change improves correctness, clarity,
  feasibility, compliance, product fit, or implementation readiness.
- Decide whether the review loop is converging or drifting.

Convergence policy:
- Favor convergence once serious defects are resolved.
- Round 1-2 may accept broad fixes.
- Round 3+ should treat new comments as blockers only if they are material.
- By Round 4, recommend either LOCK or HUMAN_REVIEW.
- Do not keep the loop alive for low-risk polish or model taste differences.

Recommendation values:
- LOCK: spec is good enough to proceed.
- ONE_MORE_ROUND: one more blind review is likely to improve material quality.
- HUMAN_REVIEW: judgment, domain authority, or product direction is needed.

ID discipline (both directions, enforced by the harness):
- Every issue_id in revision_decisions MUST have a matching entry in
  serious_issues. If you decide on a finding, it goes in serious_issues
  with a severity — a decision without a listed issue is untraceable.
- On rounds after the first, set recurrence_of on each serious issue to
  the prior-round issue_id it recurs from (or mutates from), or null if
  the issue is genuinely new this round. Reuse the prior issue_id itself
  whenever the issue is the same.

Markdown formatting rules for the revised_draft:
- Tables MUST use GitHub-flavored pipe-table syntax with a delimiter row.
- Code, schema, CLI, or copy-paste literal text MUST be wrapped in fences.
- Headings use ATX style (# / ## / ###); keep depth at or below ###.
- Bullet lists use "- ", numbered lists use "1. ".

Output JSON only:
{
  "oracle_name": "Beth",
  "role": "coordinator",
  "revision_decisions": [
    {
      "issue_id": "BETH-R1-ISSUE-001",
      "decision": "accepted_defect|rejected_claim|preference_only|unresolved_question",
      "reason": "..."
    }
  ],
  "serious_issues": [
    {
      "issue_id": "BETH-R1-ISSUE-001",
      "title": "...",
      "severity": "critical|high|medium|low",
      "source_reviewers": ["Fran", "Grok"],
      "summary": "...",
      "resolution": "...",
      "confidence": 0.0,
      "speculative": false,
      "recurrence_of": "prior-round issue_id, or null if genuinely new"
    }
  ],
  "dropped_findings": [
    {
      "oracle": "...",
      "title": "...",
      "reason": "duplicate|unsupported|style_only|too_vague|low_risk"
    }
  ],
  "feedback_themes": ["..."],
  "architectural_risks_remaining": ["..."],
  "revised_sections": ["..."],
  "open_questions": ["..."],
  "convergence_status": "converging|drifting|blocked",
  "recommendation": "LOCK|ONE_MORE_ROUND|HUMAN_REVIEW",
  "recommendation_reason": "...",
  "revised_draft": "Full revised document text here, or null if no changes needed"
}\
"""

FRAN_ADVERSARIAL_PROMPT = """\
You are Fran, the adversarial logic reviewer.

Primary job:
Find hidden assumptions, false precision, vague abstractions, contradictions, hand-wavy logic, unstated dependencies, and places where the document sounds stronger than it is.

Bias:
- Be skeptical of elegant language.
- Attack the plan where reality will attack it.
- Prefer structural defects over implementation trivia.
- Ask: what has to be true for this to work, and did the author actually state it?

Extra focus:
- ambiguous terms
- unclear ownership
- invalid reasoning jumps
- missing decision criteria
- undefined inputs/outputs
- failure modes not accounted for
- "this will work" claims with no mechanism

Do not focus on prose polish unless wording creates real ambiguity.
Return JSON only.\
"""

CODEX_FEASIBILITY_PROMPT = """\
You are Codex, the implementation-feasibility reviewer.

Primary job:
Determine whether this document can actually be built, tested, deployed, and maintained.

Focus:
- missing interfaces
- untestable requirements
- vague API contracts
- hidden state assumptions
- migration traps
- caching/session issues
- concurrency/failure handling gaps
- missing schemas/types
- bad separation of concerns
- repo-shape realism
- observability and rollback omissions

Questions to ask internally:
- What code modules would exist?
- What contracts are implied but unspecified?
- What breaks first during implementation?
- What cannot be verified?
- What would create integration churn?

Do not suggest broad rewrites unless the architecture is genuinely broken.
Return JSON only.\
"""

GROK_CONTRARIAN_PROMPT = """\
You are Grok, the contrarian reviewer.

Primary job:
Challenge the framing, surface edge cases, and identify where the document may be overengineered, under-scoped, or blind to alternatives.

Focus:
- edge cases
- alternative interpretations
- adversarial scenarios
- misuse/abuse conditions
- "what if the opposite assumption is true?"
- complexity inflation
- scope drift
- brittle dependencies on external actors or perfect data

Do not behave like an editor.
Do not restate obvious points.
Find what the others may miss because they accepted the frame too early.
Return JSON only.\
"""

GEMINI_REVIEWER_PROMPT = """\
You are Gemini, the broad-context review oracle.

Primary job:
Review the document from the perspective of cross-domain fit, workflow realism,
scientific/technical assumptions, operational edge cases, and places where the
spec may be locally coherent but globally wrong.

Focus:
- domain fit and missing real-world constraints
- overlooked stakeholder workflows
- scale and integration assumptions
- places where the plan relies on ideal data, ideal users, or ideal model behavior
- ambiguity that would cause different implementers to build different systems
- major omissions that other reviewers may miss because they accepted the frame

Do not behave like an editor.
Do not duplicate obvious concerns unless the draft still materially fails.
Return JSON only.\
"""

SONNET_REFEREE_PROMPT = """\
You are Sonnet, the referee oracle.

You do not review the document directly unless explicitly asked.
Your primary job is to normalize and score findings from other oracles.

Input:
- canonical draft
- reviewer JSON outputs
- current round number

Tasks:
1. Deduplicate overlapping findings.
2. Merge semantically equivalent findings into one atomic issue.
3. Assign final severity based on impact, not wording.
4. Flag unsupported or weak findings.
   For each merged issue, carry "confidence" as the LOWEST confidence
   among merged source findings (conservative), and "speculative": true
   if ANY merged source marked itself speculative.
5. Detect direct conflicts between reviewers.
6. Produce a normalized issue ledger for the coordinator.
7. If an issue was seen in prior rounds, REUSE the same issue_id so Beth
   and the convergence checker can track continuity across rounds.
8. On rounds after the first, set "recurrence_of" on EVERY issue: the
   prior-round issue_id it recurs from or is a mutation of, or null if
   the issue is genuinely new this round. Reviewers are blind across
   rounds — you are the only party that can resolve this linkage.

Rules:
- Do not invent new issues unless a cross-review contradiction reveals one.
- Keep each merged issue atomic.
- Preserve reviewer attribution.
- Be conservative with severity inflation.
- issue_id format: "R{round}-ISSUE-{N}" for new issues. Reuse prior IDs for recurring issues.

Output JSON:
{
  "oracle_name": "Sonnet",
  "role": "referee",
  "normalized_issues": [
    {
      "issue_id": "R1-ISSUE-001",
      "title": "...",
      "severity": "critical|high|medium|low",
      "category": "...",
      "merged_from": [
        {"oracle": "Fran", "title": "..."},
        {"oracle": "Codex", "title": "..."}
      ],
      "core_problem": "...",
      "best_evidence": "...",
      "recommended_fix": "...",
      "conflict_flag": false,
      "weak_signal": false,
      "confidence": 0.0,
      "speculative": false,
      "recurrence_of": "prior-round issue_id, or null if genuinely new"
    }
  ],
  "dropped_findings": [
    {
      "oracle": "...",
      "title": "...",
      "reason": "duplicate|unsupported|style_only|too_vague"
    }
  ]
}\
"""


# ---------------------------------------------------------------------------
# LLM client abstraction
# ---------------------------------------------------------------------------

# WHY 600s: multi-oracle reviews with 3 parallel calls + normalization +
# coordination can take 8-10 minutes for large documents.
PROVIDER_TIMEOUT = int(os.environ.get("ORACLE_TIMEOUT_SECONDS", "600"))
# WHY configurable: the 10s default suits normal links, but TLS handshakes
# over satellite/high-latency connections can exceed it (the HEARTH abort
# ran over airplane WiFi). The right value is environment-dependent; the
# default is unchanged because raising it globally would be a guess.
CONNECT_TIMEOUT = float(os.environ.get("ORACLE_CONNECT_TIMEOUT", "10.0"))
# WHY 24576: GPT-5.4 reviewer responses include full findings JSON + rationale;
# 24K tokens accommodates documents with 50+ findings without truncation.
OPENAI_REVIEWER_MAX_TOKENS = int(
    os.environ.get("ORACLE_OPENAI_REVIEWER_MAX_TOKENS", "24576")
)
# WHY 64000 for Beth: the coordinator emits a full JSON envelope including
# the complete `revised_draft` — a large-document rewrite can exceed
# 50K chars of output on its own.  Add adaptive-thinking consumption
# (Opus 4.6 routinely allocates 8–16K for reasoning on complex docs) and
# JSON-escaping overhead and 32K total becomes a truncation ceiling.
# 64K is the current Opus 4.6 output maximum and is the right default for
# a doc-rewriting coordinator; tune down via env var for small docs or
# cost-sensitive runs.
BETH_COORDINATOR_MAX_TOKENS = int(
    os.environ.get("ORACLE_BETH_MAX_TOKENS", "64000")
)
# WHY 16384 for Sonnet: the referee's output is the union of
# normalized_issues across every reviewer.  Round-1 reviews routinely
# normalize 30+ issues with full metadata (rule_id, severity, sources,
# matched canonical_signature) — easily 12K-15K characters of JSON.
# 8K (the dataclass default) was leaving Sonnet exposed to truncation
# on any review larger than ~20 findings.  16K gives 2x headroom; can
# be tuned via env var if reviews exceed it.
SONNET_REFEREE_MAX_TOKENS = int(
    os.environ.get("ORACLE_SONNET_MAX_TOKENS", "16384")
)
# WHY "high": reviewers must reason carefully about compliance implications;
# lower effort risks missed findings on nuanced regulatory language.
OPENAI_REASONING_EFFORT = os.environ.get("ORACLE_OPENAI_REASONING_EFFORT", "high")
OPENAI_VERBOSITY = os.environ.get("ORACLE_OPENAI_VERBOSITY", "low")
DEFAULT_WORKFLOW = os.environ.get("ORACLE_WORKFLOW", "manual").strip().lower() or "manual"
VALID_WORKFLOWS = {"manual", "ledger"}

# Required fields per oracle role — field name -> expected type
REQUIRED_SCHEMA: dict[str, dict[str, type]] = {
    "coordinator": {
        "revision_decisions": list,
        "revised_sections": list,
        "open_questions": list,
        "revised_draft": (str, type(None)),  # must be present, can be null
    },
    "adversarial_logic": {"findings": list},
    "implementation_feasibility": {"findings": list},
    "contrarian": {"findings": list},
    "domain_context": {"findings": list},
    "referee": {"normalized_issues": list},
}


@dataclass
class OracleConfig:
    """Configuration for one oracle."""
    name: str
    role: str
    provider: str       # "anthropic" | "openai" | "xai" | "gemini"
    model: str
    system_prompt: str
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout: int = PROVIDER_TIMEOUT


# Default oracle roster
ORACLE_ROSTER: dict[str, OracleConfig] = {
    "beth": OracleConfig(
        name="Beth",
        role="coordinator",
        provider="anthropic",
        model=os.environ.get("ORACLE_BETH_MODEL", "claude-opus-4-8"),
        system_prompt=BETH_COORDINATOR_PROMPT,
        temperature=0.0,
        max_tokens=BETH_COORDINATOR_MAX_TOKENS,
    ),
    "fran": OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model=os.environ.get("ORACLE_FRAN_MODEL", "gpt-5.6-terra"),
        system_prompt=FRAN_ADVERSARIAL_PROMPT,
        max_tokens=int(
            os.environ.get("ORACLE_FRAN_MAX_TOKENS", str(OPENAI_REVIEWER_MAX_TOKENS))
        ),
    ),
    "codex": OracleConfig(
        name="Codex",
        role="implementation_feasibility",
        provider="openai",
        model=os.environ.get("ORACLE_CODEX_MODEL", "gpt-5.6-terra"),
        system_prompt=CODEX_FEASIBILITY_PROMPT,
        max_tokens=int(
            os.environ.get("ORACLE_CODEX_MAX_TOKENS", str(OPENAI_REVIEWER_MAX_TOKENS))
        ),
    ),
    "grok": OracleConfig(
        name="Grok",
        role="contrarian",
        provider="xai",
        model=os.environ.get("ORACLE_GROK_MODEL", "grok-4.5"),
        system_prompt=GROK_CONTRARIAN_PROMPT,
    ),
    "gemini": OracleConfig(
        name="Gemini",
        role="domain_context",
        provider="gemini",
        model=os.environ.get("ORACLE_GEMINI_MODEL", "gemini-3.5-flash"),
        system_prompt=GEMINI_REVIEWER_PROMPT,
        max_tokens=int(os.environ.get("ORACLE_GEMINI_MAX_TOKENS", "8192")),
    ),
    "sonnet": OracleConfig(
        name="Sonnet",
        role="referee",
        provider="anthropic",
        model=os.environ.get("ORACLE_SONNET_MODEL", "claude-sonnet-4-6"),
        system_prompt=SONNET_REFEREE_PROMPT,
        max_tokens=SONNET_REFEREE_MAX_TOKENS,
    ),
}


def _call_anthropic(config: OracleConfig, user_message: str) -> dict:
    """Call Anthropic Messages API (Beth / Sonnet) via streaming.

    Uses `client.messages.stream()` + `get_final_message()` instead of
    `messages.create()` because non-streaming requests over 10 minutes are
    not supported by the Anthropic API. Beth with extended thinking on a
    large input regularly exceeds that ceiling, so streaming is mandatory.
    See https://docs.anthropic.com/en/api/errors#long-requests.
    """
    import httpx
    from anthropic import Anthropic

    client = Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=httpx.Timeout(config.timeout, connect=CONNECT_TIMEOUT),
        max_retries=0,
    )
    kwargs: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": config.system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    if "opus" in config.model:
        # Adaptive thinking: the model sizes its own reasoning budget per turn.
        # budget_tokens is deprecated on Opus 4.6 / Sonnet 4.6 and will be
        # removed in a future model release. Temperature must be 1 for any
        # thinking mode.
        kwargs["temperature"] = 1
        kwargs["thinking"] = {"type": "adaptive"}
    else:
        kwargs["temperature"] = config.temperature

    with client.messages.stream(**kwargs) as stream:
        final_message = stream.get_final_message()

    text = ""
    for block in final_message.content:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    result = _parse_json(text, config.name)
    usage = getattr(final_message, "usage", None)
    result["_telemetry"] = {
        "response_model": getattr(final_message, "model", None),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "temperature": kwargs.get("temperature"),
        "thinking": "adaptive" if "thinking" in kwargs else None,
    }
    return result


def _openai_reviewer_response_format(config: OracleConfig) -> dict[str, Any]:
    """Return a strict structured-output contract for OpenAI reviewers."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"oracle_{config.role}_review",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "oracle_name": {"type": "string"},
                    "role": {"type": "string"},
                    "document_type": {"type": "string"},
                    "overall_verdict": {
                        "type": "string",
                        "enum": [
                            "approve_with_minor_changes",
                            "revise",
                            "major_revision",
                        ],
                    },
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["critical", "high", "medium", "low"],
                                },
                                "category": {"type": "string"},
                                "location": {"type": "string"},
                                "evidence": {"type": "string"},
                                "problem": {"type": "string"},
                                "why_it_matters": {"type": "string"},
                                "proposed_fix": {"type": "string"},
                                "confidence": {"type": "number"},
                                # WHY: the shared contract demands marking
                                # speculative concerns, but a strict schema
                                # with additionalProperties:false FORBADE
                                # the marker — the uncertainty label had
                                # nowhere to live (AUDIT A9).
                                "speculative": {"type": "boolean"},
                            },
                            "required": [
                                "title",
                                "severity",
                                "category",
                                "location",
                                "evidence",
                                "problem",
                                "why_it_matters",
                                "proposed_fix",
                                "confidence",
                                "speculative",
                            ],
                        },
                    },
                    "top_3_must_fix": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "oracle_name",
                    "role",
                    "document_type",
                    "overall_verdict",
                    "findings",
                    "top_3_must_fix",
                ],
            },
        },
    }


def _call_openai(config: OracleConfig, user_message: str) -> dict:
    """Call OpenAI Chat Completions API (Fran / Codex)."""
    import httpx
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        timeout=httpx.Timeout(config.timeout, connect=CONNECT_TIMEOUT),
    )
    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    if config.model.startswith(("gpt-5", "o3", "o4")):
        kwargs["max_completion_tokens"] = config.max_tokens
        kwargs["reasoning_effort"] = OPENAI_REASONING_EFFORT
        kwargs["verbosity"] = OPENAI_VERBOSITY
        kwargs["response_format"] = _openai_reviewer_response_format(config)
    else:
        kwargs["temperature"] = config.temperature
        kwargs["max_tokens"] = config.max_tokens
    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    message = choice.message
    text = (message.content or "").strip()

    # Usage capture (AUDIT D1): getattr-safe because SDK fakes in tests
    # (and older SDK versions) may omit usage/model attributes entirely.
    usage = getattr(response, "usage", None)
    telemetry = {
        "response_model": getattr(response, "model", None),
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "temperature": kwargs.get("temperature"),
        "reasoning_effort": kwargs.get("reasoning_effort"),
    }

    if choice.finish_reason == "length":
        LOGGER.warning(
            f"[{config.name}] OpenAI hit max completion budget "
            f"(max_completion_tokens={config.max_tokens})"
        )

    if message.refusal:
        LOGGER.error(f"[{config.name}] OpenAI refusal: {message.refusal[:400]}")
        return {
            "oracle_name": config.name,
            "error": "Model refusal",
            "raw": redact_secrets(message.refusal[:2000]),
            "_telemetry": telemetry,
        }

    if not text:
        LOGGER.error(
            f"[{config.name}] Empty OpenAI response "
            f"(finish_reason={choice.finish_reason})"
        )
        return {
            "oracle_name": config.name,
            "error": f"Empty response (finish_reason={choice.finish_reason})",
            "raw": "",
            "_telemetry": telemetry,
        }

    result = _parse_json(text, config.name)
    result["_telemetry"] = telemetry
    return result


def _call_xai(config: OracleConfig, user_message: str) -> dict:
    """Call xAI/Grok API (OpenAI-compatible endpoint)."""
    import httpx
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ.get("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
        timeout=httpx.Timeout(config.timeout, connect=CONNECT_TIMEOUT),
    )
    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    if "reasoning" in config.model or "4.20" in config.model:
        kwargs["max_completion_tokens"] = config.max_tokens
    else:
        kwargs["temperature"] = config.temperature
        kwargs["max_tokens"] = config.max_tokens
    # WHY behind a flag, default OFF: xAI's endpoint is OpenAI-compatible,
    # but its support for this strict response_format schema has not been
    # verified with a live call (AUDIT C4). Saying "Grok output is
    # schema-enforced" without that verification would be a lie about
    # robustness. Flip on (ORACLE_XAI_JSON_MODE=1) after a green
    # eval/live run confirms the endpoint honors it.
    if os.environ.get("ORACLE_XAI_JSON_MODE", "").strip().lower() in {"1", "true", "yes"}:
        kwargs["response_format"] = _openai_reviewer_response_format(config)
    response = client.chat.completions.create(**kwargs)
    text = response.choices[0].message.content or ""
    result = _parse_json(text, config.name)
    usage = getattr(response, "usage", None)
    result["_telemetry"] = {
        "response_model": getattr(response, "model", None),
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "temperature": kwargs.get("temperature"),
    }
    return result


def _call_gemini(config: OracleConfig, user_message: str) -> dict:
    """Call Google Gemini generateContent REST API."""
    import httpx

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {
            "oracle_name": config.name,
            "error": "GEMINI_API_KEY or GOOGLE_API_KEY not set",
            "findings": [],
        }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.model}:generateContent"
    )
    payload = {
        "systemInstruction": {
            "parts": [{"text": config.system_prompt}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_message}],
            }
        ],
        "generationConfig": {
            "temperature": config.temperature,
            "maxOutputTokens": config.max_tokens,
            "responseMimeType": "application/json",
        },
    }

    with httpx.Client(timeout=httpx.Timeout(config.timeout, connect=CONNECT_TIMEOUT)) as client:
        response = client.post(
            url,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code >= 400:
        # Surface Google's structured error reason (status + message) in the
        # error string itself — otherwise the only signal that reaches the logs
        # is a bare status code, and the actual cause (RESOURCE_EXHAUSTED,
        # billing disabled, PERMISSION_DENIED, etc.) is buried in `raw` and
        # never printed. Keep the literal "Gemini API error {code}" substring
        # intact so _should_fallback_gemini() still matches on status code.
        detail = ""
        try:
            err_obj = response.json().get("error", {}) or {}
            parts = [p for p in (err_obj.get("status"), (err_obj.get("message") or "")[:300]) if p]
            if parts:
                detail = f" ({': '.join(parts)})"
        except (ValueError, AttributeError):
            detail = ""
        return {
            "oracle_name": config.name,
            "error": f"Gemini API error {response.status_code}{detail}",
            "raw": redact_secrets(response.text[:2000]),
            "findings": [],
        }

    data = response.json()
    usage = data.get("usageMetadata") or {}
    telemetry = {
        "response_model": data.get("modelVersion") or config.model,
        "input_tokens": usage.get("promptTokenCount"),
        "output_tokens": usage.get("candidatesTokenCount"),
        "temperature": config.temperature,
    }
    candidates = data.get("candidates") or []
    if not candidates:
        return {
            "oracle_name": config.name,
            "error": "Gemini returned no candidates",
            "raw": redact_secrets(json.dumps(data)[:2000]),
            "findings": [],
            "_telemetry": telemetry,
        }

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    ).strip()
    if not text:
        finish_reason = candidates[0].get("finishReason", "unknown")
        return {
            "oracle_name": config.name,
            "error": f"Gemini returned empty content (finishReason={finish_reason})",
            "raw": redact_secrets(json.dumps(data)[:2000]),
            "findings": [],
            "_telemetry": telemetry,
        }

    result = _parse_json(text, config.name)
    result["_telemetry"] = telemetry
    return result


PROVIDER_DISPATCH = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "xai": _call_xai,
    "gemini": _call_gemini,
}


MAX_RETRIES = 3
RETRY_BACKOFF = (2, 4, 8)  # seconds
# WHY 2: one invalid round can be a transient blip (rate limit, brief
# outage); two in a row means a vendor is systemically down and further
# rounds only burn spend on the healthy vendors (AUDIT C2).
MAX_CONSECUTIVE_INVALID_ROUNDS = int(
    os.environ.get("ORACLE_MAX_CONSECUTIVE_INVALID_ROUNDS", "2")
)
GEMINI_FALLBACK_ERROR_STATUSES = ("429", "500", "502", "503", "504")
# WHY 4x for rate limits: a 429 means the quota window is exhausted;
# retrying on the transient-error schedule usually re-hits the same
# window and burns the attempt (then the round, then the run — AUDIT C3).
RATE_LIMIT_BACKOFF_MULTIPLIER = 4
# WHY cap: a pathological Retry-After header (or multiplied growth) must
# not stall a round indefinitely; 120s exceeds standard vendor rate-limit
# windows while keeping worst-case round latency bounded.
MAX_RETRY_DELAY_SECONDS = 120.0


def _retry_delay(attempt: int, last_failure: Any) -> float:
    """Seconds to wait before retry `attempt`, honoring Retry-After.

    Precedence: a vendor-stated Retry-After beats the local schedule; a
    429-shaped failure quadruples the base; everything gets jitter
    because four reviewers retry in parallel and synchronized retries
    re-spike the same rate limit.
    """
    base = float(RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)])

    response = getattr(last_failure, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            retry_after = float(headers.get("retry-after"))
        except (TypeError, ValueError):
            retry_after = None
        if retry_after is not None and retry_after >= 0:
            return min(max(retry_after, base), MAX_RETRY_DELAY_SECONDS)

    if "429" in str(last_failure or ""):
        base *= RATE_LIMIT_BACKOFF_MULTIPLIER
    return min(base + random.uniform(0, base * 0.25), MAX_RETRY_DELAY_SECONDS)


def _should_fallback_gemini(config: OracleConfig, last_error: str | None) -> bool:
    """Use Flash when Gemini Pro is quota-blocked or temporarily unavailable."""
    if config.provider != "gemini" or not last_error:
        return False
    fallback_model = os.environ.get("ORACLE_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
    if not fallback_model or fallback_model == config.model:
        return False
    return any(f"Gemini API error {status}" in last_error for status in GEMINI_FALLBACK_ERROR_STATUSES)


class OracleCallError(RuntimeError):
    """All retries exhausted for one oracle call.

    Carries the per-attempt forensic log so a failure persists with
    enough detail to classify after the fact (network vs API vs format).
    WHY: the zero-finding HEARTH abort (sessions 20260611-162307 /
    f843b5593ebb) was unclassifiable because failed calls persisted only
    an error STRING — which is empty for raw httpx network exceptions
    (str(httpx.ConnectTimeout(...)) == ""), and no status, class, or
    per-attempt latency survived anywhere.
    """

    def __init__(self, message: str, attempt_log: list[dict] | None = None):
        super().__init__(message)
        self.attempt_log: list[dict] = attempt_log or []


def _describe_exception(e: Exception) -> dict:
    """Forensic record of one failed attempt: class, status, message."""
    status_code = getattr(e, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
    return {
        "failure_class": type(e).__name__,
        "status_code": status_code,
        # Raw httpx exceptions stringify to "" — the class name above is
        # then the only signal, and the message must say so explicitly.
        "error": redact_secrets(str(e)) or "(exception carried no message)",
    }


class OracleAuthError(RuntimeError):
    """Raised when a provider rejects the configured API key (HTTP 401).

    WHY a distinct type: an authentication failure is categorically different
    from a transient error. A revoked, malformed, or wrong-workspace key will
    be rejected on every attempt, so callers must be able to distinguish "the
    key is dead, stop everything" from "the model hiccuped, try again." A
    dedicated subclass lets the orchestrator and the server surface this as an
    operator-actionable configuration fault rather than burying it in a generic
    "failed after N attempts" message.
    """


def _is_auth_error(exc: Exception) -> bool:
    """True when an exception represents a provider authentication failure.

    WHY: Both the Anthropic and OpenAI SDKs (xAI reuses the OpenAI client)
    raise APIStatusError subclasses that expose the HTTP status as
    `status_code`, so a single 401 check covers all three providers without
    importing each SDK's exception hierarchy into this module. The class-name
    fallback catches SDK versions that surface the status differently but still
    name the type `AuthenticationError`.
    """
    if getattr(exc, "status_code", None) == 401:
        return True
    if getattr(exc, "status", None) == 401:
        return True
    return type(exc).__name__ == "AuthenticationError"


def call_oracle(config: OracleConfig, user_message: str) -> dict:
    """Route to the correct provider with retries and backoff.

    Raises OracleCallError (with a per-attempt forensic log) after all
    retries are exhausted.
    """
    dispatch = PROVIDER_DISPATCH.get(config.provider)
    if not dispatch:
        raise ValueError(f"Unknown provider: {config.provider}")

    last_error = None
    # last_failure keeps the exception OBJECT where one exists (so
    # _retry_delay can read Retry-After headers); otherwise the error
    # string (still usable for 429 detection).
    last_failure: Any = None
    attempt_log: list[dict] = []
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            wait = _retry_delay(attempt, last_failure)
            LOGGER.warning(f"[{config.name}] Retry {attempt}/{MAX_RETRIES} after {wait:.1f}s...")
            time.sleep(wait)

        LOGGER.info(f"[{config.name}] Calling {config.provider}/{config.model} (attempt {attempt + 1})...")
        t0 = time.time()
        try:
            result = dispatch(config, user_message)
            elapsed = time.time() - t0

            # Validate: must have parsed successfully (no "error" key from _parse_json)
            if "error" in result and "raw" in result:
                LOGGER.warning(f"[{config.name}] Parse failed: {result['error']}")
                last_error = result["error"]
                last_failure = last_error
                attempt_log.append({
                    "attempt": attempt + 1,
                    "elapsed_seconds": round(elapsed, 2),
                    "failure_class": "ParseOrProviderError",
                    "status_code": None,
                    "error": last_error,
                })
                continue

            # Schema validation: check required fields for this oracle's role
            schema_error = _validate_schema(result, config)
            if schema_error:
                LOGGER.warning(f"[{config.name}] Schema invalid: {schema_error}")
                last_error = f"Schema: {schema_error}"
                last_failure = last_error
                attempt_log.append({
                    "attempt": attempt + 1,
                    "elapsed_seconds": round(elapsed, 2),
                    "failure_class": "SchemaValidationError",
                    "status_code": None,
                    "error": last_error,
                })
                continue

            findings_count = len(result.get("findings", result.get("normalized_issues", [])))
            if result.get("recovered_partial"):
                LOGGER.warning(
                    f"[{config.name}] DEGRADED: {result.get('recovery_note', 'partial recovery')}"
                )

            # Enrich provider telemetry with call-level facts (AUDIT C1/D1):
            # configured vs actual model is the only way a silent vendor
            # model swap is ever detectable after the fact.
            telemetry = result.get("_telemetry")
            if not isinstance(telemetry, dict):
                telemetry = {}
                result["_telemetry"] = telemetry
            telemetry.update({
                "oracle": config.name,
                "provider": config.provider,
                "configured_model": config.model,
                "max_tokens": config.max_tokens,
                "latency_seconds": round(elapsed, 2),
                "attempts": attempt + 1,
            })
            if attempt_log:
                # Earlier attempts failed — keep their forensics on the
                # successful result too.
                telemetry["attempt_log"] = attempt_log

            LOGGER.info(f"[{config.name}] Done in {elapsed:.1f}s — {findings_count} findings")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            # Authentication failures are not transient: a rejected key is
            # rejected identically on every attempt. Fail hard immediately
            # instead of burning the backoff schedule (and the Gemini
            # fallback) and hiding the cause under a generic "failed after N
            # attempts" error. This is the exact failure that masqueraded as a
            # flaky retry loop during the ANTHROPIC_API_KEY rotation incident.
            if _is_auth_error(e):
                raise OracleAuthError(
                    f"[{config.name}] Authentication failed for provider "
                    f"'{config.provider}' (HTTP 401 invalid API key). The "
                    f"configured key is missing, malformed, revoked, or scoped "
                    f"to the wrong workspace. Fix the provider key and redeploy "
                    f"— retrying cannot succeed."
                ) from e
            failure = _describe_exception(e)
            failure["attempt"] = attempt + 1
            failure["elapsed_seconds"] = round(elapsed, 2)
            attempt_log.append(failure)
            # Class name in the log line because raw httpx network
            # exceptions stringify to "" (verified) — a blank error line
            # made the HEARTH abort unclassifiable.
            last_error = f"{failure['failure_class']}: {failure['error']}"
            last_failure = e
            LOGGER.error(f"[{config.name}] Failed in {elapsed:.1f}s: {last_error}")

    if _should_fallback_gemini(config, last_error):
        fallback_model = os.environ.get("ORACLE_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
        fallback_tokens = int(
            os.environ.get("ORACLE_GEMINI_FALLBACK_MAX_TOKENS", str(config.max_tokens))
        )
        fallback_config = OracleConfig(
            name=config.name,
            role=config.role,
            provider=config.provider,
            model=fallback_model,
            system_prompt=config.system_prompt,
            temperature=config.temperature,
            max_tokens=fallback_tokens,
            timeout=config.timeout,
        )
        LOGGER.warning(
            "[%s] Primary Gemini model %s failed after retries (%s); falling back to %s",
            config.name,
            config.model,
            last_error,
            fallback_model,
        )
        result = call_oracle(fallback_config, user_message)
        result["primary_model_error"] = last_error
        result["fallback_model_used"] = fallback_model
        return result

    # All retries exhausted — raise with the forensic log attached so the
    # caller can persist it (round telemetry) instead of losing it.
    raise OracleCallError(
        f"[{config.name}] Failed after {MAX_RETRIES} attempts: {last_error}",
        attempt_log=attempt_log,
    )


def _validate_schema(result: dict, config: OracleConfig) -> str | None:
    """Validate oracle response: required fields, types, and list item structure."""
    schema = REQUIRED_SCHEMA.get(config.role, {})

    # Check field presence and type
    for field_name, expected_type in schema.items():
        if field_name not in result:
            return f"Missing required field: {field_name}"
        value = result[field_name]
        if isinstance(expected_type, tuple):
            # Union type (e.g., str | None)
            if not isinstance(value, expected_type):
                return f"{field_name}: expected {expected_type}, got {type(value).__name__}"
        elif not isinstance(value, expected_type):
            return f"{field_name}: expected {expected_type.__name__}, got {type(value).__name__}"

    # Validate list item structure for key lists
    if config.role == "referee":
        for i, issue in enumerate(result.get("normalized_issues", [])):
            if not isinstance(issue, dict):
                return f"normalized_issues[{i}]: expected dict, got {type(issue).__name__}"
            if not issue.get("issue_id"):
                return f"normalized_issues[{i}]: missing issue_id"
            if not issue.get("severity"):
                return f"normalized_issues[{i}]: missing severity"

    if config.role == "coordinator":
        for i, dec in enumerate(result.get("revision_decisions", [])):
            if not isinstance(dec, dict):
                return f"revision_decisions[{i}]: expected dict, got {type(dec).__name__}"
            if not dec.get("issue_id"):
                return f"revision_decisions[{i}]: missing issue_id"
            if not dec.get("decision"):
                return f"revision_decisions[{i}]: missing decision"

    if config.role in (
        "adversarial_logic",
        "implementation_feasibility",
        "contrarian",
        "domain_context",
    ):
        for i, finding in enumerate(result.get("findings", [])):
            if not isinstance(finding, dict):
                return f"findings[{i}]: expected dict, got {type(finding).__name__}"
            if not finding.get("title"):
                return f"findings[{i}]: missing title"
            if not finding.get("severity"):
                return f"findings[{i}]: missing severity"

    return None


def _parse_json(text: str, oracle_name: str) -> dict:
    """Extract the first balanced JSON object from LLM response."""
    text = text.strip()
    preview = " ".join(text.split())[:240]

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Find the first '{' and extract the balanced JSON object
    start = text.find("{")
    if start == -1:
        LOGGER.error(
            f"[{oracle_name}] No JSON object found in response. Preview: {preview!r}"
        )
        return {"oracle_name": oracle_name, "error": "No JSON found", "raw": redact_secrets(text[:2000])}

    depth = 0
    in_string = False
    escape_next = False
    end = start

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if depth != 0:
        LOGGER.warning(f"[{oracle_name}] Unbalanced braces — attempting truncated recovery")
        return _recover_truncated_json(text, oracle_name)

    candidate = text[start:end]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        LOGGER.warning(
            f"[{oracle_name}] JSON parse error: {e} — attempting recovery. "
            f"Preview: {preview!r}"
        )
        return _recover_truncated_json(text, oracle_name)


def _recover_array_field(text: str, field_name: str) -> list | None:
    """Walk a JSON array string and return as many well-formed top-level
    elements as can be parsed before the first malformed / truncated one.

    Used when an oracle response either truncates mid-array or contains
    a malformed element partway through.  Each top-level element is an
    object (`{...}`); we balance braces to find element boundaries, then
    `json.loads` each candidate independently.  An element that fails
    to parse stops the walk — earlier well-formed elements are returned.

    Returns None when the named array key is not present in the text.
    Returns [] when the key is present but no element can be salvaged.
    """
    import re
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*\[', text)
    if match is None:
        return None

    pos = match.end()
    elements: list = []
    while pos < len(text):
        # Skip whitespace and trailing commas between elements
        while pos < len(text) and text[pos] in ' \t\n\r,':
            pos += 1
        if pos >= len(text) or text[pos] == ']':
            break
        if text[pos] != '{':
            # Unexpected character — stop walk
            break
        # Find the balanced object starting at pos
        depth = 0
        in_string = False
        escape_next = False
        end = pos
        for i in range(pos, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if depth != 0:
            # Truncated mid-element — stop, return what we have
            break
        try:
            elements.append(json.loads(text[pos:end]))
        except json.JSONDecodeError:
            # Malformed element — stop walk; downstream sees what was parseable
            break
        pos = end
    return elements


def _recover_truncated_json(text: str, oracle_name: str) -> dict:
    """Best-effort partial-content recovery from a malformed JSON response.

    Originally Beth-specific (for revised_draft truncation); now generic
    so any oracle's expected top-level array (revised_draft,
    revision_decisions, normalized_issues, findings) can be partially
    salvaged.  A degraded round with N-1 findings is far less harmful
    than a failed round with zero.
    """
    import re

    result: dict = {"oracle_name": oracle_name}

    # --- Beth-specific recovery: revised_draft (a string field) ---
    draft_match = re.search(r'"revised_draft"\s*:\s*"', text)
    if draft_match:
        draft_start = draft_match.end()
        # Find the end of the string — look for unescaped quote
        pos = draft_start
        while pos < len(text):
            if text[pos] == '\\':
                pos += 2
                continue
            if text[pos] == '"':
                break
            pos += 1
        if pos < len(text):
            raw_draft = text[draft_start:pos]
            try:
                revised = json.loads(f'"{raw_draft}"')
                result["revised_draft"] = revised
                LOGGER.info(f"[{oracle_name}] Recovered revised_draft ({len(revised)} chars)")
            except Exception:
                result["revised_draft"] = raw_draft.replace("\\n", "\n").replace('\\"', '"')
                LOGGER.info(f"[{oracle_name}] Recovered raw revised_draft ({len(raw_draft)} chars)")
        else:
            # Truncated mid-draft — take what we have
            raw_draft = text[draft_start:]
            result["revised_draft"] = raw_draft.replace("\\n", "\n").replace('\\"', '"')
            LOGGER.info(f"[{oracle_name}] Recovered truncated revised_draft ({len(raw_draft)} chars)")

    # --- Generic array-field recovery (works for any oracle role) ---
    # Try every known array key.  Whichever one(s) appear in the text
    # get partially salvaged; missing keys get default empty lists.
    for field in (
        "revision_decisions",       # Beth (coordinator)
        "revised_sections",         # Beth (coordinator)
        "open_questions",           # Beth (coordinator)
        "normalized_issues",        # Sonnet (referee)
        "findings",                 # Fran / Codex / Grok / Gemini (reviewers)
    ):
        recovered = _recover_array_field(text, field)
        if recovered is not None:
            result[field] = recovered
            if recovered:
                LOGGER.info(
                    f"[{oracle_name}] Recovered {len(recovered)} element(s) "
                    f"for {field!r} from malformed response"
                )

    # Defaults for missing Beth-shape fields
    result.setdefault("revision_decisions", [])
    result.setdefault("revised_sections", [])
    result.setdefault("open_questions", [])

    # If nothing of substance was recovered, surface the parse failure
    # so the retry loop kicks in.
    has_content = (
        "revised_draft" in result
        or any(result.get(f) for f in (
            "revision_decisions", "normalized_issues", "findings",
        ))
    )
    if not has_content:
        LOGGER.error(f"[{oracle_name}] Could not recover any content from malformed response")
        result["error"] = "Malformed JSON, no recoverable content"
        result["raw"] = redact_secrets(text[:2000])
    else:
        # WHY flag the salvage: a partially recovered response used to be
        # indistinguishable from a complete one, so a reviewer whose last
        # N findings were truncated participated in convergence as if it
        # had said everything it had to say (AUDIT B2). The flag persists
        # into the round files and surfaces in the findings report.
        result["recovered_partial"] = True
        salvaged: dict[str, int] = {
            f: len(result[f])
            for f in ("revision_decisions", "normalized_issues", "findings")
            if result.get(f)
        }
        if "revised_draft" in result and isinstance(result["revised_draft"], str):
            salvaged["revised_draft_chars"] = len(result["revised_draft"])
        result["recovery_note"] = (
            f"Response was malformed/truncated; salvaged {salvaged}. "
            f"The full response may have contained more content."
        )

    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

@dataclass
class ReviewRound:
    """State for one review round."""
    round_number: int
    reviewer_outputs: dict[str, dict] = field(default_factory=dict)
    normalized_issues: dict = field(default_factory=dict)
    coordinator_decisions: dict = field(default_factory=dict)
    revised_draft: str = ""
    valid: bool = False  # True only if the round met quorum and synthesis ran
    # Per-oracle call telemetry (models, tokens, latency — AUDIT C1/D1).
    # Kept OUT of the oracle output dicts so it never leaks into the
    # prompts that re-serialize those outputs for Beth/Sonnet.
    telemetry: dict[str, dict] = field(default_factory=dict)
    # Reviewers that failed when the round proceeded anyway on a degraded
    # quorum. Empty for full rounds. Disclosed in the report; a non-empty
    # list caps consensus at stable_with_notes.
    missing_reviewers: list[str] = field(default_factory=list)


def _last_valid_round(session: OracleSession) -> ReviewRound | None:
    """Return the most recent valid round, or None."""
    for r in reversed(session.rounds):
        if r.valid:
            return r
    return None


def _last_two_valid_rounds(session: OracleSession) -> tuple[ReviewRound | None, ReviewRound | None]:
    """Return (previous_valid, current_valid) — the two most recent valid rounds."""
    valid = [r for r in session.rounds if r.valid]
    if len(valid) < 2:
        return (None, None)
    return (valid[-2], valid[-1])


@dataclass
class OracleSession:
    """Full oracle review session."""
    session_id: str
    document_path: str
    original_draft: str
    canonical_draft: str
    rounds: list[ReviewRound] = field(default_factory=list)
    converged: bool = False
    convergence_reason: str = ""
    # WHY consensus_type: "converged: bool" alone cannot distinguish
    # "everyone agrees" from "the loop stopped on a standing disagreement".
    # Collapsing those was AUDIT finding A2 (false consensus). Values:
    #   full_agreement    — converged, no outstanding high findings
    #   stable_with_notes — converged, but open questions / 1 high remain
    #   blocked           — stopped WITHOUT consensus (repeated tradeoff,
    #                       human-review escalation, or exhausted rounds)
    #   ""                — loop has not stopped yet
    consensus_type: str = ""


# The blind-review pool.
REQUIRED_REVIEWERS = ("fran", "codex", "grok")


def _min_valid_reviewers() -> int:
    """Quorum: how many reviewers must succeed for a round to be usable.

    WHY default 2 (per the HEARTH failure handoff): one unreachable vendor
    previously discarded the entire round — three valid reviews thrown
    away, twice, producing a zero-finding abort. WHY the floor is hard 2:
    a single reviewer is not a cross-check of anything; below 2 the
    "consensus" label would be a lie regardless of disclosure.
    """
    configured = int(os.environ.get("ORACLE_MIN_VALID_REVIEWERS", "2"))
    if configured < 2:
        LOGGER.warning(
            "ORACLE_MIN_VALID_REVIEWERS=%d is below the hard floor; using 2",
            configured,
        )
        return 2
    return configured


def _is_failed_output(output: dict) -> bool:
    """True for the error placeholder a failed reviewer call leaves behind."""
    return isinstance(output, dict) and "error" in output and not output.get("findings")


def _fan_out_reviewers(
    review_round: ReviewRound,
    review_msg: str,
    output_dir: Path,
    round_num: int,
) -> bool:
    """Run the blind reviewers in parallel; persist outputs + telemetry.

    Returns True when the round is usable: either every reviewer
    succeeded, or at least ORACLE_MIN_VALID_REVIEWERS did (degraded
    quorum — failed reviewers are recorded in round.missing_reviewers
    and their error placeholders never reach synthesis).

    Why extracted: this block was duplicated verbatim between the manual
    and ledger runners — that duplication is how the F1 filename
    divergence went unnoticed. One copy, two callers.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _call_reviewer(key: str) -> tuple[str, dict]:
        config = ORACLE_ROSTER[key]
        try:
            result = call_oracle(config, review_msg)
            return config.name, result
        except OracleAuthError:
            # A dead key is a configuration fault, not a reviewer failure.
            # Propagate (it surfaces via future.result()) so the run aborts
            # loudly instead of degrading to a missing-reviewer quorum round
            # after round. Must precede OracleCallError/Exception — it is a
            # sibling of OracleCallError, not a subclass, so it would
            # otherwise be swallowed into an error placeholder.
            raise
        except OracleCallError as e:
            LOGGER.error(f"[{config.name}] FAILED after retries: {e}")
            return config.name, {
                "oracle_name": config.name,
                "error": str(e),
                "findings": [],
                # Forensics for the failure matrix: per-attempt class,
                # status, latency (the HEARTH abort persisted none of this).
                "_telemetry": {
                    "oracle": config.name,
                    "provider": config.provider,
                    "configured_model": config.model,
                    "failed": True,
                    "attempt_log": e.attempt_log,
                },
            }
        except Exception as e:
            LOGGER.error(f"[{config.name}] FAILED after retries: {e}")
            return config.name, {
                "oracle_name": config.name,
                "error": redact_secrets(str(e)) or type(e).__name__,
                "findings": [],
                "_telemetry": {
                    "oracle": config.name,
                    "provider": config.provider,
                    "configured_model": config.model,
                    "failed": True,
                    "attempt_log": [_describe_exception(e)],
                },
            }

    LOGGER.info(f"  Launching {len(REQUIRED_REVIEWERS)} blind reviewers in parallel...")
    with ThreadPoolExecutor(max_workers=len(REQUIRED_REVIEWERS)) as pool:
        futures = {pool.submit(_call_reviewer, key): key for key in REQUIRED_REVIEWERS}
        for future in as_completed(futures):
            name, result = future.result()
            # Pop telemetry before the output dict is re-serialized into
            # any downstream prompt or written as the oracle's output file.
            review_round.telemetry[name] = result.pop("_telemetry", None) or {}
            review_round.reviewer_outputs[name] = result

    for name, output in review_round.reviewer_outputs.items():
        (output_dir / f"round{round_num}_{name.lower()}.json").write_text(
            encoding="utf-8", data=json.dumps(output, indent=2)
        )
    _write_round_telemetry(output_dir, round_num, review_round)

    failed = sorted(
        name for name, output in review_round.reviewer_outputs.items()
        if _is_failed_output(output)
    )
    if not failed:
        return True

    valid_count = len(review_round.reviewer_outputs) - len(failed)
    if valid_count >= _min_valid_reviewers():
        review_round.missing_reviewers = failed
        LOGGER.warning(
            f"Round {round_num} DEGRADED: proceeding with quorum "
            f"{valid_count}/{len(review_round.reviewer_outputs)}; "
            f"failed: {', '.join(failed)}"
        )
        return True

    LOGGER.error(
        f"Round {round_num} below quorum: only {valid_count} valid reviewer(s); "
        f"failed: {', '.join(failed)}"
    )
    return False


def _valid_reviewer_outputs(review_round: ReviewRound) -> dict[str, dict]:
    """Reviewer outputs minus failure placeholders.

    Fail-closed: synthesis must only ever see validated reviewer content —
    an error placeholder is not a review and must not enter any prompt.
    """
    return {
        name: output
        for name, output in review_round.reviewer_outputs.items()
        if not _is_failed_output(output)
    }


def _apply_revised_draft(session: OracleSession, review_round: ReviewRound, beth_response: dict) -> None:
    """Adopt Beth's revised draft as canonical, if she produced one."""
    revised = beth_response.get("revised_draft")
    if revised and isinstance(revised, str) and revised.strip():
        session.canonical_draft = revised.strip()
        review_round.revised_draft = session.canonical_draft
        LOGGER.info(f"[Beth] Draft revised ({len(session.canonical_draft)} chars)")
    else:
        LOGGER.info("[Beth] No revision to draft this round")


def _persist_beth_outputs(
    output_dir: Path,
    round_num: int,
    beth_response: dict,
    review_round: ReviewRound,
) -> None:
    """Write Beth's decisions and any revised draft for one round."""
    (output_dir / f"round{round_num}_beth_decisions.json").write_text(
        encoding="utf-8", data=json.dumps(beth_response, indent=2)
    )
    if review_round.revised_draft:
        (output_dir / f"round{round_num}_revised_draft.md").write_text(
            encoding="utf-8", data=review_round.revised_draft
        )


def _write_round_telemetry(output_dir: Path, round_num: int, review_round: ReviewRound) -> None:
    """Persist per-oracle call telemetry for one round (AUDIT C1/D1).

    Written after the reviewer fan-out and rewritten after the synthesis
    calls so a round that dies mid-way still records what it spent.
    """
    (output_dir / f"round{round_num}_telemetry.json").write_text(
        encoding="utf-8", data=json.dumps(review_round.telemetry, indent=2)
    )


def _with_system_prompt(config: OracleConfig, system_prompt: str) -> OracleConfig:
    """Return a copy of an oracle config with a one-off system prompt."""
    return OracleConfig(
        name=config.name,
        role=config.role,
        provider=config.provider,
        model=config.model,
        system_prompt=system_prompt,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
    )


def _build_review_message(
    draft: str,
    round_number: int,
    changed_sections: list[str] | None = None,
    compliance_context: str | None = None,
) -> str:
    """Build the user message for reviewers."""
    msg = SHARED_CONTRACT

    if compliance_context:
        msg += (
            "\n\n---\n\n"
            "## Compliance Rule Pack\n\n"
            "The following regulatory requirements are the authoritative standard "
            "for this review. Evaluate the document for compliance against these "
            "requirements. Flag any requirement that the document fails to address, "
            "contradicts, or incompletely satisfies.\n\n"
            f"{compliance_context}"
        )

    msg += f"\n\n---\n\n## Document to Review (Round {round_number})\n\n{draft}"
    if changed_sections:
        msg += f"\n\n## Changed Sections Since Last Round\n\n" + "\n".join(f"- {s}" for s in changed_sections)
        msg += "\n\nFocus your review on the changed sections and any unresolved issues from prior rounds."
    return msg


def _reviewer_contract_json_schema() -> str:
    """Compact reviewer output contract for manual workflow."""
    return """
Return JSON only:
{
  "oracle_name": "...",
  "role": "...",
  "document_type": "...",
  "overall_verdict": "approve_with_minor_changes | revise | major_revision",
  "findings": [
    {
      "title": "...",
      "severity": "critical|high|medium|low",
      "category": "ambiguity|contradiction|omission|feasibility|testability|security|performance|governance|scope|data_model|api_contract|operational_risk|domain_fit|other",
      "location": "Section ...",
      "evidence": "...",
      "problem": "...",
      "why_it_matters": "...",
      "proposed_fix": "...",
      "confidence": 0.0,
      "speculative": false
    }
  ],
  "top_3_must_fix": ["...", "...", "..."]
}
""".strip()


def _build_manual_review_message(
    draft: str,
    round_number: int,
    compliance_context: str | None = None,
) -> str:
    """Build the simple blind-review prompt that mirrors Joe's manual flow."""
    if round_number <= 2:
        task = (
            "Please review this spec. Be direct. Point out real problems, "
            "especially compliance, edge cases, feasibility, scalability, "
            "domain fit, and production risk. Suggest fixes. Keep it concise. "
            "If there are fewer than three real problems, return fewer than three."
        )
    else:
        task = (
            "Please review this revised spec for remaining blockers or regressions only. "
            "Do not raise low-risk nitpicks, stylistic preferences, or already-resolved "
            "concerns. Keep it concise."
        )

    msg = task
    if compliance_context:
        msg += (
            "\n\n---\n\n"
            "## Compliance Rule Pack\n\n"
            "Use these requirements as authoritative context. Raise compliance "
            "findings only when the spec fails, contradicts, or materially "
            "underspecifies a requirement.\n\n"
            f"{compliance_context}"
        )

    msg += (
        f"\n\n---\n\n## Spec for Blind Review (Round {round_number})\n\n{draft}"
        f"\n\n---\n\n{_reviewer_contract_json_schema()}"
    )
    return msg


def _missing_reviewer_note(missing_reviewers: list[str] | None) -> str:
    """Disclosure block for a degraded-quorum round's synthesis prompts.

    WHY explicit: a synthesizer that simply doesn't see a reviewer could
    read the silence as agreement; the absence must be stated.
    """
    if not missing_reviewers:
        return ""
    return (
        f"## Missing Reviewers\n\n"
        f"{', '.join(missing_reviewers)} failed this round (provider/network "
        f"error) and submitted no review. Do not infer agreement or absence "
        f"of concerns from a missing reviewer.\n\n"
    )


def _build_referee_message(
    draft: str,
    reviews: dict[str, dict],
    round_number: int,
    prior_issues: list[dict] | None = None,
    missing_reviewers: list[str] | None = None,
) -> str:
    """Build the message for Sonnet referee."""
    msg = f"## Round {round_number}\n\n## Canonical Draft\n\n{draft}\n\n"
    msg += _missing_reviewer_note(missing_reviewers)
    msg += "## Reviewer Outputs\n\n"
    for name, output in reviews.items():
        msg += f"### {name}\n```json\n{json.dumps(output, indent=2)}\n```\n\n"
    if prior_issues:
        # Pass full prior issue metadata so Sonnet can match recurring issues
        summary = [
            {"issue_id": i.get("issue_id"), "title": i.get("title"), "severity": i.get("severity"), "category": i.get("category")}
            for i in prior_issues if i.get("issue_id")
        ]
        msg += (
            f"## Prior Round Normalized Issues (reuse issue_id for recurring issues)\n"
            f"```json\n{json.dumps(summary, indent=2)}\n```\n\n"
        )
    return msg


def _build_manual_beth_message(
    draft: str,
    reviews: dict[str, dict],
    round_number: int,
    max_rounds: int,
    prior_beth_decisions: list[dict] | None = None,
    missing_reviewers: list[str] | None = None,
) -> str:
    """Build Beth's raw-review bundle for the manual workflow."""
    msg = (
        f"## Current Spec\n\n{draft}\n\n"
        f"## Round Context\n\n"
        f"- Current round: {round_number}\n"
        f"- Hard cap: {max_rounds} rounds\n"
        f"- Round 3+ policy: only material blockers or regressions should keep the loop open.\n"
        f"- Final round policy: recommend LOCK or HUMAN_REVIEW, not ONE_MORE_ROUND.\n\n"
    )
    msg += _missing_reviewer_note(missing_reviewers)
    msg += "## Blind Review Bundle\n\n"
    for name, output in reviews.items():
        msg += f"### {name}\n```json\n{json.dumps(output, indent=2)}\n```\n\n"

    if prior_beth_decisions:
        msg += (
            "## Prior Beth Decisions\n"
            f"```json\n{json.dumps(prior_beth_decisions, indent=2)}\n```\n\n"
            "Do not re-accept issues already resolved. If they recur, decide whether "
            "that means the fix failed or the reviewer is nitpicking."
        )

    msg += (
        "\n\n## Your Task\n"
        "Normalize and bundle the reviews yourself. Revise the spec only for serious "
        "issues. Recommend LOCK, ONE_MORE_ROUND, or HUMAN_REVIEW."
    )
    return msg


def _build_coordinator_message(
    draft: str,
    normalized: dict,
    round_number: int,
    prior_decisions: list[dict] | None = None,
) -> str:
    """Build the message for Beth coordinator."""
    msg = (
        f"## Current Canonical Draft\n\n{draft}\n\n"
        f"## Normalized Issue Ledger (Round {round_number})\n"
        f"```json\n{json.dumps(normalized, indent=2)}\n```\n\n"
        f"Classify each finding by its issue_id and revise the draft for accepted defects.\n"
        f"Include the full revised draft in the `revised_draft` field of your JSON response.\n"
        f"If no revision is needed, set `revised_draft` to null.\n"
        f"Return a single JSON object only — no text outside the JSON."
    )
    if prior_decisions:
        msg += (
            f"\n\n## Prior Round Decisions\n"
            f"```json\n{json.dumps(prior_decisions, indent=2)}\n```\n"
            f"Do not re-accept findings already resolved. Focus on new/changed issues."
        )
    return msg


def _reviewer_verdicts(review_round: ReviewRound) -> dict[str, str]:
    """Map oracle name -> overall_verdict for a round's reviewer outputs.

    Outputs without a verdict (errored reviewers, models that omitted the
    field) are excluded — absence of a verdict is not a verdict.
    """
    verdicts: dict[str, str] = {}
    for name, output in review_round.reviewer_outputs.items():
        verdict = str(output.get("overall_verdict") or "").strip().lower()
        if verdict:
            verdicts[name] = verdict
    return verdicts


def _apply_verdict_consistency(
    review_round: ReviewRound,
    converged: bool,
    consensus_type: str,
    reason: str,
) -> tuple[bool, str, str]:
    """Cross-check a consensus claim against final-round reviewer verdicts.

    WHY: reviewers emit overall_verdict in every response, but no code read
    it — a coordinator LOCK could silently override four major_revision
    verdicts (AUDIT A3). Policy (Phase 2 handoff, Q1):
      - UNANIMOUS major_revision from every reviewer that reported a
        verdict (and every reviewer reported one) -> hard block: the run
        escalates to human review instead of reporting consensus.
        Unanimity is the one case where "the coordinator knows better
        than all reviewers" has no defensible reading.
      - PARTIAL major_revision dissent -> consensus stands, but the
        override is disclosed in the convergence reason and the outcome
        is downgraded to stable_with_notes. The system discloses who
        decided; it does not re-decide.
    Returns possibly-modified (converged, consensus_type, reason).
    """
    if not converged:
        return converged, consensus_type, reason

    verdicts = _reviewer_verdicts(review_round)
    majors = sorted(name for name, v in verdicts.items() if v == "major_revision")
    all_reported = len(verdicts) == len(review_round.reviewer_outputs) and bool(verdicts)

    if majors and all_reported and len(majors) == len(verdicts):
        return (
            False,
            "blocked",
            f"Coordinator reported consensus but ALL reviewers returned "
            f"verdict major_revision ({', '.join(majors)}) — escalating to "
            f"human review instead of overriding a unanimous verdict",
        )

    if majors:
        disclosure = (
            f" | Reviewer verdict override disclosed: {', '.join(majors)} "
            f"returned major_revision and were overridden by the coordinator"
        )
        return True, "stable_with_notes", reason + disclosure

    return converged, consensus_type, reason


def _check_convergence(session: OracleSession) -> tuple[bool, bool, str, str]:
    """Check if the review loop should stop, and whether stopping means consensus.

    Returns (stop, converged, consensus_type, reason).

    WHY stop != converged: a tradeoff that repeats unresolved across two
    valid rounds means further rounds will not settle it — the loop must
    stop — but that outcome is a standing DISAGREEMENT. Reporting it as
    convergence was AUDIT finding A2 (false consensus). The repeated
    tradeoff stops the loop with converged=False / consensus_type="blocked".

    Only compares valid rounds. Invalid rounds are skipped entirely.

    Criteria:
    1. No critical findings remain
    2. High findings <= 1
    3. Issue set stability: >80% of issue_ids overlap between rounds
    4. Any unresolved tradeoff repeating in 2+ consecutive valid rounds
       stops the loop as blocked (NOT as convergence)
    """
    previous, current = _last_two_valid_rounds(session)
    if previous is None or current is None:
        return False, False, "", "Need at least 2 valid rounds"

    issues = current.normalized_issues.get("normalized_issues", [])

    # 1. No critical findings
    critical = [i for i in issues if i.get("severity") == "critical"]
    if critical:
        return False, False, "", f"{len(critical)} critical findings remain"

    # 2. High findings <= 1
    high = [i for i in issues if i.get("severity") == "high"]
    if len(high) > 1:
        return False, False, "", f"{len(high)} high findings remain"

    # 3. Issue set stability (by lineage, not count). lineage_id falls back
    # to issue_id for pre-FIX-2 rounds; using lineage keeps a renumbered-
    # but-linked issue (R1-ISSUE-003 → R2-ISSUE-001 via recurrence_of) from
    # reading as churn.
    current_ids = {
        i.get("lineage_id") or i.get("issue_id") for i in issues
        if i.get("lineage_id") or i.get("issue_id")
    }
    prev_issues = previous.normalized_issues.get("normalized_issues", [])
    prev_ids = {
        i.get("lineage_id") or i.get("issue_id") for i in prev_issues
        if i.get("lineage_id") or i.get("issue_id")
    }
    if current_ids and prev_ids:
        overlap = len(current_ids & prev_ids) / max(len(current_ids | prev_ids), 1)
        if overlap < 0.8:
            return False, False, "", f"Issue set unstable: {overlap:.0%} overlap ({len(current_ids)} vs {len(prev_ids)})"
    elif not current_ids and not prev_ids:
        overlap = 1.0  # Both empty = stable
    elif not current_ids and prev_ids:
        # All prior issues resolved — converge (critical/high already passed above)
        overlap = 1.0
    else:
        # No prior issues but new ones appeared — not stable
        return False, False, "", f"Issue set unstable: new issues appeared ({len(current_ids)} vs {len(prev_ids)})"

    # 4. Same unresolved tradeoff repeats across valid rounds: STOP as
    # blocked. Further automated rounds cannot resolve a question the
    # coordinator has twice declined to decide — but that is dissent to
    # surface, not consensus to report.
    current_open = set(current.coordinator_decisions.get("open_questions", []))
    prev_open = set(previous.coordinator_decisions.get("open_questions", []))
    repeated = current_open & prev_open
    if repeated:
        return (
            True,
            False,
            "blocked",
            f"Blocked: unresolved tradeoff(s) repeated across rounds, "
            f"needs human decision: {sorted(repeated)}",
        )

    # WHY stable_with_notes: converging with an outstanding high finding
    # or open questions is agreement-with-residue, and the report must
    # not present it as full agreement (AUDIT finding A4).
    if high or current_open:
        consensus_type = "stable_with_notes"
        residue = []
        if high:
            residue.append(
                "unresolved high: " + "; ".join(str(i.get("title", i.get("issue_id", "?"))) for i in high)
            )
        if current_open:
            residue.append(f"open questions: {sorted(current_open)}")
        return True, True, consensus_type, f"Converged with notes — {' | '.join(residue)}"

    return True, True, "full_agreement", f"Converged: 0 high, issue overlap {overlap:.0%}"


def _reconcile_decision_ids(review_round: ReviewRound) -> list[str]:
    """FIX-1 hard gate: every coordinator decision must join to a normalized issue.

    WHY: the coordinator and the normalizer can end up reading different
    issue sets (run 20260729-153932: 10 accepted/decided IDs had no
    normalized record, so those defects had no severity, source, or
    corroboration and silently dropped out of every metric). Rather than
    emitting metrics past the subset violation, the harness reconstructs
    a minimal issue record from the decision itself and marks it
    "reconstructed" — the report and audit trail then show exactly which
    records lack normalizer provenance instead of hiding them.

    Returns the reconstructed issue_ids (empty when the invariant held).
    """
    issues = review_round.normalized_issues.setdefault("normalized_issues", [])
    known = {
        i.get("issue_id")
        for i in issues
        if isinstance(i, dict) and i.get("issue_id")
    }
    reconstructed: list[str] = []
    for d in review_round.coordinator_decisions.get("revision_decisions", []):
        if not isinstance(d, dict):
            continue
        iid = d.get("issue_id")
        if not iid or iid in known:
            continue
        issues.append({
            "issue_id": iid,
            "title": str(
                d.get("title") or d.get("reason") or "Reconstructed from coordinator decision"
            )[:160],
            # WHY "unknown": inventing a severity here would fabricate the
            # exact counts this gate exists to protect. "unknown" surfaces
            # in its own metrics bucket (same policy as oracle2_adapter,
            # AUDIT F1).
            "severity": d.get("severity") or "unknown",
            "reconstructed": True,
            "reconstruction_source": "coordinator_decision",
        })
        known.add(iid)
        reconstructed.append(iid)
    if reconstructed:
        review_round.normalized_issues["reconstructed_issue_ids"] = reconstructed
        LOGGER.warning(
            f"Round {review_round.round_number}: {len(reconstructed)} coordinator "
            f"decision(s) referenced issue IDs missing from the normalized set — "
            f"reconstructed minimal records for: {', '.join(reconstructed)}"
        )
    return reconstructed


def _assign_issue_lineage(prior_rounds: list[ReviewRound], review_round: ReviewRound) -> None:
    """FIX-2: attach a stable lineage_id to every normalized issue.

    lineage_id is the issue_id an issue was FIRST detected under, carried
    forward by (a) direct issue_id reuse or (b) a resolved
    recurrence_of / mutation_of link emitted by the normalizer. WHY
    harness-side: reviewers are blind across rounds and the referee's
    voluntary ID reuse measured 0% in practice — "R1 fix for ISSUE-003
    failed → R2-ISSUE-001" lived only in prose. A claimed parent that
    resolves to nothing is recorded as lineage_unresolved_parent, never
    silently treated as novel.
    """
    lineage: dict[str, str] = {}
    for r in prior_rounds:
        if not r.valid:
            continue
        for issue in r.normalized_issues.get("normalized_issues", []):
            iid = issue.get("issue_id") if isinstance(issue, dict) else None
            if iid:
                lineage[iid] = issue.get("lineage_id") or iid
    for issue in review_round.normalized_issues.get("normalized_issues", []):
        if not isinstance(issue, dict) or not issue.get("issue_id"):
            continue
        iid = issue["issue_id"]
        parent = issue.get("recurrence_of") or issue.get("mutation_of")
        if iid in lineage:
            issue["lineage_id"] = lineage[iid]
        elif parent and parent in lineage:
            issue["lineage_id"] = lineage[parent]
        else:
            issue["lineage_id"] = iid
            if parent:
                issue["lineage_unresolved_parent"] = parent


def _run_manual_round(
    session: OracleSession,
    round_num: int,
    max_rounds: int,
    output_dir: Path,
    compliance_context: str | None,
) -> tuple[ReviewRound, bool]:
    """Execute one manual-style round: blind reviewers -> Beth directly.

    This mirrors Joe's manual process. Reviewers stay blind; Beth receives the
    raw bundle and acts as normalizer, bundler, spec revisor, and stop-signal.
    """
    review_round = ReviewRound(round_number=round_num)
    review_msg = _build_manual_review_message(
        session.canonical_draft,
        round_num,
        compliance_context=compliance_context,
    )

    if not _fan_out_reviewers(review_round, review_msg, output_dir, round_num):
        LOGGER.error(f"Round {round_num} INVALID: reviewer quorum not met.")
        session.rounds.append(review_round)
        return review_round, False

    prior_decisions = [
        r.coordinator_decisions
        for r in session.rounds
        if r.valid and r.coordinator_decisions
    ]
    # Fail-closed: only validated reviews enter the bundle; failed
    # reviewers appear as an explicit absence note, never as content.
    beth_msg = _build_manual_beth_message(
        session.canonical_draft,
        _valid_reviewer_outputs(review_round),
        round_number=round_num,
        max_rounds=max_rounds,
        prior_beth_decisions=prior_decisions or None,
        missing_reviewers=review_round.missing_reviewers or None,
    )
    beth_config = _with_system_prompt(
        ORACLE_ROSTER["beth"],
        BETH_MANUAL_SYNTHESIS_PROMPT,
    )

    try:
        beth_response = call_oracle(beth_config, beth_msg)
    except Exception as e:
        review_round.telemetry["Beth"] = {
            "oracle": "Beth",
            "failed": True,
            "attempt_log": getattr(e, "attempt_log", [_describe_exception(e)]),
        }
        _write_round_telemetry(output_dir, round_num, review_round)
        LOGGER.error(f"[Beth] FAILED after retries: {e}. Round invalid.")
        session.rounds.append(review_round)
        return review_round, False

    review_round.telemetry["Beth"] = beth_response.pop("_telemetry", None) or {}
    _write_round_telemetry(output_dir, round_num, review_round)

    review_round.coordinator_decisions = beth_response
    serious_issues = beth_response.get("serious_issues", [])
    review_round.normalized_issues = {
        "oracle_name": "Beth",
        "role": "manual_normalizer",
        "normalized_issues": serious_issues if isinstance(serious_issues, list) else [],
    }
    # FIX-3: carry Beth's drop signal so duplicate/unsupported rates are
    # measured in the manual workflow instead of permanently n/a. Only set
    # when actually emitted — absence must stay "not measured", never 0.0.
    dropped_findings = beth_response.get("dropped_findings")
    if isinstance(dropped_findings, list):
        review_round.normalized_issues["dropped_findings"] = dropped_findings
    # FIX-1/FIX-2: enforce decision-ID ⊆ issue-ID before anything downstream
    # consumes the round, then resolve cross-round lineage.
    _reconcile_decision_ids(review_round)
    _assign_issue_lineage(session.rounds, review_round)

    _apply_revised_draft(session, review_round, beth_response)
    review_round.valid = True

    _persist_beth_outputs(output_dir, round_num, beth_response, review_round)
    (output_dir / f"round{round_num}_beth_normalized.json").write_text(
        encoding="utf-8", data=json.dumps(review_round.normalized_issues, indent=2)
    )

    session.rounds.append(review_round)

    recommendation = str(beth_response.get("recommendation") or "").strip().upper()
    reason = str(beth_response.get("recommendation_reason") or "").strip()

    if recommendation == "LOCK":
        # LOCK with open questions is agreement-with-residue, not full
        # agreement — the distinction must survive to the report (AUDIT A2/A4).
        open_questions = beth_response.get("open_questions") or []
        consensus_type = "stable_with_notes" if open_questions else "full_agreement"
        converged, consensus_type, lock_reason = _apply_verdict_consistency(
            review_round,
            True,
            consensus_type,
            reason or "Beth recommended LOCK",
        )
        # A round that ran without a reviewer cannot claim full agreement:
        # the missing oracle's dissent is unknowable, not absent.
        if converged and review_round.missing_reviewers and consensus_type == "full_agreement":
            consensus_type = "stable_with_notes"
            lock_reason += (
                f" | Degraded quorum: round ran without "
                f"{', '.join(review_round.missing_reviewers)}"
            )
        session.converged = converged
        session.consensus_type = consensus_type
        session.convergence_reason = lock_reason
        if converged:
            LOGGER.info(f"\nLocked after round {round_num}: {session.convergence_reason}")
        else:
            LOGGER.warning(
                f"\nLOCK blocked by reviewer verdicts after round {round_num}: "
                f"{session.convergence_reason}"
            )
        return review_round, True

    if recommendation == "HUMAN_REVIEW":
        session.converged = False
        session.consensus_type = "blocked"
        session.convergence_reason = reason or "Beth recommended HUMAN_REVIEW"
        LOGGER.info(f"\nStopping for human review after round {round_num}: {session.convergence_reason}")
        return review_round, True

    if round_num >= max_rounds:
        session.converged = False
        session.consensus_type = "blocked"
        session.convergence_reason = (
            reason or f"Reached max rounds ({max_rounds}) without LOCK"
        )
        LOGGER.info(f"\nStopping at max rounds: {session.convergence_reason}")
        return review_round, True

    LOGGER.info(f"\nBeth recommended one more round: {reason or 'no reason provided'}")
    return review_round, False


def _run_round(
    session: OracleSession,
    round_num: int,
    output_dir: Path,
    compliance_context: str | None,
) -> tuple[ReviewRound, bool]:
    """Execute a single review round: parallel reviewers → Sonnet → Beth.

    Returns (review_round, converged).  The round is appended to session.rounds
    and session.canonical_draft is updated if Beth revises.

    Why extracted: run_review was 170 lines with the round loop inlined.
    Each round is an independent unit of work — extracting it makes the
    convergence loop in run_review readable and each round independently testable.
    """
    review_round = ReviewRound(round_number=round_num)

    last_valid = _last_valid_round(session)
    changed_sections = last_valid.coordinator_decisions.get("revised_sections", []) if last_valid else None
    prior_decisions = last_valid.coordinator_decisions if last_valid else None
    prior_issues = last_valid.normalized_issues.get("normalized_issues", []) if last_valid else []

    # --- Parallel blind review (Fran, Codex, Grok) ---
    review_msg = _build_review_message(
        session.canonical_draft, round_num, changed_sections,
        compliance_context=compliance_context,
    )

    if not _fan_out_reviewers(review_round, review_msg, output_dir, round_num):
        LOGGER.error(f"Round {round_num} INVALID: reviewer quorum not met.")
        session.rounds.append(review_round)
        return review_round, False

    # --- Sonnet normalizes (fail-closed: validated reviews only) ---
    referee_msg = _build_referee_message(
        session.canonical_draft, _valid_reviewer_outputs(review_round),
        round_number=round_num, prior_issues=prior_issues,
        missing_reviewers=review_round.missing_reviewers or None,
    )
    try:
        normalized = call_oracle(ORACLE_ROSTER["sonnet"], referee_msg)
    except OracleAuthError:
        # Dead key — abort the whole review rather than marking rounds invalid.
        raise
    except Exception as e:
        review_round.telemetry["Sonnet"] = {
            "oracle": "Sonnet",
            "failed": True,
            "attempt_log": getattr(e, "attempt_log", [_describe_exception(e)]),
        }
        _write_round_telemetry(output_dir, round_num, review_round)
        LOGGER.error(f"[Sonnet] FAILED after retries: {e}. Round invalid.")
        session.rounds.append(review_round)
        return review_round, False

    review_round.telemetry["Sonnet"] = normalized.pop("_telemetry", None) or {}
    review_round.normalized_issues = normalized
    (output_dir / f"round{round_num}_sonnet_normalized.json").write_text(
        encoding="utf-8", data=json.dumps(normalized, indent=2)
    )

    # --- Beth classifies and revises ---
    coord_msg = _build_coordinator_message(
        session.canonical_draft, normalized, round_num,
        prior_decisions=[prior_decisions] if prior_decisions else None,
    )
    try:
        beth_response = call_oracle(ORACLE_ROSTER["beth"], coord_msg)
    except OracleAuthError:
        # Dead key — abort the whole review rather than marking rounds invalid.
        raise
    except Exception as e:
        review_round.telemetry["Beth"] = {
            "oracle": "Beth",
            "failed": True,
            "attempt_log": getattr(e, "attempt_log", [_describe_exception(e)]),
        }
        _write_round_telemetry(output_dir, round_num, review_round)
        LOGGER.error(f"[Beth] FAILED after retries: {e}. Round invalid.")
        session.rounds.append(review_round)
        return review_round, False

    review_round.telemetry["Beth"] = beth_response.pop("_telemetry", None) or {}
    _write_round_telemetry(output_dir, round_num, review_round)
    review_round.coordinator_decisions = beth_response

    # FIX-1/FIX-2: enforce decision-ID ⊆ issue-ID, resolve cross-round
    # lineage, and re-persist the normalized file so the on-disk record
    # (what oracle2_adapter reads) matches what the metrics were computed
    # from. The pre-Beth write above is kept as a crash artifact; this
    # write supersedes it.
    _reconcile_decision_ids(review_round)
    _assign_issue_lineage(session.rounds, review_round)
    (output_dir / f"round{round_num}_sonnet_normalized.json").write_text(
        encoding="utf-8",
        data=json.dumps(review_round.normalized_issues, indent=2),
    )

    _apply_revised_draft(session, review_round, beth_response)
    review_round.valid = True

    _persist_beth_outputs(output_dir, round_num, beth_response, review_round)

    session.rounds.append(review_round)

    stop, converged, consensus_type, reason = _check_convergence(session)
    if stop:
        converged, consensus_type, reason = _apply_verdict_consistency(
            review_round, converged, consensus_type, reason
        )
        # A round that ran without a reviewer cannot claim full agreement.
        if converged and review_round.missing_reviewers and consensus_type == "full_agreement":
            consensus_type = "stable_with_notes"
            reason += (
                f" | Degraded quorum: round ran without "
                f"{', '.join(review_round.missing_reviewers)}"
            )
        session.converged = converged
        session.consensus_type = consensus_type
        session.convergence_reason = reason
        if converged:
            LOGGER.info(f"\nConverged after round {round_num}: {reason}")
        else:
            LOGGER.warning(f"\nStopped WITHOUT consensus after round {round_num}: {reason}")
    else:
        LOGGER.info(f"\nNot converged: {reason}")

    return review_round, stop


# Preflight pass conditions: these "errors" prove the provider accepted
# auth + model and responded — for a connectivity/model-ID check, a prose
# or empty reply is success. Anything else (exceptions, HTTP error dicts,
# missing keys) is a real preflight failure.
_PREFLIGHT_ACCEPTABLE_ERRORS = (
    "No JSON found",
    "Empty response",
    "Model refusal",
    "Gemini returned no candidates",
    "Gemini returned empty content",
    "Malformed JSON",
)


def preflight_models() -> list[dict]:
    """Ping each unique (provider, model) in the roster with a tiny request.

    WHY: the HEARTH zero-finding abort burned two full rounds (and the
    healthy vendors' spend) to discover that calls were failing. A ~one-
    token ping per vendor before round 1 converts that into an immediate,
    named failure: which oracle, which provider, which model, what error.

    Returns a list of failure dicts; empty list = all vendors reachable.
    Opt-in via ORACLE_PREFLIGHT=1 (default off: it makes live network
    calls, which keyless/mocked environments must not attempt).
    """
    failures: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for cfg in ORACLE_ROSTER.values():
        ident = (cfg.provider, cfg.model)
        if ident in seen:
            continue
        seen.add(ident)
        ping_config = OracleConfig(
            name=f"preflight-{cfg.name}",
            role="preflight",  # no REQUIRED_SCHEMA entry -> no schema gate
            provider=cfg.provider,
            model=cfg.model,
            system_prompt="Reply with the single word: pong",
            max_tokens=int(os.environ.get("ORACLE_PREFLIGHT_MAX_TOKENS", "64")),
            timeout=int(os.environ.get("ORACLE_PREFLIGHT_TIMEOUT", "30")),
        )
        try:
            result = PROVIDER_DISPATCH[cfg.provider](ping_config, "Reply with the single word: pong")
            error = str(result.get("error", ""))
            if error and not error.startswith(_PREFLIGHT_ACCEPTABLE_ERRORS):
                failures.append({
                    "oracle": cfg.name,
                    "provider": cfg.provider,
                    "model": cfg.model,
                    "error": error,
                })
        except Exception as e:
            failure = _describe_exception(e)
            failure.update({
                "oracle": cfg.name,
                "provider": cfg.provider,
                "model": cfg.model,
            })
            failures.append(failure)
    return failures


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_run_manifest(
    output_dir: Path,
    session_id: str,
    workflow: str,
    max_rounds: int,
    document_path: str,
    draft: str,
    compliance_context: str | None,
) -> None:
    """Persist everything needed to defend or replay this run (AUDIT D2).

    Records the full oracle roster as configured (provider, model,
    temperature, token budgets), hashes of every system prompt and of the
    inputs, and all ORACLE_* environment overrides. Prompt/input hashes
    rather than full text keep the manifest small while still proving
    what configuration produced a given result.

    WHY only ORACLE_* env vars: API keys live in *_API_KEY variables and
    must never be persisted; the ORACLE_ prefix carries no secrets.
    """
    manifest = {
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "workflow": workflow,
        "max_rounds": max_rounds,
        "document_path": document_path,
        "document_sha256": _sha256(draft),
        "compliance_context_sha256": (
            _sha256(compliance_context) if compliance_context else None
        ),
        "oracle_roster": {
            key: {
                "name": cfg.name,
                "role": cfg.role,
                "provider": cfg.provider,
                "model": cfg.model,
                "temperature": cfg.temperature,
                "max_tokens": cfg.max_tokens,
                "timeout": cfg.timeout,
                "system_prompt_sha256": _sha256(cfg.system_prompt),
            }
            for key, cfg in ORACLE_ROSTER.items()
        },
        "env_overrides": {
            k: os.environ[k] for k in sorted(os.environ) if k.startswith("ORACLE_")
        },
    }
    (output_dir / "run_manifest.json").write_text(
        encoding="utf-8", data=json.dumps(manifest, indent=2)
    )


def _usage_totals(session: OracleSession) -> dict[str, dict]:
    """Aggregate per-oracle call/token/latency totals across rounds (AUDIT D1)."""
    totals: dict[str, dict] = {}
    for r in session.rounds:
        for name, t in r.telemetry.items():
            if not isinstance(t, dict):
                continue
            agg = totals.setdefault(name, {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_seconds": 0.0,
                "models": [],
            })
            agg["calls"] += 1
            for key in ("input_tokens", "output_tokens"):
                value = t.get(key)
                if isinstance(value, (int, float)):
                    agg[key] += int(value)
            latency = t.get("latency_seconds")
            if isinstance(latency, (int, float)):
                agg["latency_seconds"] = round(agg["latency_seconds"] + latency, 2)
            model = t.get("response_model") or t.get("configured_model")
            if model and model not in agg["models"]:
                agg["models"].append(model)
    return totals


def run_review(
    draft: str,
    document_path: str = "",
    max_rounds: int = 4,
    output_dir: Path | None = None,
    compliance_context: str | None = None,
    workflow: str = DEFAULT_WORKFLOW,
    cancel_check: Callable[[], bool] | None = None,
) -> OracleSession:
    """Run the full multi-oracle review loop.

    Default workflow is "manual": blind reviewers -> Beth directly.  The
    legacy "ledger" workflow keeps the older Sonnet-normalized issue ledger.
    Saves final_draft.md and session_summary.json on completion.

    cancel_check: optional callable polled at each round boundary; returning
    True stops the review before the next round's oracle calls are made.
    The session finalizes normally (artifacts written) with consensus_type
    "cancelled" — cancellation halts spend, it never destroys evidence.
    """
    workflow = workflow.strip().lower()
    if workflow not in VALID_WORKFLOWS:
        raise ValueError(f"Unknown workflow '{workflow}'. Expected one of {sorted(VALID_WORKFLOWS)}")

    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    session = OracleSession(
        session_id=session_id,
        document_path=document_path,
        original_draft=draft,
        canonical_draft=draft,
    )

    if output_dir is None:
        output_dir = Path("oracle_reviews") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Written before the first oracle call so even a run that dies in
    # round 1 records what configuration produced it.
    _write_run_manifest(
        output_dir, session_id, workflow, max_rounds,
        document_path, draft, compliance_context,
    )

    # Opt-in vendor preflight (ORACLE_PREFLIGHT=1): fail in seconds with a
    # named cause instead of burning review rounds against a dead vendor.
    if os.environ.get("ORACLE_PREFLIGHT", "").strip().lower() in {"1", "true", "yes"}:
        preflight_failures = preflight_models()
        if preflight_failures:
            detail = "; ".join(
                f"{f['oracle']} ({f['provider']}/{f['model']}): "
                f"{f.get('failure_class', '')} {f.get('error', '')}".strip()
                for f in preflight_failures
            )
            raise OracleCallError(f"Preflight failed — review not started: {detail}")

    consecutive_invalid = 0
    for round_num in range(1, max_rounds + 1):
        # Round boundary is the cancellation point: all of a round's oracle
        # calls either happen or don't — no torn rounds, no lost evidence.
        if cancel_check is not None and cancel_check():
            session.converged = False
            session.consensus_type = "cancelled"
            session.convergence_reason = (
                f"Cancelled by user before round {round_num} — "
                f"{round_num - 1} round(s) completed; remaining rounds not run"
            )
            LOGGER.info(session.convergence_reason)
            break
        LOGGER.info(f"\n{'='*60}\nRound {round_num}\n{'='*60}")
        if workflow == "manual":
            _, should_stop = _run_manual_round(
                session,
                round_num,
                max_rounds,
                output_dir,
                compliance_context,
            )
        else:
            _, should_stop = _run_round(session, round_num, output_dir, compliance_context)
        if should_stop:
            break

        # WHY abort on consecutive invalid rounds: with a vendor hard-down,
        # every retry of the round re-pays the three healthy vendors and
        # still produces nothing. Two consecutive invalid rounds means the
        # failure is systemic, not transient — burning the remaining round
        # budget cannot help (AUDIT C2).
        if session.rounds and not session.rounds[-1].valid:
            consecutive_invalid += 1
        else:
            consecutive_invalid = 0
        if consecutive_invalid >= MAX_CONSECUTIVE_INVALID_ROUNDS:
            session.converged = False
            session.consensus_type = "blocked"
            session.convergence_reason = (
                f"Aborted after {consecutive_invalid} consecutive invalid rounds "
                f"(oracle failures) — the document was NOT fully reviewed"
            )
            LOGGER.error(f"\n{session.convergence_reason}")
            break

    # A run must never end without explaining its outcome — an empty
    # reason on a non-converged session previously left readers unable to
    # tell a failed run from a quietly stopped one (AUDIT C2/F2).
    if not session.converged and not session.convergence_reason:
        valid_rounds = sum(1 for r in session.rounds if r.valid)
        session.consensus_type = session.consensus_type or "blocked"
        session.convergence_reason = (
            f"Stopped at max rounds ({max_rounds}) without convergence "
            f"({valid_rounds}/{len(session.rounds)} rounds valid)"
        )

    # Save final state
    (output_dir / "final_draft.md").write_text(encoding="utf-8", data=session.canonical_draft)
    summary = {
        "session_id": session.session_id,
        "document_path": session.document_path,
        "workflow": workflow,
        "total_rounds": len(session.rounds),
        "converged": session.converged,
        "consensus_type": session.consensus_type,
        "convergence_reason": session.convergence_reason,
        "total_findings_by_round": [
            {
                "round": r.round_number,
                "reviewer_findings": {
                    name: len(out.get("findings", []))
                    for name, out in r.reviewer_outputs.items()
                },
                "normalized_issues": len(
                    r.normalized_issues.get("normalized_issues", [])
                ),
                "accepted_defects": sum(
                    1 for d in r.coordinator_decisions.get("revision_decisions", [])
                    if d.get("decision") == "accepted_defect"
                ),
            }
            for r in session.rounds
        ],
        "usage_totals": _usage_totals(session),
    }
    (output_dir / "session_summary.json").write_text(encoding="utf-8", data=json.dumps(summary, indent=2))
    LOGGER.info(f"\nResults saved to {output_dir}/")

    return session


# ---------------------------------------------------------------------------
# Scoring / QC metrics
# ---------------------------------------------------------------------------

def _issue_source_names(issue: dict) -> list[str]:
    """Source-oracle attribution for a normalized issue, both workflow shapes."""
    sources: list[str] = []
    for merged in issue.get("merged_from", []) or []:
        if isinstance(merged, dict) and merged.get("oracle") and merged["oracle"] not in sources:
            sources.append(merged["oracle"])
    for reviewer in issue.get("source_reviewers", []) or []:
        if isinstance(reviewer, str) and reviewer and reviewer not in sources:
            sources.append(reviewer)
    return sources


def _accepted_severity_counts(
    accepted_ids: set[str], issue_severity: dict[str, str]
) -> dict[str, int]:
    """FIX-3: count every severity class the pipeline actually uses.

    Medium/low were dropped from metrics while the report body demonstrably
    contained accepted [MEDIUM] findings — 9 of 24 accepted defects had no
    severity bucket. "unknown" holds accepted defects whose issue record is
    reconstructed or carries no severity: a data problem to count, never a
    severity to invent (same policy as oracle2_adapter, AUDIT F1).
    """
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
    for iid in accepted_ids:
        sev = issue_severity.get(iid, "unknown")
        counts[sev if sev in counts else "unknown"] += 1
    return counts


def _continuity_metrics(session: OracleSession) -> tuple[float | None, int]:
    """FIX-2: (issue_id_continuity, novel_issue_count) from lineage data.

    Continuity = fraction of NON-NOVEL later-round issues whose parent
    resolves: an issue is non-novel when it reuses a prior issue_id or
    claims recurrence_of/mutation_of; its parent resolves when that link
    lands on an ID actually seen in a prior valid round. Genuinely novel
    issues no longer drag the metric to a permanent 0% — the old
    definition (plain ID-set overlap) alerted on nothing because it read
    0% for every renumbering referee regardless of real linkage.

    novel_issue_count = distinct lineage roots — issues, not re-sightings.
    """
    samples: list[float] = []
    seen_ids: set[str] = set()
    lineage_roots: set[str] = set()
    first = True
    for r in session.rounds:
        if not r.valid:
            continue
        issues = [
            i for i in r.normalized_issues.get("normalized_issues", [])
            if isinstance(i, dict) and i.get("issue_id")
        ]
        if not first and issues:
            non_novel = resolved = 0
            for issue in issues:
                parent = issue.get("recurrence_of") or issue.get("mutation_of")
                if issue["issue_id"] in seen_ids:
                    non_novel += 1
                    resolved += 1
                elif parent:
                    non_novel += 1
                    resolved += 1 if parent in seen_ids else 0
            if non_novel:
                samples.append(resolved / non_novel)
        for issue in issues:
            seen_ids.add(issue["issue_id"])
            lineage_roots.add(issue.get("lineage_id") or issue["issue_id"])
        first = False
    continuity = sum(samples) / len(samples) if samples else None
    return continuity, len(lineage_roots)


def _coordinator_telemetry(
    all_decisions: list[dict], issues_by_id: dict[str, dict]
) -> dict:
    """FIX-4: per-run coordinator acceptance telemetry.

    A coordinator that accepts everything is a failure pattern only
    visible across runs — these per-run rates are persisted in
    metrics.json so rolling aggregation is possible, and the per-run
    alerts catch the two cases that never need history: blanket
    acceptance and single-reviewer criticals accepted uncorroborated.
    """
    provider_by_oracle = {cfg.name: cfg.provider for cfg in ORACLE_ROSTER.values()}
    decided = [d for d in all_decisions if isinstance(d, dict) and d.get("issue_id")]
    total = len(decided)

    def _count(decision: str) -> int:
        return sum(1 for d in decided if d.get("decision") == decision)

    accepted_n = _count("accepted_defect")
    per_reviewer: dict[str, dict] = {}
    cross_vendor_accepted = single_source_accepted = 0
    severe_pool = severe_downgraded = 0
    single_source_criticals: list[str] = []
    for d in decided:
        issue = issues_by_id.get(d["issue_id"])
        if issue is None:
            continue
        is_accept = d.get("decision") == "accepted_defect"
        sources = _issue_source_names(issue)
        if issue.get("severity") in ("critical", "high"):
            severe_pool += 1
            if d.get("decision") in ("rejected_claim", "preference_only"):
                severe_downgraded += 1
        for s in sources:
            stats = per_reviewer.setdefault(s, {"decided": 0, "accepted": 0})
            stats["decided"] += 1
            stats["accepted"] += 1 if is_accept else 0
        if is_accept and sources:
            if len({provider_by_oracle.get(s, "unknown") for s in sources}) >= 2:
                cross_vendor_accepted += 1
            if len(sources) == 1:
                single_source_accepted += 1
                if issue.get("severity") == "critical":
                    single_source_criticals.append(d["issue_id"])
    for stats in per_reviewer.values():
        stats["acceptance_rate"] = stats["accepted"] / stats["decided"]

    alerts: list[str] = []
    # WHY >= 5: one or two decisions all accepted is normal judgment; a
    # full-slate 100% is the compliant-coordinator signature worth flagging.
    if total >= 5 and accepted_n == total:
        alerts.append("coordinator accepted 100% of decided findings this run")
    if single_source_criticals:
        alerts.append(
            "critical defect(s) accepted on a single reviewer's finding with "
            f"no corroboration: {', '.join(sorted(single_source_criticals))}"
        )

    return {
        "decided_count": total,
        "acceptance_rate": accepted_n / total if total else None,
        "rejection_rate": _count("rejected_claim") / total if total else None,
        "preference_only_rate": _count("preference_only") / total if total else None,
        "severe_downgrade_rate": severe_downgraded / severe_pool if severe_pool else None,
        "per_reviewer_acceptance": per_reviewer,
        "accepted_cross_vendor_count": cross_vendor_accepted,
        "accepted_single_source_count": single_source_accepted,
        "alerts": alerts,
    }


def compute_metrics(session: OracleSession) -> dict:
    """Compute the QC scoring rubric for a completed review.

    Joins Beth's decisions to Sonnet's normalized issues by issue_id,
    not by fuzzy title matching.
    """
    # Build issue_id → issue/severity lookups from the normalized ledgers
    issue_severity: dict[str, str] = {}
    issues_by_id: dict[str, dict] = {}
    reconstructed_count = 0
    for r in session.rounds:
        for issue in r.normalized_issues.get("normalized_issues", []):
            iid = issue.get("issue_id", "")
            if iid:
                issue_severity[iid] = issue.get("severity", "low")
                issues_by_id[iid] = issue
            if issue.get("reconstructed"):
                reconstructed_count += 1

    # Classify Beth's decisions by joining on issue_id
    all_decisions = []
    for r in session.rounds:
        all_decisions.extend(r.coordinator_decisions.get("revision_decisions", []))

    accepted = [d for d in all_decisions if d.get("decision") == "accepted_defect"]
    rejected = [d for d in all_decisions if d.get("decision") == "rejected_claim"]
    preference = [d for d in all_decisions if d.get("decision") == "preference_only"]

    # Count accepted by severity via issue_id join (FIX-3: all classes)
    accepted_ids = {d.get("issue_id") for d in accepted if d.get("issue_id")}
    sev_counts = _accepted_severity_counts(accepted_ids, issue_severity)

    # Dropped findings from the normalizer (Sonnet, or Beth in manual mode)
    dropped = []
    for r in session.rounds:
        dropped.extend(r.normalized_issues.get("dropped_findings", []))

    total_findings = sum(
        len(out.get("findings", []))
        for r in session.rounds
        for out in r.reviewer_outputs.values()
    )
    duplicate_count = sum(1 for d in dropped if d.get("reason") == "duplicate")
    unsupported_count = sum(1 for d in dropped if d.get("reason") == "unsupported")

    # WHY None vs 0.0: only the ledger workflow's referee emits
    # dropped_findings. The manual workflow has no drop signal at all, so
    # its rates were constitutionally 0.0 yet reported as if measured
    # (AUDIT D3). None means "not measured"; 0.0 means "measured, zero".
    has_drop_signal = any(
        "dropped_findings" in r.normalized_issues
        for r in session.rounds
        if r.valid
    )

    # Valid rounds = all 5 oracles succeeded (reviewer + Sonnet + Beth)
    valid_rounds = sum(1 for r in session.rounds if r.valid)

    # WHY dangling-ID tracking (AUDIT A7): Beth references findings by
    # issue_id; an ID with no matching normalized issue silently drops
    # out of every severity count. _reconcile_decision_ids repairs this
    # in-pipeline, so a non-empty list here means an unreconciled
    # (legacy/corrupt) session.
    dangling_decision_ids = sorted({
        d.get("issue_id") for d in all_decisions
        if d.get("issue_id") and d.get("issue_id") not in issue_severity
    })

    issue_id_continuity, novel_issue_count = _continuity_metrics(session)

    # FIX-1 hard gate: never emit severity-class counts past a subset
    # violation — with decisions untraceable to issues, every bucket is
    # understated by an unknowable amount. None renders as n/a; the
    # decision totals themselves (counted from decisions alone) stay.
    metrics_integrity = "id_subset_violation" if dangling_decision_ids else "ok"
    severity_metrics: dict[str, int | None] = {
        f"accepted_{k}_count": (None if dangling_decision_ids else v)
        for k, v in sev_counts.items()
    }

    return {
        **severity_metrics,
        "total_accepted_defects": len(accepted),
        "total_rejected_claims": len(rejected),
        "total_preference_only": len(preference),
        "novel_issue_count": novel_issue_count,
        "reconstructed_issue_count": reconstructed_count,
        "duplicate_rate": (
            duplicate_count / max(total_findings, 1) if has_drop_signal else None
        ),
        "unsupported_claim_rate": (
            unsupported_count / max(total_findings, 1) if has_drop_signal else None
        ),
        "rounds_to_stability": len(session.rounds),
        "valid_rounds": valid_rounds,
        "converged": session.converged,
        "consensus_type": session.consensus_type,
        "dangling_decision_ids": dangling_decision_ids,
        "metrics_integrity": metrics_integrity,
        "issue_id_continuity": issue_id_continuity,
        "coordinator_telemetry": _coordinator_telemetry(all_decisions, issues_by_id),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Oracle2: Multi-oracle review system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Environment variables:
  ANTHROPIC_API_KEY   — Required for Beth (and Sonnet in ledger workflow)
  OPENAI_API_KEY      — Required for Fran and Codex (GPT-5.4)
  XAI_API_KEY         — Required for Grok
  GEMINI_API_KEY      — Optional dormant adapter; Gemini is not in the review flow

  ORACLE_WORKFLOW     — manual | ledger (default: manual)
  ORACLE_BETH_MODEL   — Override Beth model  (default: claude-opus-4-8)
  ORACLE_FRAN_MODEL   — Override Fran model  (default: gpt-5.6-terra)
  ORACLE_CODEX_MODEL  — Override Codex model (default: gpt-5.6-terra)
  ORACLE_GROK_MODEL   — Override Grok model  (default: grok-4.5)
  ORACLE_GEMINI_MODEL — Override Gemini model (default: gemini-3.5-flash)
  ORACLE_SONNET_MODEL — Override Sonnet model (default: claude-sonnet-4-6)

Examples:
  python oracle2.py docs/PHASE3_SCALING_PLAN.md
  python oracle2.py docs/PHASE3_SCALING_PLAN.md --max-rounds 5
  python oracle2.py docs/PHASE3_SCALING_PLAN.md --output-dir reviews/scaling-v2

  # Compliance review against FAR rule pack (all Parts summary + selected Parts in full):
  python oracle2.py proposal.md --rulepack docs/far_rulepack.json --parts 15,19,52
""",
    )
    parser.add_argument("document", help="Path to the document to review")
    parser.add_argument("--max-rounds", type=int, default=4, help="Maximum review rounds (default: 4)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory (default: oracle_reviews/<timestamp>)")
    parser.add_argument("--workflow", choices=sorted(VALID_WORKFLOWS), default=DEFAULT_WORKFLOW, help="Review workflow (default: manual)")
    parser.add_argument("--rulepack", type=str, nargs="+", default=None, help="Path(s) to rule pack JSON (e.g., far_rulepack.json nfs_rulepack.json)")
    parser.add_argument("--parts", type=str, default=None, help="Comma-separated Part numbers for Tier 2 detail (e.g., 15,19,52,1852)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    doc_path = Path(args.document)
    if not doc_path.exists():
        LOGGER.error(f"Document not found: {doc_path}")
        sys.exit(1)

    draft = doc_path.read_text(encoding="utf-8")
    LOGGER.info(f"Loaded {doc_path} ({len(draft)} chars)")

    # Load rule pack(s) if specified
    compliance_context: str | None = None
    if args.rulepack:
        from build_far_rulepack import render_for_oracle

        selected_parts: list[int] | None = None
        if args.parts:
            selected_parts = [int(p.strip()) for p in args.parts.split(",") if p.strip().isdigit()]

        context_sections = []
        for i, rp_path_str in enumerate(args.rulepack, 1):
            rulepack_path = Path(rp_path_str)
            if not rulepack_path.exists():
                LOGGER.error(f"Rule pack not found: {rulepack_path}")
                sys.exit(1)

            with open(rulepack_path, encoding="utf-8") as f:
                rulepack = json.load(f)

            # Filter selected_parts to those that exist in this pack
            pack_part_nums = {p["part"] for p in rulepack.get("part_index", [])}
            parts_for_pack = [p for p in (selected_parts or []) if p in pack_part_nums] or None

            pack_name = rulepack.get("standard_title") or rulepack.get("standard_id") or rulepack_path.stem
            LOGGER.info(f"Rule pack {i}: {pack_name}, Tier 2 Parts: {parts_for_pack or 'summary only'}")

            rendered = render_for_oracle(rulepack, parts_for_pack)
            context_sections.append(f"## Authority {i}: {pack_name}\n\n{rendered}")

        compliance_context = "\n\n---\n\n".join(context_sections)
        LOGGER.info(f"Combined compliance context: {len(compliance_context)} chars (~{len(compliance_context)//4} tokens)")

    # Validate API keys
    missing = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not os.environ.get("XAI_API_KEY"):
        missing.append("XAI_API_KEY")
    if missing:
        LOGGER.error(f"Missing API keys: {', '.join(missing)}")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None
    session = run_review(
        draft=draft,
        document_path=str(doc_path),
        max_rounds=args.max_rounds,
        output_dir=output_dir,
        compliance_context=compliance_context,
        workflow=args.workflow,
    )

    metrics = compute_metrics(session)
    LOGGER.info(f"\n{'='*60}\nMetrics\n{'='*60}")
    for k, v in metrics.items():
        LOGGER.info(f"  {k}: {v}")

    if output_dir is None:
        output_dir = Path("oracle_reviews") / session.session_id
    (output_dir / "metrics.json").write_text(encoding="utf-8", data=json.dumps(metrics, indent=2))

    print(f"\nDone. Results in {output_dir}/")
    print(f"  final_draft.md          — Canonical revised document")
    print(f"  session_summary.json    — Round-by-round stats")
    print(f"  metrics.json            — QC scoring rubric")
    print(f"  roundN_*.json           — Per-round oracle outputs")


if __name__ == "__main__":
    main()

