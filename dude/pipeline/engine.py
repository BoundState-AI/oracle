#!/usr/bin/env python3
"""
Module: dude.pipeline.engine
Purpose: The resolved control flow (spec v0.2 §2, invariants I1/I2/I3).

Order is the contract:
  capture():  safety floor -> persist SafetyEvent -> persist Capture
  analyze():  safety floor -> persist SafetyEvent -> fingerprint -> gate
              -> (NO_NEW_DATA: serve prior + cumulative; crisis NEVER
              gated) -> passes (fail closed) -> triggers -> conduct ->
              deltas -> actions -> template-bound summary -> persist run

The safety scan runs BEFORE the gate in both entry points, and its
persistence failure aborts the run (StoreError propagates as a refusal).
The summary is assembled only from vetted templates and validated
against the banned-phrase floor — free prose cannot contradict or omit
the safety verdict because the verdict is injected verbatim.

Safety Critical: True
Psychologically Critical: True

Never-suppress-error: nothing in this module catches StoreError; a
failed write aborts the run loudly.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import logging
from dataclasses import dataclass

from dude.core import actions as action_engine
from dude.core import conduct, fingerprint, loop, safety
from dude.core import triggers as trigger_engine
from dude.core.state import CaseEvent, transition
from dude.data import (
    AnalysisRun,
    Capture,
    Case,
    ConfidenceAdjustment,
    GateMode,
    HypothesisDelta,
    Refusal,
    SafetyEvent,
    SafetyScanResult,
    SourceType,
)
from dude.data.actions import ActionEvaluation, ActionRecommendation
from dude.pipeline.passes import PassSet
from dude.store.jsonl import CaseBundle, CaseStore

LOGGER = logging.getLogger("dude.pipeline.engine")


@dataclass
class AnalysisResult:
    """What analyze() hands the surface layer."""

    run: AnalysisRun
    safety: SafetyScanResult
    served_prior: bool
    recommendation: ActionRecommendation | None = None


def capture(
    store: CaseStore,
    case_id: str,
    text: str,
    source_type: SourceType = SourceType.USER_STATEMENT,
) -> tuple[Capture, SafetyScanResult]:
    """Stage-1 capture (v0.2 §2). Safety floor first; SafetyEvent is
    persisted before the capture itself so a store failure can never lose
    a crisis flag while keeping the content."""
    scan = safety.scan(text)
    record = Capture(case_id=case_id, text=text, source_type=source_type)
    if scan.flags:
        store.append(
            SafetyEvent(
                case_id=case_id,
                capture_id=record.id,
                flags=scan.flags,
                crisis=scan.crisis,
            )
        )
    store.append(record)
    return record, scan


def analyze(store: CaseStore, case_id: str, passes: PassSet | None = None) -> AnalysisResult:
    """The resolved analyze() control flow (v0.2 §2)."""
    passes = passes or PassSet()
    bundle = store.load_case(case_id)

    # I1: safety floor before every gate, persisted first.
    scan = safety.scan(bundle.all_text())
    if scan.flags:
        store.append(
            SafetyEvent(case_id=case_id, flags=scan.flags, crisis=scan.crisis)
        )

    prior = bundle.analysis_runs[-1] if bundle.analysis_runs else None
    current = fingerprint.scope_fingerprint(
        case=bundle.case,
        captures=bundle.captures,
        artifacts=bundle.artifacts,
        events=bundle.events,
        interpretations=bundle.interpretations,
        hypotheses=bundle.hypotheses,
        last_run_at=prior.recorded_at if prior else None,
    )
    mode = fingerprint.gate(current, prior.fingerprint if prior else None)

    if mode is GateMode.NO_NEW_DATA and prior is not None:
        # Crisis output is NEVER gated; the prior run is served with the
        # evidence-state message and a fresh cumulative view.
        LOGGER.info("Gate: NO_NEW_DATA for case %s; serving prior run", case_id)
        return AnalysisResult(run=prior, safety=scan, served_prior=True)

    refusals: list[Refusal] = []
    for model_pass in (passes.separator, passes.unknowns, passes.hypotheses, passes.adversary):
        output = model_pass.run(bundle)
        refusals.extend(output.refusals)
        for record in (
            output.observations + output.interpretations
            + output.unknowns + output.hypotheses
        ):
            store.append(record)
    # Reload so pass output participates downstream (annotation attachment
    # is append + reload — reconcile() is bookkeeping, not judgment, I10).
    bundle = store.load_case(case_id)

    matches = trigger_engine.match(store.load_triggers(), bundle.all_text())
    adjustment = trigger_engine.merge(matches)
    patterns = conduct.accrue(bundle.events)
    deltas = _deltas(bundle, prior)
    recommendation = _recommend(bundle, refusals)

    run = AnalysisRun(
        case_id=case_id,
        mode=mode,
        fingerprint=current,
        crisis_active=scan.crisis,
        hypothesis_bands={h.lineage_id: h.band for h in bundle.hypotheses},
        deltas=deltas,
        cumulative_patterns=patterns,
        trigger_matches=matches,
        adjustment=adjustment,
        refusals=refusals,
        user_facing_summary=_summary(mode, scan, adjustment, refusals),
    )
    store.append(run)
    updated = bundle.case.model_copy(
        update={"status": transition(bundle.case.status, CaseEvent.ANALYSIS_PERSISTED)}
    )
    store.append(updated)
    return AnalysisResult(
        run=run, safety=scan, served_prior=False, recommendation=recommendation
    )


def _deltas(bundle: CaseBundle, prior: AnalysisRun | None) -> list[HypothesisDelta]:
    """Band movement keyed by lineage (v0.1 §19–20; review A21)."""
    previous = prior.hypothesis_bands if prior else {}
    deltas = []
    for hypothesis in bundle.hypotheses:
        before = previous.get(hypothesis.lineage_id)
        if before != hypothesis.band:
            deltas.append(
                HypothesisDelta(
                    lineage_id=hypothesis.lineage_id,
                    title=hypothesis.title,
                    previous=before,
                    current=hypothesis.band,
                    reason="Band set by user or pass output this run.",
                )
            )
    return deltas


def _recommend(
    bundle: CaseBundle, refusals: list[Refusal]
) -> ActionRecommendation | None:
    """Score actions when options, evaluations, and live hypotheses exist.
    The safety_seeking marker note is stamped here when pairing options
    with evaluations (see dude.core.actions._is_safety_seeking)."""
    if not bundle.action_options or not bundle.hypotheses:
        return None
    safety_ids = {o.id for o in bundle.action_options if o.safety_seeking}
    evaluations = [
        ev.model_copy(update={"notes": [*ev.notes, "safety_seeking"]})
        if ev.action_id in safety_ids and "safety_seeking" not in ev.notes
        else ev
        for ev in bundle.action_evaluations
    ]
    try:
        return action_engine.recommend(
            case_id=bundle.case.id,
            options=bundle.action_options,
            evaluations=evaluations,
            hypotheses=bundle.hypotheses,
        )
    except ValueError as exc:
        # Fail closed as a visible refusal, not a silent missing section.
        LOGGER.error("Action scoring refused: %s", exc)
        refusals.append(Refusal(pass_name="action_scoring", reason=str(exc)))
        return None


def _summary(
    mode: GateMode,
    scan: SafetyScanResult,
    adjustment: ConfidenceAdjustment,
    refusals: list[Refusal],
) -> str:
    """Template-bound synthesis (v0.2 §2): vetted copy only, safety verdict
    injected verbatim, validated against the banned-phrase floor."""
    parts: list[str] = []
    if scan.crisis:
        parts.append(scan.user_facing_message)
        parts.extend(f"{r.name}: {r.contact}" for r in scan.resources)
    parts.append(loop.mode_message(mode))
    if adjustment.user_facing_note:
        parts.append(adjustment.user_facing_note)
    if refusals:
        names = ", ".join(sorted({r.pass_name for r in refusals}))
        parts.append(f"Passes that did not run this analysis: {names}.")
    return loop.validate_copy("\n\n".join(parts))
