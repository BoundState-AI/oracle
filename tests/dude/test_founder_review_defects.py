"""Named tests from the founder's first-production-output review.

Five defects were called; each gets a machine-checked guard here so
none can regress silently.
"""

from __future__ import annotations

import json

from dude.core import conduct
from dude.data import CreatedBy, Event
from dude.data.enums import AccessLevel, Pursuit
from dude.pipeline.live_passes import (
    HYPOTHESES_RULES,
    SEPARATOR_RULES,
    UNKNOWNS_RULES,
    LiveUnknowns,
)
from tests.dude.test_live_passes import FakeChat, _bundle


class TestDefect1_DuplicationIsNotEvidence:
    def test_duplicate_extraction_is_not_repeated_evidence(self) -> None:
        """Repeated extraction of the same incident accrues nothing:
        machine-extracted events are unconfirmed, and only user-confirmed
        events feed course-of-conduct accrual. duplicate_claim_count is
        structurally decoupled from evidence_weight."""
        duplicates = [
            Event(
                case_id="c",
                description="Gabig emailed about business development",
                pattern_class="unexplained_contact",
                created_by=CreatedBy.MODEL_STUB,
                user_confirmed=False,
            )
            for _ in range(5)
        ]
        assert conduct.accrue(duplicates) == []


class TestDefect2_UserFactNotDegraded:
    def test_explicit_user_fact_not_degraded_by_ambiguous_supporting_quote(
        self,
    ) -> None:
        """The separator contract forbids demoting an explicit user
        assertion because an embedded quote is lexically ambiguous
        (production case: 'Tawyna knows Seemann' demoted to a which-Jerry
        unknown). The rule is part of the pass prompt contract."""
        assert "Never weaken" in SEPARATOR_RULES
        assert "demotion of the assertion" in SEPARATOR_RULES


class TestDefect3_UnknownsAreNotTasks:
    def test_low_access_unknowns_are_never_chased(self, tmp_path) -> None:
        """Machine-enforced clamp: an unknown the user cannot legitimately
        answer is DO_NOT_CHASE no matter what the model recommends.
        Uncertainty never becomes surveillance."""
        reply = json.dumps(
            {
                "unknowns": [
                    {
                        "statement": "Whether Seemann's sent folder shows contact",
                        "importance": "high",
                        "user_access": "low",
                        "pursuit": "pursue",  # the model tries to chase
                    },
                    {
                        "statement": "Full headers of the user's own emails",
                        "importance": "high",
                        "user_access": "high",
                        "pursuit": "pursue",
                    },
                ]
            }
        )
        _store, bundle = _bundle(tmp_path)
        output = LiveUnknowns(FakeChat("anthropic", [reply])).run(bundle)
        by_access = {u.user_access: u.pursuit for u in output.unknowns}
        assert by_access[AccessLevel.LOW] is Pursuit.DO_NOT_CHASE  # clamped
        assert by_access[AccessLevel.HIGH] is Pursuit.PURSUE  # legitimate

    def test_unknown_is_not_automatically_a_task_is_contractual(self) -> None:
        assert "not automatically a task" in UNKNOWNS_RULES
        assert "surveillance" in UNKNOWNS_RULES


class TestDefects4And5_HypothesisHygiene:
    def test_safety_state_is_not_a_causal_hypothesis(self) -> None:
        assert "Safety state is not a causal hypothesis" in HYPOTHESES_RULES

    def test_titles_are_propositions_not_verdicts(self) -> None:
        assert "never verdicts" in HYPOTHESES_RULES
        assert "Decompose compound claims" in HYPOTHESES_RULES
