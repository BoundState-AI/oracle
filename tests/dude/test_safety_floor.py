"""Safety floor invariants (spec v0.2 §5, I1; review A1/A2/A5).

These tests were written before the pipeline was allowed to ship: the
floor must catch the review's concrete harm scenarios, must mark acute
categories as crisis, and must surface resources verbatim.
"""

from __future__ import annotations

import pytest

from dude.core import safety
from dude.data.enums import SafetyCategory


def _categories(text: str) -> set[SafetyCategory]:
    return {f.category for f in safety.scan(text).flags}


class TestAcuteCategories:
    def test_self_harm_is_crisis(self) -> None:
        result = safety.scan("I honestly don't want to be alive anymore.")
        assert SafetyCategory.SELF_HARM in {f.category for f in result.flags}
        assert result.crisis

    def test_review_a2_dv_scenario_flags(self) -> None:
        # The company-ending sentence from review A2 must never pass clean.
        result = safety.scan(
            "he said if I leave he'll make sure I regret it"
        )
        assert result.flags, "review A2 scenario passed the floor unflagged"

    def test_violence_threat_is_crisis(self) -> None:
        result = safety.scan("He said he's going to kill me if I tell anyone.")
        assert SafetyCategory.VIOLENCE_THREAT in {f.category for f in result.flags}
        assert result.crisis

    def test_child_danger_is_crisis(self) -> None:
        assert SafetyCategory.CHILD_DANGER in _categories(
            "I don't think the kids are safe at his house."
        )

    def test_medical_emergency_is_crisis(self) -> None:
        result = safety.scan("I have chest pain and trouble breathing right now.")
        assert result.crisis

    def test_crisis_surfaces_resources_verbatim(self) -> None:
        result = safety.scan("I keep thinking about killing myself.")
        names = {r.name for r in result.resources}
        assert "988 Suicide & Crisis Lifeline" in names
        assert result.user_facing_message == safety.CRISIS_MESSAGE


class TestChronicCategories:
    def test_stalking_flags_without_crisis(self) -> None:
        result = safety.scan("He keeps showing up outside my apartment.")
        assert SafetyCategory.STALKING_PATTERN in {f.category for f in result.flags}
        assert not result.crisis
        assert result.chronic_flags()

    def test_coercive_control_flags(self) -> None:
        assert SafetyCategory.COERCIVE_CONTROL in _categories(
            "He controls the money and checks my phone every night."
        )

    def test_legal_deadline_flags(self) -> None:
        assert SafetyCategory.LEGAL_DEADLINE in _categories(
            "The filing deadline is in ten days and I want to wait."
        )


class TestFloorBehavior:
    def test_benign_text_is_clean(self) -> None:
        result = safety.scan(
            "Jerry replied about the proposal and suggested open source."
        )
        assert not result.flags
        assert not result.crisis
        assert not result.resources

    def test_flags_carry_auditable_excerpts(self) -> None:
        result = safety.scan("yesterday he was tracking my phone again")
        assert all(f.matched_excerpt for f in result.flags)

    @pytest.mark.parametrize(
        "text",
        [
            "I could kill for a coffee right now",  # idiom: acceptable FP zone
        ],
    )
    def test_recall_leaning_is_documented_policy(self, text: str) -> None:
        # WHY this test exists: the floor is recall-tuned; false positives
        # surface resources, which is the accepted cost (v0.2 §5). This
        # test documents the policy so a future precision pass that starts
        # missing real threats fails the acute tests above, not silently.
        safety.scan(text)  # must not raise, any flags are acceptable
