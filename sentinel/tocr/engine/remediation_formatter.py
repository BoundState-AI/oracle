#!/usr/bin/env python3
"""
Module: TOCR Remediation Formatter (Sonnet/Bedrock)
Purpose: Generate contract-attorney-grade remediation language from structured findings.

Uses the same BSMH pattern: deterministic engine produces structured findings,
Sonnet writes the human-readable remediation in plain English that a task lead
can hand directly to a CO.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary
"""

__version__ = "1.0.0"

import asyncio
import json
import logging
import os
from typing import Any, Optional

from sentinel.tocr.models.evidence import TOCRFinding
from sentinel.tocr.models.remediation import RemediationStep
from sentinel.tocr.models.task_order import TaskOrder

LOGGER = logging.getLogger(__name__)

_TOCR_REMEDIATION_SYSTEM_PROMPT = """You are a senior NASA contracts attorney and compliance advisor writing
remediation instructions for a task order that failed compliance review.

Given a structured compliance finding with evidence, write clear, specific,
actionable remediation instructions that a task lead can follow immediately.

STRUCTURE (in this order):
1. PROBLEM: One sentence — what is wrong, in plain English. No jargon.
2. WHY THIS MATTERS: 2-3 sentences — the legal/regulatory consequence if not fixed.
   Cite the specific FAR clause and what it requires. If DCAA audit exposure exists, say so.
3. EXACTLY WHAT TO DO: Numbered steps. Be specific to THIS task order — reference
   the actual field paths, sub-task IDs, text that changed, and dollar amounts.
4. WHO NEEDS TO ACT: Name the role (CO, task lead, financial manager, legal) and
   what each person specifically needs to do.
5. DEADLINE GUIDANCE: Is this a release blocker? Can work proceed while it's fixed?

MANDATORY RULES:
- Write for someone who does NOT know FAR. Explain every acronym on first use.
- Reference specific text from the evidence — quote what was added/removed.
- For emergency justification findings: explain the three FAR 16.505(b)(4)
  requirements (circumstances, why normal procedures can't be followed, impact
  of delay) and assess whether the current justification meets each one.
- For undisclosed changes: show exactly what text changed and what needs to be
  added to the Summary of Changes.
- Never say "consult legal" without explaining what legal should look for.
- Be direct. If the finding suggests the emergency designation is unjustified,
  say so and explain why.

PROHIBITED:
- Generic advice like "review and update as needed"
- "Ensure compliance" without saying how
- Hedging language — if the FAR is clear, state the requirement clearly
- Internal system terminology (rule_id, field_path, signal names)

Keep response to 200-400 words. Every word should help the task lead fix the problem."""


def _finding_to_prompt_payload(
    step: RemediationStep,
    finding: TOCRFinding,
    task_order: Optional[TaskOrder] = None,
) -> dict[str, Any]:
    """Build the structured payload for the Sonnet prompt."""
    payload: dict[str, Any] = {
        "finding": {
            "rule_id": finding.rule_id,
            "rule_title": finding.rule_title,
            "severity": finding.severity.value,
            "review_priority": finding.review_priority.value,
            "finding_text": finding.finding_text,
            "guidance": finding.guidance,
            "remediation_template": finding.remediation,
            "authority_basis": finding.authority_basis,
        },
        "evidence": {},
        "current_remediation": {
            "what_to_fix": step.what_to_fix,
            "how_to_fix": step.how_to_fix,
            "why_it_matters": step.why_it_matters,
            "owner": step.owner,
        },
    }

    if finding.evidence:
        e = finding.evidence
        payload["evidence"] = {
            "field_path": e.field_path,
            "prior_text": e.prior_text[:500] if e.prior_text else "",
            "proposed_text": e.proposed_text[:500] if e.proposed_text else "",
            "change_type": e.change_type.value,
            "classification": e.classification.value,
        }

    if task_order:
        payload["task_order_context"] = {
            "to_number": task_order.task_order_number,
            "revision": task_order.revision_number,
            "title": task_order.title,
            "emergency_designation": task_order.emergency_designation,
            "emergency_justification": task_order.emergency_justification[:500]
            if task_order.emergency_justification else "",
            "sub_task_count": len(task_order.sub_tasks),
            "sub_task_ids": [st.sub_task_id for st in task_order.sub_tasks[:20]],
        }

    return payload


async def format_remediation_sonnet(
    step: RemediationStep,
    finding: TOCRFinding,
    task_order: Optional[TaskOrder] = None,
) -> Optional[str]:
    """
    Format a single remediation step using Sonnet via Bedrock or direct API.

    Returns the formatted text, or None if the call fails (caller should
    fall back to template-based remediation).

    Uses the same Bedrock/Anthropic pattern as BSMH response_formatter.
    """
    payload = _finding_to_prompt_payload(step, finding, task_order)
    user_message = json.dumps(payload, indent=2)

    use_bedrock = os.environ.get("USE_BEDROCK", "1").lower() in ("1", "true", "yes")
    bedrock_region = os.environ.get(
        "AWS_REGION",
        os.environ.get(
            "BEDROCK_REGION",
            os.environ.get("aws_region", os.environ.get("bedrock_region", "us-gov-west-1")),
        ),
    )
    model_bedrock = os.environ.get(
        "TOCR_SONNET_BEDROCK_MODEL",
        os.environ.get(
            "MIRA_MODEL_SONNET",
            os.environ.get("mira_model_sonnet", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
        ),
    )
    model_direct = os.environ.get(
        "TOCR_SONNET_DIRECT_MODEL",
        "claude-sonnet-4-5-20250929",
    )
    max_tokens = int(os.environ.get("TOCR_SONNET_MAX_TOKENS", "1200"))

    def _call_sonnet() -> str:
        if use_bedrock:
            from anthropic import AnthropicBedrock

            client = AnthropicBedrock(aws_region=bedrock_region)
            model = model_bedrock
        else:
            from anthropic import Anthropic

            api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is missing or empty.")

            client = Anthropic(api_key=api_key)
            model = model_direct

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=_TOCR_REMEDIATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text = (message.content[0].text or "").strip()
        if not text:
            raise RuntimeError("Sonnet formatter returned empty response.")
        return text

    # Use get_running_loop() — get_event_loop() is deprecated since Python 3.10
    # and may create a new loop unexpectedly in non-main threads.
    loop = asyncio.get_running_loop()
    try:
        text = await loop.run_in_executor(None, _call_sonnet)
        return text
    except (RuntimeError, ConnectionError, TimeoutError) as exc:
        LOGGER.warning("[TOCR] Sonnet remediation formatter failed: %s", exc)
        return None


async def format_all_remediations(
    steps: list[RemediationStep],
    findings: list[TOCRFinding],
    task_order: Optional[TaskOrder] = None,
    max_concurrent: int = 3,
) -> dict[str, str]:
    """
    Format all remediation steps using Sonnet, with concurrency limit.

    Returns a dict mapping finding_id -> formatted remediation text.
    Only includes entries where Sonnet succeeded; caller should fall back
    to template for missing entries.
    """
    finding_map = {f.finding_id: f for f in findings}
    results: dict[str, str] = {}

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _format_one(step: RemediationStep) -> None:
        finding = finding_map.get(step.finding_id)
        if not finding:
            return
        async with semaphore:
            text = await format_remediation_sonnet(step, finding, task_order)
            if text:
                results[step.finding_id] = text

    await asyncio.gather(*[_format_one(s) for s in steps])
    return results
