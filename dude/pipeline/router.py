#!/usr/bin/env python3
"""
Module: dude.pipeline.router
Purpose: Model router (spec v0.1 §54–55, mechanized).

The §55 invariant — never let one model generate, critique, score, and
certify itself — is enforced structurally here: a ModelRouter carries a
`primary` chat model (extraction/hypotheses) and an `adversary` chat
model, and refuses construction when both would be the same provider.
With only one provider configured, the builder passes can go live but
the adversary stays a visible refusal — never a same-provider
self-certification.

Providers are resolved from environment keys at call time:
  ANTHROPIC_API_KEY -> Anthropic (model: $DUDE_ANTHROPIC_MODEL,
                       default claude-sonnet-5)
  OPENAI_API_KEY    -> OpenAI    (model: $DUDE_OPENAI_MODEL,
                       default gpt-5.4)

Safety Critical: True — routing decides which model authorities exist;
a silent same-provider fallback would fabricate independence.
Psychologically Critical: False

Never-suppress-error: provider failures raise ModelCallError with the
original cause; callers convert to refusals, never to empty output.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = False

import logging
import os
from dataclasses import dataclass
from typing import Protocol

LOGGER = logging.getLogger("dude.pipeline.router")

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
MAX_OUTPUT_TOKENS = 8192
REQUEST_TIMEOUT_SECONDS = 120.0


class ModelCallError(Exception):
    """A provider call failed. Callers refuse; they never fabricate."""


class ChatModel(Protocol):
    """One system+user completion returning raw text. Provider identity
    is exposed so the router can enforce independence."""

    provider: str

    def complete(self, system: str, user: str) -> str: ...


class AnthropicChat:
    provider = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        import anthropic

        self._model = model or os.environ.get(
            "DUDE_ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL
        )
        self._client = anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS)

    def complete(self, system: str, user: str) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            LOGGER.error("Anthropic call failed: %s", exc)
            raise ModelCallError(f"Anthropic call failed: {exc}") from exc
        return "".join(
            block.text for block in response.content if block.type == "text"
        )


class OpenAIChat:
    provider = "openai"

    def __init__(self, model: str | None = None) -> None:
        import openai

        self._model = model or os.environ.get("DUDE_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        self._client = openai.OpenAI(timeout=REQUEST_TIMEOUT_SECONDS)

    def complete(self, system: str, user: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:
            LOGGER.error("OpenAI call failed: %s", exc)
            raise ModelCallError(f"OpenAI call failed: {exc}") from exc
        return response.choices[0].message.content or ""


@dataclass(frozen=True)
class ModelRouter:
    """primary drives builder passes; adversary attacks. Distinct
    providers or no adversary at all — enforced at construction."""

    primary: ChatModel
    adversary: ChatModel | None

    def __post_init__(self) -> None:
        if (
            self.adversary is not None
            and self.adversary.provider == self.primary.provider
        ):
            raise ValueError(
                "Adversary must run on a different provider than the "
                "builder (spec v0.1 §55); refusing same-provider "
                "self-certification."
            )


def resolve_router() -> ModelRouter | None:
    """Build the best router the environment allows, or None (stubs).

    Anthropic is preferred as primary when both providers exist; the
    other provider becomes the adversary. One provider -> live builder,
    refused adversary. Zero -> None."""
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if has_anthropic and has_openai:
        # DUDE_PRIMARY_PROVIDER=openai flips the roles: OpenAI builds,
        # Anthropic attacks. Both roles always exist (§55).
        if os.environ.get("DUDE_PRIMARY_PROVIDER", "").lower() == "openai":
            return ModelRouter(primary=OpenAIChat(), adversary=AnthropicChat())
        return ModelRouter(primary=AnthropicChat(), adversary=OpenAIChat())
    if has_anthropic:
        LOGGER.warning("Single provider (anthropic): adversary pass will refuse.")
        return ModelRouter(primary=AnthropicChat(), adversary=None)
    if has_openai:
        LOGGER.warning("Single provider (openai): adversary pass will refuse.")
        return ModelRouter(primary=OpenAIChat(), adversary=None)
    return None
