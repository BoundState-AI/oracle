"""Action-engine invariants (spec v0.2 I8/I9; review A3/A9/A10).

The Case-D scenario is the load-bearing test here: with a live
catastrophic hypothesis, leaving must not lose to staying because
leaving is irreversible.
"""

from __future__ import annotations

import pytest

from dude.core import actions as engine
from dude.data import ConfidenceBand, HarmClass, Hypothesis
from dude.data.actions import ActionEvaluation, ActionOption


def _hypothesis(title: str, harm: HarmClass, band=ConfidenceBand.PLAUSIBLE) -> Hypothesis:
    return Hypothesis(
        case_id="c", title=title, description=title, harm_class=harm, band=band
    )


class TestCaseDOverride:
    """Review A3: the abuse scenario, mechanized."""

    def _setup(self):
        abuse = _hypothesis("Partner is abusive", HarmClass.CATASTROPHIC_TO_USER)
        benign = _hypothesis("Rough patch, no abuse", HarmClass.NONE)
        leave = ActionOption(
            case_id="c",
            title="Leave and stay with family",
            description="",
            safety_seeking=True,
        )
        stay = ActionOption(
            case_id="c", title="Wait and gather more evidence", description="",
            is_no_action=True,
        )
        evals = [
            ActionEvaluation(
                action_id=leave.id,
                utilities={abuse.id: 0.9, benign.id: 0.4},
                reversibility=0.1,  # leaving is irreversible
                option_preservation=0.3,
                notes=["safety_seeking"],
            ),
            ActionEvaluation(
                action_id=stay.id,
                utilities={abuse.id: 0.1, benign.id: 0.8},
                unsafe_under=[abuse.id],
                reversibility=1.0,  # staying is maximally "reversible"
                option_preservation=0.9,
            ),
        ]
        return abuse, benign, leave, stay, evals

    def test_staying_is_excluded_while_abuse_hypothesis_live(self) -> None:
        abuse, benign, leave, stay, evals = self._setup()
        rec = engine.recommend("c", [leave, stay], evals, [abuse, benign])
        assert rec.safety_dominant_applied
        assert rec.criterion == engine.CRITERION_SAFETY
        assert stay.id in rec.excluded_action_ids
        assert rec.ranked_action_ids[0] == leave.id

    def test_contradicted_catastrophic_hypothesis_releases_override(self) -> None:
        abuse, benign, leave, stay, evals = self._setup()
        abuse_dead = abuse.model_copy(update={"band": ConfidenceBand.CONTRADICTED})
        rec = engine.recommend("c", [leave, stay], evals, [abuse_dead, benign])
        assert not rec.safety_dominant_applied
        assert stay.id not in rec.excluded_action_ids


class TestPriorFreeScoring:
    def test_no_hypothesis_weight_exists_anywhere(self) -> None:
        """Review A9: no hidden priors — the field must not exist."""
        assert "HypothesisWeight" not in dir(engine)
        assert "hypothesisWeight" not in ActionEvaluation.model_fields
        assert "hypothesis_weight" not in ActionEvaluation.model_fields

    def test_no_emotional_impulse_penalty_exists(self) -> None:
        """Review A10: the user's emotional state is never a scoring input."""
        fields = set(ActionEvaluation.model_fields)
        assert "impulse_contamination" not in fields
        assert "emotional_impulse_penalty" not in fields

    def test_dominated_action_never_ranks_first(self) -> None:
        h1 = _hypothesis("H1", HarmClass.NONE)
        h2 = _hypothesis("H2", HarmClass.NONE)
        good = ActionOption(case_id="c", title="good", description="")
        worse = ActionOption(case_id="c", title="strictly worse", description="")
        evals = [
            ActionEvaluation(action_id=good.id, utilities={h1.id: 0.8, h2.id: 0.7}),
            ActionEvaluation(action_id=worse.id, utilities={h1.id: 0.5, h2.id: 0.4}),
        ]
        rec = engine.recommend("c", [good, worse], evals, [h1, h2])
        assert rec.ranked_action_ids[0] == good.id
        assert worse.id not in rec.ranked_action_ids  # dominance-filtered

    def test_missing_evaluation_refuses_instead_of_dropping(self) -> None:
        h1 = _hypothesis("H1", HarmClass.NONE)
        option = ActionOption(case_id="c", title="unevaluated", description="")
        with pytest.raises(ValueError, match="missing evaluations"):
            engine.recommend("c", [option], [], [h1])

    def test_no_live_hypothesis_refuses(self) -> None:
        dead = _hypothesis("H", HarmClass.NONE, band=ConfidenceBand.CONTRADICTED)
        option = ActionOption(case_id="c", title="a", description="")
        evaluation = ActionEvaluation(action_id=option.id)
        with pytest.raises(ValueError, match="live hypothesis"):
            engine.recommend("c", [option], [evaluation], [dead])

    def test_works_and_fails_views_are_banded(self) -> None:
        h1 = _hypothesis("H1", HarmClass.NONE)
        h2 = _hypothesis("H2", HarmClass.NONE)
        option = ActionOption(case_id="c", title="a", description="")
        evaluation = ActionEvaluation(
            action_id=option.id, utilities={h1.id: 0.9, h2.id: 0.1}
        )
        rec = engine.recommend("c", [option], [evaluation], [h1, h2])
        assert rec.works_under[option.id] == [h1.id]
        assert rec.fails_under[option.id] == [h2.id]
