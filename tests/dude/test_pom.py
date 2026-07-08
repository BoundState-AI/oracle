"""POM subsystem invariants — the named tests from the build instruction
(§16) plus model-lag coverage. The final principle under test: DUDE may
know Joseph deeply; knowing Joseph may never determine what happened in
the external world.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dude.core.loop import validate_copy
from dude.data import Case, ConfidenceBand
from dude.pipeline.engine import analyze, capture
from dude.pom.contracts import (
    AllowedUse,
    EpistemicStatus,
    GroundingCoordinate,
    ModelComponent,
    PomCategory,
    PomItem,
    SourceArtifact,
    Temporal,
    WorkingModel,
)
from dude.pom.pipeline import confirm_item, ingest_source, retrieve
from dude.pom.policy import (
    LagStatus,
    PolicyViolation,
    authorize,
    lag_summary,
    model_lag_check,
    surface_grounding,
)
from dude.pom.store import PomStore
from dude.store.jsonl import CaseStore

USER = "joseph"


def _item(**overrides) -> PomItem:
    base = dict(
        user_id=USER,
        source_artifact_id="src1",
        source_excerpt="…from the manual…",
        category=PomCategory.TRIGGER_PATTERN,
        statement="Ambiguity from powerful people is a high-sensitivity pattern",
        epistemic_status=EpistemicStatus.USER_STATED_FACT,
        allowed_uses=[AllowedUse.TRIGGER_CONTEXT, AllowedUse.UNCERTAINTY_WIDENING],
    )
    base.update(overrides)
    return PomItem(**base)


@pytest.fixture()
def pom(tmp_path) -> PomStore:
    return PomStore(CaseStore(root=tmp_path / "dude_home"))


class TestEpistemicDiscipline:
    def test_assistant_interpretation_never_becomes_user_fact(self) -> None:
        with pytest.raises(ValueError, match="cannot be user_confirmed"):
            _item(
                epistemic_status=EpistemicStatus.ASSISTANT_INTERPRETATION,
                user_confirmed=True,
            )

    def test_user_confirmed_item_requires_supersede_not_overwrite(self, pom) -> None:
        original = _item(epistemic_status=EpistemicStatus.WORKING_HYPOTHESIS)
        pom.append(original)
        promoted = confirm_item(pom, original)
        assert promoted.supersedes == original.id
        assert promoted.epistemic_status is EpistemicStatus.USER_CONFIRMED_PATTERN
        loaded = pom.load().items
        assert [i.id for i in loaded] == [promoted.id]  # chain resolved
        # The original record still exists on disk (append-only), it is
        # merely superseded — nothing was overwritten.
        raw = (pom._dir / "items.jsonl").read_text()  # noqa: SLF001
        assert original.id in raw

    def test_source_artifact_is_immutable(self, pom) -> None:
        first = ingest_source(pom, USER, "Joseph Operating Manual v1", "content A")
        second = ingest_source(pom, USER, "Joseph Operating Manual v1", "content B")
        assert second.supersedes == first.id
        assert first.content_sha256 != second.content_sha256
        raw = (pom._dir / "source_artifacts.jsonl").read_text()  # noqa: SLF001
        assert "content A" in raw and "content B" in raw
        with pytest.raises(ValueError, match="does not match"):
            SourceArtifact(
                user_id=USER, title="t", content="x", content_sha256="tampered"
            )


class TestBiographyIsNeverEvidence:
    PTSD_ITEM_KWARGS = dict(
        category=PomCategory.IDENTITY,
        statement="Joseph reports diagnosed PTSD following severe childhood trauma",
        epistemic_status=EpistemicStatus.USER_STATED_FACT,
        allowed_uses=[
            AllowedUse.TRIGGER_CONTEXT,
            AllowedUse.COMMUNICATION_ADAPTATION,
            AllowedUse.UNCERTAINTY_WIDENING,
            AllowedUse.GROUNDING,
        ],
    )

    def test_ptsd_history_cannot_discount_observation(self) -> None:
        item = _item(**self.PTSD_ITEM_KWARGS)
        with pytest.raises(PolicyViolation, match="constitutionally prohibited"):
            authorize(item, "discount_current_observation")

    def test_prior_accurate_threat_detection_cannot_validate_new_threat(self) -> None:
        item = _item(
            statement="Joseph has accurately detected institutional danger before",
            epistemic_status=EpistemicStatus.USER_CONFIRMED_PATTERN,
            user_confirmed=True,
        )
        for use in ("infer_current_threat_true", "support_current_hypothesis"):
            with pytest.raises(PolicyViolation, match="constitutionally prohibited"):
                authorize(item, use)

    def test_trigger_match_never_supports_current_hypothesis(self, pom) -> None:
        pom.append(_item())
        with pytest.raises(PolicyViolation, match="prohibited"):
            retrieve(
                pom,
                case_id="case1",
                analysis_run_id="run1",
                use="support_current_hypothesis",
                cues=["powerful"],
                reason="attempted misuse",
            )

    def test_trigger_match_never_contradicts_current_hypothesis(self, pom) -> None:
        pom.append(_item())
        with pytest.raises(PolicyViolation, match="prohibited"):
            retrieve(
                pom,
                case_id="case1",
                analysis_run_id="run1",
                use="contradict_current_hypothesis",
                cues=["powerful"],
                reason="attempted misuse",
            )

    def test_trigger_match_never_moves_hypothesis_bands_in_engine(
        self, store, case
    ) -> None:
        """Structural end-to-end: an analysis with trigger matches leaves
        hypothesis bands exactly as the hypotheses state them."""
        from dude.data import Hypothesis, TriggerPattern

        store.append_trigger(
            TriggerPattern(
                name="institutional silence",
                cues=["institutional silence"],
                user_confirmed=True,
                active=True,
            )
        )
        hypothesis = Hypothesis(
            case_id=case.id,
            title="H",
            description="d",
            band=ConfidenceBand.PLAUSIBLE,
        )
        store.append(hypothesis)
        capture(store, case.id, "weeks of institutional silence again")
        result = analyze(store, case.id)
        assert result.run.trigger_matches  # the trigger fired
        assert result.run.hypothesis_bands[hypothesis.lineage_id] is (
            ConfidenceBand.PLAUSIBLE
        )

    def test_historical_case_never_corrobates_new_case(self, pom) -> None:
        herald = _item(
            category=PomCategory.HISTORICAL_CASE_CONTEXT,
            statement="Herald behaved opaquely in the MIRA case",
            epistemic_status=EpistemicStatus.USER_REPORTED_EVENT,
            case_ref="mira",
            allowed_uses=[AllowedUse.CASE_RETRIEVAL, AllowedUse.UNCERTAINTY_WIDENING],
        )
        pom.append(herald)
        with pytest.raises(PolicyViolation, match="prohibited"):
            authorize(herald, "cross_case_corroboration")
        # Even with an allowed use, historical case context only surfaces
        # via explicit case retrieval — never as ambient context.
        ambient = retrieve(
            pom,
            case_id="jacksonville",
            analysis_run_id="run1",
            use=AllowedUse.UNCERTAINTY_WIDENING,
            cues=["herald"],
            reason="ambient",
        )
        assert ambient == []
        explicit = retrieve(
            pom,
            case_id="jacksonville",
            analysis_run_id="run1",
            use=AllowedUse.CASE_RETRIEVAL,
            cues=["herald"],
            reason="user asked for prior cases",
        )
        assert [i.id for i in explicit] == [herald.id]

    def test_semantic_similarity_is_not_evidence(self, pom) -> None:
        """Candidates are candidates: nothing reaches context without an
        allowed use, and matching strength grants no evidence status."""
        pom.append(_item(allowed_uses=[]))  # matches cues, allows nothing
        result = retrieve(
            pom,
            case_id="c",
            analysis_run_id="r",
            use=AllowedUse.TRIGGER_CONTEXT,
            cues=["powerful people"],
            reason="match",
        )
        assert result == []  # similarity alone retrieved nothing


class TestTemporalAndGrounding:
    def test_stale_financial_values_not_current_truth(self) -> None:
        snapshot = _item(
            category=PomCategory.STRATEGIC_CONTEXT,
            statement="Retirement account balance was $X in 2025",
            temporal=Temporal.HISTORICAL,
            allowed_uses=[AllowedUse.STRATEGIC_CONTEXT],
        )
        with pytest.raises(PolicyViolation, match="historical/stale"):
            authorize(snapshot, AllowedUse.STRATEGIC_CONTEXT)
        expired = _item(
            statement="Active application: Jacksonville Navy job",
            temporal=Temporal.WINDOWED,
            valid_to=datetime.now(timezone.utc) - timedelta(days=1),
            allowed_uses=[AllowedUse.STRATEGIC_CONTEXT],
        )
        with pytest.raises(PolicyViolation, match="window expired"):
            authorize(expired, AllowedUse.STRATEGIC_CONTEXT)

    def test_grounding_phrase_requires_allowed_context(self) -> None:
        coordinate = GroundingCoordinate(
            user_id=USER,
            phrase="The boys are not barefoot in the snow.",
            meaning="Present-safety orientation for family-threat activation",
            activation_contexts=["family_safety_activation"],
            contraindications=["active_emergency"],
            user_confirmed=True,
            active=True,
        )
        assert (
            surface_grounding(coordinate, "family_safety_activation")
            == coordinate.phrase
        )
        with pytest.raises(PolicyViolation, match="not an allowed activation"):
            surface_grounding(coordinate, "workplace_ambiguity")
        with pytest.raises(PolicyViolation, match="contraindicated"):
            surface_grounding(coordinate, "active_emergency")


class TestRetrievalAudit:
    def test_every_retrieved_pom_item_has_audit_record(self, pom) -> None:
        item = _item()
        pom.append(item)
        retrieved = retrieve(
            pom,
            case_id="case1",
            analysis_run_id="run1",
            use=AllowedUse.TRIGGER_CONTEXT,
            cues=["powerful"],
            reason="trigger overlap context for run1",
        )
        assert [i.id for i in retrieved] == [item.id]
        audits = pom.load().retrievals
        assert len(audits) == 1
        assert audits[0].pom_item_id == item.id
        assert audits[0].case_id == "case1"
        assert audits[0].retrieval_reason == "trigger overlap context for run1"


class TestModelLag:
    """Model lag: the internal predictive model may still be optimized for
    a world state that no longer fully exists. Not 'cognitive distortion',
    not 'irrational thought' — and the copy never says either."""

    def _model(self) -> WorkingModel:
        return WorkingModel(
            user_id=USER,
            name="powerful institutions can trap me with no recourse",
            description="threat model formed under real childhood danger",
            historical_basis=["childhood abuse", "narrative rewriting"],
            adaptive_when="childhood household; early institutional career",
            components=[
                ModelComponent(
                    name="institutional coordination",
                    currently_supporting=["professional cooling", "unexplained silence"],
                    currently_contradicting=[],
                ),
                ModelComponent(
                    name="trapped with no exit",
                    currently_supporting=[],
                    currently_contradicting=[
                        "independent employment paths exist",
                        "not financially trapped",
                        "NASA Legal responded promptly",
                    ],
                ),
            ],
        )

    def test_per_component_verdicts(self) -> None:
        verdicts = {v.component: v.status for v in model_lag_check(self._model())}
        assert verdicts["institutional coordination"] is LagStatus.SUPPORTED
        assert verdicts["trapped with no exit"] is LagStatus.APPEARS_STALE

    def test_summary_is_evidence_state_language(self) -> None:
        model = self._model()
        summary = lag_summary(model, model_lag_check(model))
        validate_copy(summary)  # banned-phrase floor
        assert "remain supported" in summary
        assert "appears stale" in summary
        # Never a truth verdict on the person:
        assert "false" not in summary.lower()
        assert "wrong" not in summary.lower()

    def test_historical_basis_is_context_not_a_vote(self) -> None:
        """A component with no CURRENT evidence is unresolved, no matter
        how strong the historical basis was."""
        model = WorkingModel(
            user_id=USER,
            name="m",
            description="d",
            historical_basis=["decades of real events"],
            components=[ModelComponent(name="only history")],
        )
        [verdict] = model_lag_check(model)
        assert verdict.status is LagStatus.UNRESOLVED


class TestBundledImportIdempotence:
    def test_bundled_import_runs_twice_without_duplicates(self, tmp_path) -> None:
        """Production regression: id-based dedupe re-imported all items on
        every boot (1980 after 11 deploys), then the content-keyed fix
        crashed the boot on a stale variable in the return path. This
        exercises the FULL function twice, return value included."""
        from dude.api.app import import_bundled_pom
        from dude.store.jsonl import CaseStore

        store = CaseStore(root=tmp_path / "dude_home")
        first = import_bundled_pom(store)
        assert first is not None and first["items_imported"] > 0
        second = import_bundled_pom(store)
        assert second["items_imported"] == 0
        assert second["items_total"] == first["items_total"]
