#!/usr/bin/env python3
"""
Module: dude.pipeline.passes
Purpose: Typed protocols for the model passes, plus Phase-1 stubs
         (spec v0.2 I12; v0.1 §32–33).

Every model pass sits behind a protocol. Phase-1 ships stubs only — no
network, mirroring HEARTH's stubbed ClauseAnalyzer. A stub declares
itself honestly: it returns empty output plus a Refusal naming the pass,
so a run's record says on its face which passes did not run. Fail closed
means the run reports what's missing; it never fabricates model output
and never silently proceeds as if a pass had run.

Any future live implementation must keep the contract: raw structured
returns, no free-prose authority, and a different provider for the
adversary than for the builder (v0.1 §55).

Safety Critical: False
Psychologically Critical: True — a stub that pretended to be a model
would be fabricated epistemics.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging
from typing import Protocol

from dude.data import Hypothesis, Interpretation, Observation, Refusal, Unknown
from dude.store.jsonl import CaseBundle

LOGGER = logging.getLogger("dude.pipeline.passes")

STUB_REASON = "Pass is stubbed in Phase 1 (no model configured); no output produced."


class PassOutput:
    """Container: whatever a pass produced, plus refusals. Slots keep it
    honest — passes cannot smuggle extra channels."""

    __slots__ = ("observations", "interpretations", "unknowns", "hypotheses", "refusals")

    def __init__(
        self,
        observations: list[Observation] | None = None,
        interpretations: list[Interpretation] | None = None,
        unknowns: list[Unknown] | None = None,
        hypotheses: list[Hypothesis] | None = None,
        refusals: list[Refusal] | None = None,
    ) -> None:
        self.observations = observations or []
        self.interpretations = interpretations or []
        self.unknowns = unknowns or []
        self.hypotheses = hypotheses or []
        self.refusals = refusals or []


class SeparatorPass(Protocol):
    """P2: observation/inference separation over captures."""

    def run(self, bundle: CaseBundle) -> PassOutput: ...


class UnknownsPass(Protocol):
    """P3: what's missing."""

    def run(self, bundle: CaseBundle) -> PassOutput: ...


class HypothesisPass(Protocol):
    """P4: competing causal models (archetypes attempted, honest exits)."""

    def run(self, bundle: CaseBundle) -> PassOutput: ...


class AdversaryPass(Protocol):
    """P5: attack hypotheses in both directions (v0.1 §34). Output attaches
    as annotations, never merges (v0.2 I10)."""

    def run(self, bundle: CaseBundle) -> PassOutput: ...


class _Stub:
    """Shared stub behavior: empty output + a named refusal."""

    pass_name = "stub"

    def run(self, bundle: CaseBundle) -> PassOutput:  # noqa: ARG002
        return PassOutput(
            refusals=[Refusal(pass_name=self.pass_name, reason=STUB_REASON)]
        )


class StubSeparator(_Stub):
    pass_name = "separator"


class StubUnknowns(_Stub):
    pass_name = "unknowns"


class StubHypotheses(_Stub):
    pass_name = "hypotheses"


class StubAdversary(_Stub):
    pass_name = "adversary"


class PassSet:
    """The pass configuration handed to analyze(). Defaults to all stubs."""

    def __init__(
        self,
        separator: SeparatorPass | None = None,
        unknowns: UnknownsPass | None = None,
        hypotheses: HypothesisPass | None = None,
        adversary: AdversaryPass | None = None,
    ) -> None:
        self.separator = separator or StubSeparator()
        self.unknowns = unknowns or StubUnknowns()
        self.hypotheses = hypotheses or StubHypotheses()
        self.adversary = adversary or StubAdversary()
