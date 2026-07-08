#!/usr/bin/env python3
"""
Module: dude.pipeline.engine
Purpose: The resolved control flow (spec v0.2 §2, invariants I1/I2/I3).

Order is the contract:
  capture():  safety floor -> persist SafetyEvent -> persist Capture
  analyze():  safety floor -> persist SafetyEvent -> fingerprint -> gate
              -> (NO_NEW_DATA: serve prior + cumulative; crisis NEVER
              gated) -> passes (fail closed) -> trigger layer (trigger
              spec v1.1: pre-filter -> policy-checked retrieval ->
              proposals; confirmed assessments + non-superseded legacy
              matches -> ONE merged adjustment; danger families escalate
              to safety, R2) -> conduct -> deltas -> actions ->
              template-bound summary -> persist run

The action engine and NEED-TO-ACT take ZERO trigger-derived inputs (R1);
while a crisis is active the overlap display is demoted below resources
(R2).

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
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dude.core import actions as action_engine
from dude.core import conduct, fingerprint, loop, safety
from dude.core.state import CaseEvent, transition
from dude.data import (
    AnalysisRun,
    Capture,
    Case,
    GateMode,
    HypothesisDelta,
    Refusal,
    SafetyEvent,
    SafetyScanResult,
    SourceType,
)
from dude.data.actions import ActionEvaluation, ActionRecommendation
from dude.pipeline.passes import (
    AdversaryPass,
    HypothesisPass,
    PassOutput,
    PassSet,
    SeparatorPass,
    UnknownsPass,
)
from dude.store.jsonl import CaseBundle, CaseStore, StoreError
from dude.triggers import assess as trigger_assess
from dude.triggers import distortion
from dude.triggers.assess import StubAssessor, TriggerAssessor, TriggerLayerResult
from dude.triggers.contracts import DEFAULT_USER_ID, OverlapLevel
from dude.triggers.store import TriggerStore

LOGGER = logging.getLogger("dude.pipeline.engine")

# NEED TO ACT NOW is computed from deadlines + safety state only (v1.1
# R2): trigger overlap is an illegal input, enforced structurally — the
# computation has no trigger parameter.
NEED_TO_ACT_DEADLINE_WINDOW = timedelta(hours=72)


@dataclass
class AnalysisResult:
    """What analyze() hands the surface layer."""

    run: AnalysisRun
    safety: SafetyScanResult
    served_prior: bool
    recommendation: ActionRecommendation | None = None
    need_to_act: str = "low"


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


def analyze(
    store: CaseStore,
    case_id: str,
    passes: PassSet | None = None,
    assessor: TriggerAssessor | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> AnalysisResult:
    """The resolved analyze() control flow (v0.2 §2; trigger layer per
    trigger spec v1.1)."""
    passes = passes or PassSet()
    assessor = assessor or StubAssessor()
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
        # Stub refusals are permanent until a model is configured —
        # re-running completes nothing, so they don't reopen the gate.
        from dude.pipeline.passes import STUB_REASON

        transient_refusals = [r for r in prior.refusals if r.reason != STUB_REASON]
        if transient_refusals:
            # An incomplete prior run never gates its own completion
            # (GateMode.INCOMPLETE_PRIOR_RERUN — see enums for WHY).
            mode = GateMode.INCOMPLETE_PRIOR_RERUN
        else:
            # Crisis output is NEVER gated; the prior run is served with
            # the evidence-state message and a fresh cumulative view.
            LOGGER.info("Gate: NO_NEW_DATA for case %s; serving prior run", case_id)
            return AnalysisResult(
                run=prior,
                safety=scan,
                served_prior=True,
                need_to_act=_need_to_act_now(bundle.case, scan.crisis),
            )

    pre_pass = bundle  # the evidence snapshot the passes actually see
    bundle, refusals = _run_model_passes(store, bundle, passes)

    # Recompute the fingerprint with the post-pass HYPOTHESIS set but the
    # PRE-PASS evidence snapshot. Evidence must come from the snapshot the
    # passes actually analyzed: a capture landing mid-run (models take
    # tens of seconds) must stay OUTSIDE this run's fingerprint, or the
    # gate will believe evidence was analyzed that no pass ever saw
    # (found in production — the Vann captures were swallowed).
    current = fingerprint.scope_fingerprint(
        case=pre_pass.case,
        captures=pre_pass.captures,
        artifacts=pre_pass.artifacts,
        events=pre_pass.events,
        interpretations=pre_pass.interpretations,
        hypotheses=bundle.hypotheses,
        last_run_at=prior.recorded_at if prior else None,
    )
    # Trigger layer (trigger spec v1.1): deterministic pre-filter ->
    # policy-checked retrieval -> proposal pass -> confirmed assessments
    # + non-superseded legacy matches -> the ONE merged adjustment.
    run_id = uuid.uuid4().hex
    trigger_layer = trigger_assess.assess_case(
        TriggerStore(store), bundle, store.load_triggers(), assessor, run_id, user_id
    )
    refusals.extend(trigger_layer.refusals)
    # R2: danger-shaped family matches escalate INTO the safety layer.
    scan = _escalate(store, case_id, scan, trigger_layer)
    recommendation = _recommend(bundle, refusals)
    run = AnalysisRun(
        id=run_id,
        case_id=case_id,
        mode=mode,
        fingerprint=current,
        crisis_active=scan.crisis,
        hypothesis_bands={h.lineage_id: h.band for h in bundle.hypotheses},
        deltas=_deltas(bundle, prior),
        cumulative_patterns=conduct.accrue(bundle.events),
        trigger_matches=trigger_layer.matches,
        trigger_overlap=trigger_layer.overlap.value,
        adjustment=trigger_layer.adjustment,
        refusals=refusals,
        user_facing_summary=_summary(mode, scan, trigger_layer, refusals),
    )
    store.append(run)
    store.append(
        bundle.case.model_copy(
            update={
                "status": transition(bundle.case.status, CaseEvent.ANALYSIS_PERSISTED)
            }
        )
    )
    return AnalysisResult(
        run=run,
        safety=scan,
        served_prior=False,
        recommendation=recommendation,
        need_to_act=_need_to_act_now(bundle.case, scan.crisis),
    )


def _run_model_passes(
    store: CaseStore, bundle: CaseBundle, passes: PassSet
) -> tuple[CaseBundle, list[Refusal]]:
    """Run the four model passes, persist their output, and reload so
    pass output participates downstream (annotation attachment is append
    + reload — reconcile() is bookkeeping, not judgment, I10).

    Latency: the three builder passes are independent reads of the same
    pre-pass evidence snapshot, so they run CONCURRENTLY; wall time drops
    from the sum of the passes to max(builders) + adversary. The
    adversary runs AFTER an append+reload so it sees the hypotheses
    minted this run. Store appends stay on the main thread and happen in
    the fixed builder order — the append-only JSONL store is not proven
    thread-safe, and the stream must stay deterministic."""
    refusals: list[Refusal] = []
    builders = (passes.separator, passes.unknowns, passes.hypotheses)
    with ThreadPoolExecutor(max_workers=len(builders)) as pool:
        futures = [pool.submit(_run_pass_fail_closed, p, bundle) for p in builders]
        outputs = [future.result() for future in futures]
    for output in outputs:
        refusals.extend(output.refusals)
        _persist_pass_output(store, output)
    reloaded = store.load_case(bundle.case.id)
    adversary_output = _run_pass_fail_closed(passes.adversary, reloaded)
    refusals.extend(adversary_output.refusals)
    _persist_pass_output(store, adversary_output)
    return store.load_case(bundle.case.id), refusals


def _run_pass_fail_closed(
    model_pass: SeparatorPass | UnknownsPass | HypothesisPass | AdversaryPass,
    bundle: CaseBundle,
) -> PassOutput:
    """One pass, fail closed: an unexpected exception is logged in full
    and becomes that pass's visible refusal — one broken provider must
    never crash the run or discard the sibling passes' completed work.
    StoreError re-raises untouched (module never-suppress rule: a failed
    write aborts the run loudly; passes themselves never touch the store)."""
    try:
        return model_pass.run(bundle)
    except StoreError:
        raise
    except Exception as exc:  # noqa: BLE001 — WHY broad: any pass crash
        # must degrade to a refusal, exactly like a ModelCallError would.
        name = getattr(model_pass, "pass_name", type(model_pass).__name__)
        LOGGER.exception("Pass %s raised; recording a refusal", name)
        return PassOutput(
            refusals=[
                Refusal(
                    pass_name=name,
                    reason=f"Pass raised {type(exc).__name__}: {exc}",
                )
            ]
        )


def _persist_pass_output(store: CaseStore, output: PassOutput) -> None:
    """Serial, main-thread persistence of one pass's records (append
    order within a pass is the contract order: observations,
    interpretations, unknowns, hypotheses — unchanged)."""
    for record in (
        output.observations
        + output.interpretations
        + output.unknowns
        + output.hypotheses
    ):
        store.append(record)


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


def _escalate(
    store: CaseStore,
    case_id: str,
    scan: SafetyScanResult,
    trigger_layer: TriggerLayerResult,
) -> SafetyScanResult:
    """R2: a danger-shaped family match raises safety flags — it may add
    urgency, never terminate as psychology. The escalation is persisted
    like any other safety event; a failed write aborts the run."""
    if not trigger_layer.safety_flags:
        return scan
    store.append(
        SafetyEvent(case_id=case_id, flags=trigger_layer.safety_flags, crisis=True)
    )
    return SafetyScanResult(
        flags=[*scan.flags, *trigger_layer.safety_flags],
        crisis=True,
        resources=list(safety.CRISIS_RESOURCES),
        user_facing_message=safety.CRISIS_MESSAGE,
    )


def _need_to_act_now(case: Case, crisis: bool, now: datetime | None = None) -> str:
    """R2: computed from deadlines + safety state ONLY. Trigger overlap
    is an illegal input — structurally, this function has no trigger
    parameter."""
    if crisis:
        return "high"
    moment = now or datetime.now(timezone.utc)
    urgent = any(
        not d.resolved and d.due_at <= moment + NEED_TO_ACT_DEADLINE_WINDOW
        for d in case.deadlines
    )
    return "high" if urgent else "low"


def _overlap_section(trigger_layer: TriggerLayerResult) -> list[str]:
    """Non-crisis overlap display, template-bound (R3/R5/R8)."""
    parts: list[str] = []
    if trigger_layer.matches:
        parts.append(distortion.render_overlap_line(trigger_layer.overlap))
        parts.append(distortion.EVIDENCE_EFFECT_COPY)
        if trigger_layer.adjustment.user_facing_note:
            parts.append(trigger_layer.adjustment.user_facing_note)
        parts.extend(
            distortion.render_low_diagnostic(slug)
            for slug in trigger_layer.low_diagnostic_slugs
        )
        block = distortion.render_distortion_block(
            trigger_layer.overlap, crisis_active=False
        )
        if block:
            parts.append(block)
    elif trigger_layer.families_present and not trigger_layer.unconfirmed_labels:
        # Mirrored invariant (R3): no match is not unexplained activation.
        parts.append(distortion.NO_MATCH_COPY)
    if trigger_layer.unconfirmed_labels:
        parts.append(
            distortion.render_possible_overlap(trigger_layer.unconfirmed_labels)
        )
    return parts


def _summary(
    mode: GateMode,
    scan: SafetyScanResult,
    trigger_layer: TriggerLayerResult,
    refusals: list[Refusal],
) -> str:
    """Template-bound synthesis (v0.2 §2): vetted copy only, safety verdict
    injected verbatim, validated against the banned-phrase floor. While a
    crisis is active the overlap display is demoted below the resources
    and reduced to the precedence line (R2)."""
    parts: list[str] = []
    if scan.crisis:
        parts.append(scan.user_facing_message)
        parts.extend(f"{r.name}: {r.contact}" for r in scan.resources)
        if trigger_layer.overlap is not OverlapLevel.NONE:
            parts.append(distortion.CRISIS_PRECEDENCE_COPY)
    parts.append(loop.mode_message(mode))
    if not scan.crisis:
        parts.extend(_overlap_section(trigger_layer))
    if refusals:
        names = ", ".join(sorted({r.pass_name for r in refusals}))
        parts.append(f"Passes that did not run this analysis: {names}.")
    return loop.validate_copy("\n\n".join(parts))
