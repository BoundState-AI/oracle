#!/usr/bin/env python3
"""
Module: oracle.oracle2
Purpose: Multi-oracle review system for specs, plans, and architecture docs.

Flow:
  Round 0: Beth (Opus 4.6) writes or accepts the canonical draft
  Round 1: Fran (GPT-5.4), Codex (GPT-5.4), Grok (xAI) review independently (blind)
  Round 1.5: Sonnet (Claude Sonnet 4.6) normalizes/deduplicates findings
  Round 2: Beth classifies findings, revises draft
  Round 3+: Re-review changed sections until convergence

Convergence:
  - No new critical findings
  - New high findings <= 1
  - Delta in accepted defects < 10%
  - Same unresolved tradeoff repeats twice

__safety_critical__: bool = True — multi-oracle compliance review engine

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

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
7. If a concern is speculative, label it as speculative.
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
      "confidence": 0.0
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
5. Detect direct conflicts between reviewers.
6. Produce a normalized issue ledger for the coordinator.
7. If an issue was seen in prior rounds, REUSE the same issue_id so Beth
   and the convergence checker can track continuity across rounds.

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
      "weak_signal": false
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
# WHY "high": reviewers must reason carefully about compliance implications;
# lower effort risks missed findings on nuanced regulatory language.
OPENAI_REASONING_EFFORT = os.environ.get("ORACLE_OPENAI_REASONING_EFFORT", "high")
OPENAI_VERBOSITY = os.environ.get("ORACLE_OPENAI_VERBOSITY", "low")

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
    "referee": {"normalized_issues": list},
}


@dataclass
class OracleConfig:
    """Configuration for one oracle."""
    name: str
    role: str
    provider: str       # "anthropic" | "openai" | "xai"
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
        model=os.environ.get("ORACLE_BETH_MODEL", "claude-opus-4-6"),
        system_prompt=BETH_COORDINATOR_PROMPT,
        temperature=0.0,
        max_tokens=BETH_COORDINATOR_MAX_TOKENS,
    ),
    "fran": OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model=os.environ.get("ORACLE_FRAN_MODEL", "gpt-5.4"),
        system_prompt=FRAN_ADVERSARIAL_PROMPT,
        max_tokens=int(
            os.environ.get("ORACLE_FRAN_MAX_TOKENS", str(OPENAI_REVIEWER_MAX_TOKENS))
        ),
    ),
    "codex": OracleConfig(
        name="Codex",
        role="implementation_feasibility",
        provider="openai",
        model=os.environ.get("ORACLE_CODEX_MODEL", "gpt-5.4"),
        system_prompt=CODEX_FEASIBILITY_PROMPT,
        max_tokens=int(
            os.environ.get("ORACLE_CODEX_MAX_TOKENS", str(OPENAI_REVIEWER_MAX_TOKENS))
        ),
    ),
    "grok": OracleConfig(
        name="Grok",
        role="contrarian",
        provider="xai",
        model=os.environ.get("ORACLE_GROK_MODEL", "grok-4.20"),
        system_prompt=GROK_CONTRARIAN_PROMPT,
    ),
    "sonnet": OracleConfig(
        name="Sonnet",
        role="referee",
        provider="anthropic",
        model=os.environ.get("ORACLE_SONNET_MODEL", "claude-sonnet-4-6"),
        system_prompt=SONNET_REFEREE_PROMPT,
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
        timeout=httpx.Timeout(config.timeout, connect=10.0),
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
    return _parse_json(text, config.name)


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
        timeout=httpx.Timeout(config.timeout, connect=10.0),
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
            "raw": message.refusal[:2000],
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
        }

    return _parse_json(text, config.name)


def _call_xai(config: OracleConfig, user_message: str) -> dict:
    """Call xAI/Grok API (OpenAI-compatible endpoint)."""
    import httpx
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ.get("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
        timeout=httpx.Timeout(config.timeout, connect=10.0),
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
    response = client.chat.completions.create(**kwargs)
    text = response.choices[0].message.content or ""
    return _parse_json(text, config.name)


PROVIDER_DISPATCH = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "xai": _call_xai,
}


MAX_RETRIES = 3
RETRY_BACKOFF = (2, 4, 8)  # seconds


def call_oracle(config: OracleConfig, user_message: str) -> dict:
    """Route to the correct provider with retries and backoff."""
    dispatch = PROVIDER_DISPATCH.get(config.provider)
    if not dispatch:
        raise ValueError(f"Unknown provider: {config.provider}")

    last_error = None
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            LOGGER.warning(f"[{config.name}] Retry {attempt}/{MAX_RETRIES} after {wait}s...")
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
                continue

            # Schema validation: check required fields for this oracle's role
            schema_error = _validate_schema(result, config)
            if schema_error:
                LOGGER.warning(f"[{config.name}] Schema invalid: {schema_error}")
                last_error = f"Schema: {schema_error}"
                continue

            findings_count = len(result.get("findings", result.get("normalized_issues", [])))
            LOGGER.info(f"[{config.name}] Done in {elapsed:.1f}s — {findings_count} findings")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            LOGGER.error(f"[{config.name}] Failed in {elapsed:.1f}s: {e}")
            last_error = str(e)

    # All retries exhausted
    raise RuntimeError(f"[{config.name}] Failed after {MAX_RETRIES} attempts: {last_error}")


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

    if config.role in ("adversarial_logic", "implementation_feasibility", "contrarian"):
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
        return {"oracle_name": oracle_name, "error": "No JSON found", "raw": text[:2000]}

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


def _recover_truncated_json(text: str, oracle_name: str) -> dict:
    """Attempt to recover useful data from truncated Beth responses.

    Beth's revised_draft field is often so large that the response
    gets truncated mid-JSON. This extracts what we can:
    1. Try to find revision_decisions before the truncation
    2. Extract revised_draft content even if JSON is incomplete
    """
    import re

    result: dict = {"oracle_name": oracle_name}

    # Try to extract revised_draft as a raw string between markers
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
            # Unescape JSON string escapes
            try:
                revised = json.loads(f'"{raw_draft}"')
                result["revised_draft"] = revised
                LOGGER.info(f"[{oracle_name}] Recovered revised_draft ({len(revised)} chars)")
            except Exception:
                # Even raw is useful
                result["revised_draft"] = raw_draft.replace("\\n", "\n").replace('\\"', '"')
                LOGGER.info(f"[{oracle_name}] Recovered raw revised_draft ({len(raw_draft)} chars)")
        else:
            # Truncated mid-draft — take what we have
            raw_draft = text[draft_start:]
            result["revised_draft"] = raw_draft.replace("\\n", "\n").replace('\\"', '"')
            LOGGER.info(f"[{oracle_name}] Recovered truncated revised_draft ({len(raw_draft)} chars)")

    # Try to extract revision_decisions array
    decisions_match = re.search(r'"revision_decisions"\s*:\s*\[', text)
    if decisions_match:
        bracket_start = decisions_match.end() - 1
        depth = 0
        for i in range(bracket_start, len(text)):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    try:
                        decisions = json.loads(text[bracket_start:i + 1])
                        result["revision_decisions"] = decisions
                    except Exception:
                        pass
                    break

    # Defaults for missing fields
    result.setdefault("revision_decisions", [])
    result.setdefault("revised_sections", [])
    result.setdefault("open_questions", [])

    if "revised_draft" not in result:
        LOGGER.error(f"[{oracle_name}] Could not recover any content from truncated response")
        result["error"] = "Truncated JSON, no recoverable content"
        result["raw"] = text[:2000]

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
    valid: bool = False  # True only if all required oracles succeeded


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


def _build_referee_message(
    draft: str,
    reviews: dict[str, dict],
    round_number: int,
    prior_issues: list[dict] | None = None,
) -> str:
    """Build the message for Sonnet referee."""
    msg = f"## Round {round_number}\n\n## Canonical Draft\n\n{draft}\n\n## Reviewer Outputs\n\n"
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


def _check_convergence(session: OracleSession) -> tuple[bool, str]:
    """Check if the review loop should stop.

    Only compares valid rounds. Invalid rounds are skipped entirely.

    Convergence criteria:
    1. No critical findings remain
    2. High findings <= 1
    3. Issue set stability: >80% of issue_ids overlap between rounds
    4. Any single unresolved tradeoff appears in 2+ consecutive valid rounds
    """
    previous, current = _last_two_valid_rounds(session)
    if previous is None or current is None:
        return False, "Need at least 2 valid rounds"

    issues = current.normalized_issues.get("normalized_issues", [])

    # 1. No critical findings
    critical = [i for i in issues if i.get("severity") == "critical"]
    if critical:
        return False, f"{len(critical)} critical findings remain"

    # 2. High findings <= 1
    high = [i for i in issues if i.get("severity") == "high"]
    if len(high) > 1:
        return False, f"{len(high)} high findings remain"

    # 3. Issue set stability (by issue_id, not count)
    current_ids = {i.get("issue_id") for i in issues if i.get("issue_id")}
    prev_issues = previous.normalized_issues.get("normalized_issues", [])
    prev_ids = {i.get("issue_id") for i in prev_issues if i.get("issue_id")}
    if current_ids and prev_ids:
        overlap = len(current_ids & prev_ids) / max(len(current_ids | prev_ids), 1)
        if overlap < 0.8:
            return False, f"Issue set unstable: {overlap:.0%} overlap ({len(current_ids)} vs {len(prev_ids)})"
    elif not current_ids and not prev_ids:
        overlap = 1.0  # Both empty = stable
    elif not current_ids and prev_ids:
        # All prior issues resolved — converge (critical/high already passed above)
        overlap = 1.0
    else:
        # No prior issues but new ones appeared — not stable
        overlap = 0.0
        return False, f"Issue set unstable: new issues appeared ({len(current_ids)} vs {len(prev_ids)})"

    # 4. Same unresolved tradeoff repeats across valid rounds
    current_open = set(current.coordinator_decisions.get("open_questions", []))
    prev_open = set(previous.coordinator_decisions.get("open_questions", []))
    repeated = current_open & prev_open
    if repeated:
        return True, f"Converged (repeated tradeoffs: {repeated})"

    return True, f"Converged: {len(high)} high, issue overlap {overlap:.0%}"


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
    from concurrent.futures import ThreadPoolExecutor, as_completed

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

    required_reviewers = ("fran", "codex", "grok")
    reviewer_failed = False

    def _call_reviewer(key: str) -> tuple[str, dict]:
        config = ORACLE_ROSTER[key]
        try:
            result = call_oracle(config, review_msg)
            return config.name, result
        except Exception as e:
            LOGGER.error(f"[{config.name}] FAILED after retries: {e}")
            return config.name, {"oracle_name": config.name, "error": str(e), "findings": []}

    LOGGER.info(f"  Launching {len(required_reviewers)} reviewers in parallel...")
    with ThreadPoolExecutor(max_workers=len(required_reviewers)) as pool:
        futures = {pool.submit(_call_reviewer, key): key for key in required_reviewers}
        for future in as_completed(futures):
            name, result = future.result()
            review_round.reviewer_outputs[name] = result
            if "error" in result and not result.get("findings"):
                reviewer_failed = True

    for name, output in review_round.reviewer_outputs.items():
        (output_dir / f"round{round_num}_{name.lower()}.json").write_text(
            encoding="utf-8", data=json.dumps(output, indent=2)
        )

    if reviewer_failed:
        LOGGER.error(f"Round {round_num} INVALID: required reviewer failed.")
        session.rounds.append(review_round)
        return review_round, False

    # --- Sonnet normalizes ---
    referee_msg = _build_referee_message(
        session.canonical_draft, review_round.reviewer_outputs,
        round_number=round_num, prior_issues=prior_issues,
    )
    try:
        normalized = call_oracle(ORACLE_ROSTER["sonnet"], referee_msg)
    except Exception as e:
        LOGGER.error(f"[Sonnet] FAILED after retries: {e}. Round invalid.")
        session.rounds.append(review_round)
        return review_round, False

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
    except Exception as e:
        LOGGER.error(f"[Beth] FAILED after retries: {e}. Round invalid.")
        session.rounds.append(review_round)
        return review_round, False

    review_round.coordinator_decisions = beth_response

    revised = beth_response.get("revised_draft")
    if revised and isinstance(revised, str) and revised.strip():
        session.canonical_draft = revised.strip()
        review_round.revised_draft = session.canonical_draft
        LOGGER.info(f"[Beth] Draft revised ({len(session.canonical_draft)} chars)")
    else:
        LOGGER.info("[Beth] No revision to draft this round")

    review_round.valid = True

    (output_dir / f"round{round_num}_beth_decisions.json").write_text(
        encoding="utf-8", data=json.dumps(beth_response, indent=2)
    )
    if review_round.revised_draft:
        (output_dir / f"round{round_num}_revised_draft.md").write_text(
            encoding="utf-8", data=review_round.revised_draft
        )

    session.rounds.append(review_round)

    converged, reason = _check_convergence(session)
    if converged:
        session.converged = True
        session.convergence_reason = reason
        LOGGER.info(f"\nConverged after round {round_num}: {reason}")
    else:
        LOGGER.info(f"\nNot converged: {reason}")

    return review_round, converged


def run_review(
    draft: str,
    document_path: str = "",
    max_rounds: int = 3,
    output_dir: Path | None = None,
    compliance_context: str | None = None,
) -> OracleSession:
    """Run the full multi-oracle review loop.

    Dispatches up to max_rounds through _run_round(), checking convergence
    after each.  Saves final_draft.md and session_summary.json on completion.
    """
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

    for round_num in range(1, max_rounds + 1):
        LOGGER.info(f"\n{'='*60}\nRound {round_num}\n{'='*60}")
        _, converged = _run_round(session, round_num, output_dir, compliance_context)
        if converged:
            break

    # Save final state
    (output_dir / "final_draft.md").write_text(encoding="utf-8", data=session.canonical_draft)
    summary = {
        "session_id": session.session_id,
        "document_path": session.document_path,
        "total_rounds": len(session.rounds),
        "converged": session.converged,
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
    }
    (output_dir / "session_summary.json").write_text(encoding="utf-8", data=json.dumps(summary, indent=2))
    LOGGER.info(f"\nResults saved to {output_dir}/")

    return session


# ---------------------------------------------------------------------------
# Scoring / QC metrics
# ---------------------------------------------------------------------------

def compute_metrics(session: OracleSession) -> dict:
    """Compute the QC scoring rubric for a completed review.

    Joins Beth's decisions to Sonnet's normalized issues by issue_id,
    not by fuzzy title matching.
    """
    # Build issue_id → severity lookup from Sonnet's normalized issues
    issue_severity: dict[str, str] = {}
    for r in session.rounds:
        for issue in r.normalized_issues.get("normalized_issues", []):
            iid = issue.get("issue_id", "")
            if iid:
                issue_severity[iid] = issue.get("severity", "low")

    # Classify Beth's decisions by joining on issue_id
    all_decisions = []
    for r in session.rounds:
        all_decisions.extend(r.coordinator_decisions.get("revision_decisions", []))

    accepted = [d for d in all_decisions if d.get("decision") == "accepted_defect"]
    rejected = [d for d in all_decisions if d.get("decision") == "rejected_claim"]
    preference = [d for d in all_decisions if d.get("decision") == "preference_only"]

    # Count accepted by severity via issue_id join
    accepted_ids = {d.get("issue_id") for d in accepted if d.get("issue_id")}
    critical_accepted = sum(
        1 for iid in accepted_ids if issue_severity.get(iid) == "critical"
    )
    high_accepted = sum(
        1 for iid in accepted_ids if issue_severity.get(iid) == "high"
    )

    # Dropped findings from Sonnet
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

    # Valid rounds = all 5 oracles succeeded (reviewer + Sonnet + Beth)
    valid_rounds = sum(1 for r in session.rounds if r.valid)

    return {
        "accepted_critical_count": critical_accepted,
        "accepted_high_count": high_accepted,
        "total_accepted_defects": len(accepted),
        "total_rejected_claims": len(rejected),
        "total_preference_only": len(preference),
        "novel_issue_count": len(issue_severity),
        "duplicate_rate": duplicate_count / max(total_findings, 1),
        "unsupported_claim_rate": unsupported_count / max(total_findings, 1),
        "rounds_to_stability": len(session.rounds),
        "valid_rounds": valid_rounds,
        "converged": session.converged,
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
  ANTHROPIC_API_KEY   — Required for Beth (Opus) and Sonnet
  OPENAI_API_KEY      — Required for Fran and Codex (GPT-5.4)
  XAI_API_KEY         — Required for Grok

  ORACLE_BETH_MODEL   — Override Beth model  (default: claude-opus-4-6)
  ORACLE_FRAN_MODEL   — Override Fran model  (default: gpt-5.4)
  ORACLE_CODEX_MODEL  — Override Codex model (default: gpt-5.4)
  ORACLE_GROK_MODEL   — Override Grok model  (default: grok-4)
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
    parser.add_argument("--max-rounds", type=int, default=3, help="Maximum review rounds (default: 3)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory (default: oracle_reviews/<timestamp>)")
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
