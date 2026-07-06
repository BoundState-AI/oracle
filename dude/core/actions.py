#!/usr/bin/env python3
"""
Module: dude.core.actions
Purpose: Prior-free action scoring (spec v0.2 I8/I9; review A3/A9/A10).

No HypothesisWeight exists — scoring never invents a prior over
hypotheses. The base criterion is dominance filtering followed by
minimax regret across live hypotheses. When any live hypothesis carries
catastrophic-to-user harm, the SAFETY-DOMINANT override applies first:
actions unacceptable under a live catastrophic hypothesis are excluded,
and safety-seeking actions are exempt from irreversibility tie-breaking —
robustness hedging never recommends staying in a possibly-dangerous
situation because leaving scores as "irreversible."

The user's emotional state is not an input to anything in this module.

Safety Critical: True — inaction bias here is review A3.
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import logging

from dude.data.actions import ActionEvaluation, ActionOption, ActionRecommendation
from dude.data.enums import HarmClass
from dude.data.hypotheses import Hypothesis

LOGGER = logging.getLogger("dude.core.actions")

# Utility thresholds for the user-facing works/fails view. Bands, not
# false precision: >= WORKS means the action holds up in that world,
# < FAILS means it goes badly there.
WORKS_THRESHOLD = 0.5
FAILS_THRESHOLD = 0.2

CRITERION_BASE = "dominance+minimax_regret"
CRITERION_SAFETY = "safety_dominant"


def recommend(
    case_id: str,
    options: list[ActionOption],
    evaluations: list[ActionEvaluation],
    hypotheses: list[Hypothesis],
) -> ActionRecommendation:
    """Rank actions across live hypotheses with no hidden priors."""
    live = [h for h in hypotheses if h.is_live()]
    if not live:
        raise ValueError("Action scoring requires at least one live hypothesis.")
    evals = {e.action_id: e for e in evaluations}
    missing = [o.id for o in options if o.id not in evals]
    if missing:
        # Never-suppress: an unevaluated action silently dropped would be a
        # fail-open ranking. Refuse instead.
        raise ValueError(f"Actions missing evaluations: {missing}")

    catastrophic = [
        h for h in live if h.harm_class is HarmClass.CATASTROPHIC_TO_USER
    ]
    excluded: dict[str, str] = {}
    candidates = list(options)
    if catastrophic:
        candidates, excluded = _safety_filter(candidates, evals, catastrophic)

    live_ids = [h.id for h in live]
    survivors = _dominance_filter(candidates, evals, live_ids)
    ranked = sorted(
        survivors,
        key=lambda o: (
            _max_regret(o, evals, live_ids, [h.id for h in catastrophic]),
            -_tiebreak(evals[o.id], safety_exempt=bool(catastrophic)),
        ),
    )
    return ActionRecommendation(
        case_id=case_id,
        criterion=CRITERION_SAFETY if catastrophic else CRITERION_BASE,
        safety_dominant_applied=bool(catastrophic),
        ranked_action_ids=[o.id for o in ranked],
        excluded_action_ids=excluded,
        works_under=_threshold_view(ranked, evals, live_ids, above=True),
        fails_under=_threshold_view(ranked, evals, live_ids, above=False),
    )


def _safety_filter(
    options: list[ActionOption],
    evals: dict[str, ActionEvaluation],
    catastrophic: list[Hypothesis],
) -> tuple[list[ActionOption], dict[str, str]]:
    """Exclude actions unacceptable under a live catastrophic hypothesis
    (v0.2 I9). The exclusion reason is user-visible."""
    cat_ids = {h.id: h.title for h in catastrophic}
    kept: list[ActionOption] = []
    excluded: dict[str, str] = {}
    for option in options:
        bad = [hid for hid in evals[option.id].unsafe_under if hid in cat_ids]
        if bad:
            titles = "; ".join(cat_ids[h] for h in bad)
            excluded[option.id] = (
                f"Unacceptable while a catastrophic hypothesis is live: {titles}"
            )
        else:
            kept.append(option)
    if excluded:
        LOGGER.warning(
            "Safety-dominant override excluded %d action(s)", len(excluded)
        )
    return kept, excluded


def _dominance_filter(
    options: list[ActionOption],
    evals: dict[str, ActionEvaluation],
    live_ids: list[str],
) -> list[ActionOption]:
    """Drop strictly dominated actions (worse-or-equal everywhere, worse
    somewhere, on utilities alone)."""

    def dominates(a: str, b: str) -> bool:
        ua, ub = evals[a].utilities, evals[b].utilities
        pairs = [(ua.get(h, 0.0), ub.get(h, 0.0)) for h in live_ids]
        return all(x >= y for x, y in pairs) and any(x > y for x, y in pairs)

    return [
        o
        for o in options
        if not any(dominates(other.id, o.id) for other in options if other.id != o.id)
    ]


def _max_regret(
    option: ActionOption,
    evals: dict[str, ActionEvaluation],
    live_ids: list[str],
    catastrophic_ids: list[str],
) -> float:
    """Minimax-regret key. Under safety dominance, regret in catastrophic
    worlds is weighted double so performance-if-the-bad-story-is-true
    leads the ranking."""
    best = {
        h: max(e.utilities.get(h, 0.0) for e in evals.values()) for h in live_ids
    }
    regrets = []
    for h in live_ids:
        regret = best[h] - evals[option.id].utilities.get(h, 0.0)
        if h in catastrophic_ids:
            regret *= 2.0
        regrets.append(regret)
    return max(regrets)


def _tiebreak(evaluation: ActionEvaluation, safety_exempt: bool) -> float:
    """Secondary key (higher is better): option preservation, information
    gain, low cost. Reversibility participates EXCEPT for safety-seeking
    actions under the override (v0.2 I9) — leaving must not lose the
    tie-break for being irreversible."""
    info = evaluation.information_gain
    mean_info = sum(info.values()) / len(info) if info else 0.0
    costs = (
        evaluation.financial_cost
        + evaluation.social_cost
        + evaluation.legal_risk
        + evaluation.professional_risk
        + evaluation.physical_risk
        + evaluation.emotional_cost
        + evaluation.time_cost
    ) / 7.0
    score = evaluation.option_preservation + mean_info - costs
    exempt_reversibility = safety_exempt and _is_safety_seeking(evaluation)
    if not exempt_reversibility:
        score += evaluation.reversibility
    return score


def _is_safety_seeking(evaluation: ActionEvaluation) -> bool:
    # WHY a marker note instead of a flag on the evaluation: safety_seeking
    # lives on ActionOption (it describes the action, not its scores), but
    # tie-breaking only sees evaluations. The pipeline stamps the note when
    # pairing options with evaluations so this module needs no back-pointer.
    return "safety_seeking" in evaluation.notes


def _threshold_view(
    options: list[ActionOption],
    evals: dict[str, ActionEvaluation],
    live_ids: list[str],
    above: bool,
) -> dict[str, list[str]]:
    view: dict[str, list[str]] = {}
    for option in options:
        utilities = evals[option.id].utilities
        if above:
            hits = [h for h in live_ids if utilities.get(h, 0.0) >= WORKS_THRESHOLD]
        else:
            hits = [h for h in live_ids if utilities.get(h, 0.0) < FAILS_THRESHOLD]
        view[option.id] = hits
    return view
