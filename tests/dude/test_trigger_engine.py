"""Trigger Calibration Engine — seed data, raw-data rules, matched
pairs, status discipline, migration, store, and distortion vocabulary
(trigger spec v1 §2-§4/§11-§13; v1.1 R3/R4/R6/R7/R9).

Structure tests run against the seed data parsed from the git-excluded
local source (v1 §12 family-structure tests are seed-data tests by
design). No monkeypatching; models are injected."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dude.core.loop import validate_copy
from dude.data.enums import TriggerCalibration
from dude.data.triggers import TriggerPattern
from dude.pom.contracts import EpistemicStatus
from dude.store.jsonl import CaseStore
from dude.triggers import distortion, seed, status
from dude.triggers.contracts import (
    CaptureState,
    EvidenceSourceType,
    FeatureType,
    PersonalTriggerProfile,
    SupportDirection,
    TriggerCalibrationResponse,
    TriggerEvidence,
    TriggerFamily,
    TriggerFamilyStatus,
)
from dude.triggers.migrate import migrate_legacy
from dude.triggers.seed import import_seed
from dude.triggers.store import TriggerStore

pytestmark = pytest.mark.skipif(
    not seed.LOCAL_SOURCE.exists(),
    reason="git-excluded local calibration source not present",
)

USER = "joseph"
NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture()
def tstore(store: CaseStore) -> TriggerStore:
    trigger_store = TriggerStore(store)
    import_seed(trigger_store, user_id=USER)
    return trigger_store


def _responses_for(bundle, family_slug):
    prompt_ids = {p.id for p in bundle.prompts if p.family_slug == family_slug}
    return [r for r in bundle.calibration if r.prompt_id in prompt_ids]


def _contrast_for(bundle, family_slug):
    contrasts = [c for c in bundle.contrasts if c.family_slug == family_slug]
    assert contrasts, f"no pair contrast seeded for {family_slug}"
    return contrasts[0]


def _profile_for(bundle, family_slug):
    profile = bundle.profile_for_family(USER, family_slug)
    assert profile is not None
    return profile


def _response(
    prompt_id: str,
    session_id: str,
    raw: int,
    at: datetime,
    scale=(0, 5),
    crisis: bool = False,
) -> TriggerCalibrationResponse:
    return TriggerCalibrationResponse(
        user_id=USER,
        prompt_id=prompt_id,
        session_id=session_id,
        raw_score=raw,
        declared_scale_min=scale[0],
        declared_scale_max=scale[1],
        raw_response_text=f"scenario rated {raw}",
        state_at_capture=CaptureState(crisis_flag_active=crisis),
        timestamp=at,
    )


def _evidence(family, source, epistemic, direction) -> TriggerEvidence:
    return TriggerEvidence(
        user_id=USER,
        trigger_family_id=family.id,
        family_slug=family.slug,
        source_type=source,
        epistemic_status=epistemic,
        support_direction=direction,
    )


class TestSeededFamilyStructure:
    """v1 §12 family-structure tests, against the parsed seed data."""

    def test_power_changes_false_motive_activation(self, tstore) -> None:
        """§2/§3.A: the no-power arm scored cold, the power arm hot —
        the mechanism is powered false attribution, not misunderstanding."""
        bundle = tstore.load()
        contrast = _contrast_for(bundle, "consequential_false_motive_attribution")
        assert contrast.contrast_supported
        by_id = {r.id: r for r in bundle.calibration}
        assert by_id[contrast.low_response_id].raw_score == 1
        assert by_id[contrast.high_response_id].raw_score == 5
        # The inferred mechanism stays a working hypothesis, never a fact.
        assert contrast.inferred_mechanism_slug is not None
        assert contrast.epistemic_status is EpistemicStatus.WORKING_HYPOTHESIS

    def test_generic_misunderstanding_not_promoted_from_powered_false_attribution(
        self, tstore
    ) -> None:
        """§4: the broad theory stays low-support even though the narrow
        powered mechanism is self-report supported."""
        bundle = tstore.load()
        broad = _profile_for(bundle, "generic_misunderstanding")
        narrow = _profile_for(bundle, "consequential_false_motive_attribution")
        assert broad.status is TriggerFamilyStatus.CANDIDATE_WITH_LOW_SUPPORT
        assert narrow.status is TriggerFamilyStatus.SELF_REPORT_SUPPORTED

    def test_visibility_to_power_separate_from_success(self, tstore) -> None:
        """§3.G: success while invisible scored 0; visibility scored 5."""
        bundle = tstore.load()
        contrast = _contrast_for(bundle, "visibility_to_power")
        assert contrast.contrast_supported
        assert contrast.low_effective == 0
        assert contrast.high_effective == 5
        family = bundle.families_by_slug()["visibility_to_power"]
        exclusion = family.feature_by_slug("anonymous_success")
        assert exclusion is not None
        assert exclusion.feature_type is FeatureType.EXCLUSION

    def test_old_event_discussion_separate_from_identity_foreclosure(
        self, tstore
    ) -> None:
        """§3.B: private factual discussion (1) vs identity proof (5)."""
        bundle = tstore.load()
        contrast = _contrast_for(bundle, "historical_event_used_as_fixed_identity")
        assert contrast.contrast_supported
        family = bundle.families_by_slug()["historical_event_used_as_fixed_identity"]
        exclusion = family.feature_by_slug("private_factual_discussion")
        assert exclusion is not None
        assert exclusion.feature_type is FeatureType.EXCLUSION

    def test_child_threat_independent_of_blocked_access(self, tstore) -> None:
        """§3.F: child danger alone scored 4 — hot WITHOUT the blocked
        amplifier; the F pair contrast is deliberately unsupported."""
        bundle = tstore.load()
        prompts = {p.prompt_slug: p for p in bundle.prompts}
        responses = {r.prompt_id: r for r in bundle.calibration}
        full_access = responses[prompts["f_full_access"].id]
        assert full_access.raw_score == 4
        contrast = _contrast_for(bundle, "dependent_in_danger")
        assert not contrast.contrast_supported
        assert contrast.inferred_mechanism_slug is None

    def test_blocked_protective_access_is_amplifier(self, tstore) -> None:
        bundle = tstore.load()
        family = bundle.families_by_slug()["dependent_in_danger"]
        feature = family.feature_by_slug("blocked_protective_access")
        assert feature is not None
        assert feature.feature_type is FeatureType.AMPLIFIER

    def test_legible_authority_separate_from_arbitrary_power(self, tstore) -> None:
        """§3.E: legible bounded authority scored ZERO; arbitrary opaque
        discretion is the mechanism. The zero arm is a passed control."""
        bundle = tstore.load()
        contrast = _contrast_for(bundle, "arbitrary_power_without_legible_recourse")
        assert contrast.contrast_supported
        assert contrast.low_effective == 0
        family_prompts = [
            p
            for p in bundle.prompts
            if p.family_slug == "arbitrary_power_without_legible_recourse"
        ]
        assert status.passed_negative_controls(
            _responses_for(bundle, "arbitrary_power_without_legible_recourse"),
            family_prompts,
        ) >= 1

    def test_constrained_exit_supports_physical_and_consequential_subtypes(
        self, tstore
    ) -> None:
        bundle = tstore.load()
        family = bundle.families_by_slug()["constrained_exit"]
        slugs = {f.feature_slug for f in family.features}
        assert "physical_exit_constraint" in slugs
        assert "occupational_exit_constraint" in slugs
        assert "financial_exit_constraint" in slugs

    def test_waiting_separate_from_opaque_moving_timeline(self, tstore) -> None:
        """§3.H: waiting itself is activating (3) and opacity amplifies
        (4); the 1-point contrast does NOT license a mechanism inference."""
        bundle = tstore.load()
        family = bundle.families_by_slug()["consequential_suspended_outcome"]
        amplifier = family.feature_by_slug("moving_or_opaque_timeline")
        assert amplifier is not None
        assert amplifier.feature_type is FeatureType.AMPLIFIER
        contrast = _contrast_for(bundle, "consequential_suspended_outcome")
        assert contrast.high_effective == 4
        assert contrast.low_effective == 3
        assert not contrast.contrast_supported
        assert contrast.inferred_mechanism_slug is None

    def test_trigger_origin_not_inferred_from_historical_similarity(
        self, tstore
    ) -> None:
        """§3 preamble + R6a: no family shape asserts a causal origin or
        carries a real-world anchor; the contract refuses anchored shapes."""
        bundle = tstore.load()
        for family in bundle.families:
            text = f"{family.label} {family.description}".lower()
            for token in ("nasa", "akashic", "1994", "childhood", "caused"):
                assert token not in text, (family.slug, token)
        with pytest.raises(ValueError, match="real-world anchors"):
            TriggerFamily(
                slug="anchored",
                label="Anchored",
                description="The 1994 event caused this pattern.",
            )


class TestRawDataRules:
    """v1 §13: the user's raw answer is evidence; normalization never
    overwrites it."""

    def test_raw_scores_preserved_across_scale_versions(self, tstore) -> None:
        bundle = tstore.load()
        round1 = [r for r in bundle.calibration if r.session_id == "round_1"]
        round2 = [r for r in bundle.calibration if r.session_id == "round_2"]
        assert round1 and round2
        assert all(r.declared_scale_max == 4 for r in round1)
        assert all(r.declared_scale_max == 5 for r in round2)
        assert all(r.raw_response_text for r in round1 + round2)

    def test_out_of_range_raw_score_preserved_not_silently_clamped(
        self, tstore
    ) -> None:
        """Round 1 was declared 0-4 with spontaneous 5s: preserved
        verbatim, flagged, marked for re-ask, never counted at face value."""
        bundle = tstore.load()
        spontaneous = [
            r
            for r in bundle.calibration
            if r.session_id == "round_1" and r.raw_score == 5
        ]
        assert spontaneous, "the spontaneous round-1 fives must survive import"
        for response in spontaneous:
            assert response.out_of_range
            assert "Re-ask required" in response.clarification
            assert response.raw_score == 5  # never clamped
            assert response.effective_score() == 4  # derived view only
        assert status.face_value_responses(spontaneous) == []

    def test_out_of_range_flag_is_computed_not_trusted(self) -> None:
        response = TriggerCalibrationResponse(
            user_id=USER,
            prompt_id="p",
            session_id="s",
            raw_score=9,
            declared_scale_min=0,
            declared_scale_max=4,
            out_of_range=False,  # a lying caller is corrected
            raw_response_text="9",
        )
        assert response.out_of_range
        assert response.raw_score == 9

    def test_conflicting_calibration_not_averaged_away(self, tstore) -> None:
        """§3.J: inconsistent intensity across wordings is preserved as
        distinct responses; no aggregate score field exists anywhere."""
        bundle = tstore.load()
        scores = sorted(
            r.raw_score
            for r in _responses_for(
                bundle, "psychiatric_or_character_delegitimization"
            )
        )
        assert scores == [2, 3, 3, 4, 5]
        assert "score" not in PersonalTriggerProfile.model_fields
        assert "average" not in PersonalTriggerProfile.model_fields

    def test_calibration_during_crisis_quarantined(self, tstore) -> None:
        """R6f: crisis-time capture is force-quarantined by the contract
        and excluded from status math."""
        response = _response("p1", "s1", 4, NOW, crisis=True)
        assert response.quarantined
        assert "crisis" in response.quarantine_reason
        assert status.usable_responses([response]) == []


class TestStatusEngine:
    """R4: cap, promote, demote — deterministically."""

    def _candidate(self, tstore) -> PersonalTriggerProfile:
        bundle = tstore.load()
        return _profile_for(bundle, "generic_silence")

    def test_status_demotes_on_contradicting_evidence(self, tstore) -> None:
        bundle = tstore.load()
        family = bundle.families_by_slug()["consequential_false_motive_attribution"]
        profile = _profile_for(bundle, family.slug)
        assert profile.status is TriggerFamilyStatus.SELF_REPORT_SUPPORTED
        contradicting = [
            _evidence(
                family,
                EvidenceSourceType.DIRECT_USER_REPORT,
                EpistemicStatus.USER_STATED_FACT,
                SupportDirection.CONTRADICTS,
            )
            for _ in range(2)
        ]
        decision = status.evaluate(profile, contradicting, [], [])
        assert decision.changed
        assert decision.status is TriggerFamilyStatus.CANDIDATE  # one level
        assert "quorum" in decision.reason  # visible reason
        updated = status.apply_decision(tstore, profile, decision)
        assert updated.supersedes == profile.id
        resolved = tstore.load().profile_for_family(USER, family.slug)
        assert resolved.status is TriggerFamilyStatus.CANDIDATE

    def test_single_contradiction_below_quorum_does_not_demote(self, tstore) -> None:
        bundle = tstore.load()
        family = bundle.families_by_slug()["consequential_false_motive_attribution"]
        profile = _profile_for(bundle, family.slug)
        one = [
            _evidence(
                family,
                EvidenceSourceType.DIRECT_USER_REPORT,
                EpistemicStatus.USER_STATED_FACT,
                SupportDirection.CONTRADICTS,
            )
        ]
        assert not status.evaluate(profile, one, [], []).changed

    def test_single_session_cannot_reach_strongly_supported(self, tstore) -> None:
        """R4: the value strongly_supported does not exist, and one
        session cannot even reach self_report_supported."""
        assert not hasattr(TriggerFamilyStatus, "STRONGLY_SUPPORTED")
        assert "strongly_supported" not in {
            s.value for s in TriggerFamilyStatus
        }
        bundle = tstore.load()
        profile = self._candidate(tstore)
        family = bundle.families_by_slug()[profile.family_slug]
        prompts = [p for p in bundle.prompts if p.family_slug == profile.family_slug]
        # One sitting, even with a passed control and an in-vivo tag.
        responses = [
            _response(prompts[0].id, "one_sitting", 4, NOW + timedelta(minutes=i))
            for i in range(3)
        ]
        in_vivo = [
            _evidence(
                family,
                EvidenceSourceType.IN_VIVO_CONFIRMATION,
                EpistemicStatus.USER_CONFIRMED_PATTERN,
                SupportDirection.SUPPORTS,
            )
        ]
        decision = status.evaluate(profile, in_vivo, responses, prompts)
        assert not decision.changed
        assert decision.status is profile.status

    def test_promotion_requires_separated_sessions_control_and_in_vivo(
        self, tstore
    ) -> None:
        bundle = tstore.load()
        profile = self._candidate(tstore)
        family = bundle.families_by_slug()[profile.family_slug]
        prompts = [p for p in bundle.prompts if p.family_slug == profile.family_slug]
        control = prompts[0].model_copy(
            update={"id": "control_prompt", "is_negative_control": True}
        )
        prompts = [*prompts, control]
        responses = [
            _response(prompts[0].id, "s1", 4, NOW),
            _response(control.id, "s1", 0, NOW),  # passed negative control
            _response(prompts[0].id, "s2", 4, NOW + timedelta(days=3)),
        ]
        in_vivo = [
            _evidence(
                family,
                EvidenceSourceType.IN_VIVO_CONFIRMATION,
                EpistemicStatus.USER_CONFIRMED_PATTERN,
                SupportDirection.SUPPORTS,
            )
        ]
        decision = status.evaluate(profile, in_vivo, responses, prompts)
        assert decision.changed
        assert decision.status is TriggerFamilyStatus.SELF_REPORT_SUPPORTED
        # Without the in-vivo confirmation the same record does not promote.
        assert not status.evaluate(profile, [], responses, prompts).changed

    def test_case_derived_evidence_cannot_raise_match_confidence(
        self, tstore
    ) -> None:
        """R4 no-closed-loop, both layers: the contract refuses a
        supported profile on match-derived evidence alone, and the status
        engine ignores match-derived supports entirely."""
        bundle = tstore.load()
        profile = self._candidate(tstore)
        family = bundle.families_by_slug()[profile.family_slug]
        forged = profile.to_json_dict()
        forged.update(
            status="self_report_supported",
            evidence_source_types=["repeated_case_pattern"],
        )
        with pytest.raises(ValueError, match="closed loop"):
            # model_validate is the store's load path: a forged record
            # cannot even round-trip through persistence.
            PersonalTriggerProfile.model_validate(forged)
        match_derived = [
            _evidence(
                family,
                EvidenceSourceType.REPEATED_CASE_PATTERN,
                EpistemicStatus.WORKING_HYPOTHESIS,
                SupportDirection.SUPPORTS,
            )
            for _ in range(5)
        ]
        assert not status.evaluate(profile, match_derived, [], []).changed

    def test_low_score_candidate_not_promoted_to_core(self, tstore) -> None:
        """§4: low-support candidates stay put on their seeded record."""
        bundle = tstore.load()
        profile = self._candidate(tstore)
        prompts = [p for p in bundle.prompts if p.family_slug == profile.family_slug]
        decision = status.evaluate(
            profile, bundle.evidence, bundle.calibration, prompts
        )
        assert not decision.changed
        assert decision.status is TriggerFamilyStatus.CANDIDATE_WITH_LOW_SUPPORT

    def test_user_retire_always_wins(self, tstore) -> None:
        bundle = tstore.load()
        profile = _profile_for(bundle, "consequential_false_motive_attribution")
        retired = status.retire(tstore, profile, "no longer mine")
        assert retired.status is TriggerFamilyStatus.RETIRED
        assert "Retired by user" in retired.status_reason
        # Nothing the engine computes moves a retired profile.
        decision = status.evaluate(retired, [], [], [])
        assert not decision.changed
        assert decision.status is TriggerFamilyStatus.RETIRED

    def test_assistant_interpretation_not_promoted_to_user_fact(self) -> None:
        with pytest.raises(ValueError, match="never a user fact"):
            TriggerEvidence(
                user_id=USER,
                trigger_family_id="f",
                family_slug="s",
                source_type=EvidenceSourceType.ASSISTANT_HYPOTHESIS,
                epistemic_status=EpistemicStatus.USER_STATED_FACT,
                support_direction=SupportDirection.SUPPORTS,
            )

    def test_quarantined_and_out_of_range_excluded_from_session_math(
        self, tstore
    ) -> None:
        responses = [
            _response("p", "s1", 3, NOW, crisis=True),  # quarantined
            _response("p", "s2", 9, NOW + timedelta(days=2)),  # out of range
        ]
        assert status.separated_session_count(
            status.face_value_responses(responses)
        ) == 0


class TestMigration:
    """v1 §11 / R9: nothing discarded, nothing auto-promoted."""

    @pytest.fixture()
    def migrated(self, store, tstore):
        import json
        from pathlib import Path

        source = Path("dude/pom/sources/joseph_triggers_v1.json")
        for entry in json.loads(source.read_text(encoding="utf-8")):
            store.append_trigger(TriggerPattern(**entry))
        links = migrate_legacy(tstore, store, USER)
        return store, tstore, links

    def test_all_legacy_triggers_link_to_families(self, migrated) -> None:
        store, tstore, links = migrated
        legacy = store.load_triggers()
        assert len(links) == len(legacy) == 11
        linked = {link.legacy_trigger_id for link in links}
        assert linked == {t.id for t in legacy}
        assert all(link.superseded_by_family_id for link in links)

    def test_legacy_migrates_as_candidate_never_supported(self, migrated) -> None:
        _store, tstore, _links = migrated
        bundle = tstore.load()
        for slug in ("inactivity_as_threat", "unsolicited_help", "fatigue_amplification"):
            profile = bundle.profile_for_family(USER, slug)
            assert profile is not None, slug
            assert profile.status is TriggerFamilyStatus.CANDIDATE
        # Mapped-to low-support families are NOT re-promoted by migration.
        silence = bundle.profile_for_family(USER, "generic_silence")
        assert silence.status is TriggerFamilyStatus.CANDIDATE_WITH_LOW_SUPPORT

    def test_migration_evidence_is_weak_and_typed(self, migrated) -> None:
        _store, tstore, links = migrated
        bundle = tstore.load()
        migration_evidence = [
            e
            for e in bundle.evidence
            if e.source_type is EvidenceSourceType.LEGACY_MANUAL_TRIGGER
        ]
        assert len(migration_evidence) == 11
        assert all(e.strength.value == "weak" for e in migration_evidence)

    def test_attend_calibration_tag_carries_onto_family(self, migrated) -> None:
        """R7: the historically_accurate legacy tag survives migration."""
        _store, tstore, _links = migrated
        profile = tstore.load().profile_for_family(
            USER, "arbitrary_power_without_legible_recourse"
        )
        assert profile.calibration is TriggerCalibration.HISTORICALLY_ACCURATE

    def test_migration_is_idempotent(self, migrated) -> None:
        store, tstore, _links = migrated
        assert migrate_legacy(tstore, store, USER) == []


class TestTriggerStore:
    def test_supersede_chains_resolve(self, tstore) -> None:
        bundle = tstore.load()
        family = bundle.families[0]
        revised = family.model_copy(
            update={"id": "revised", "supersedes": family.id}
        )
        tstore.append(revised)
        reloaded = tstore.load()
        ids = {f.id for f in reloaded.families}
        assert "revised" in ids
        assert family.id not in ids

    def test_revocation_is_a_superseding_record_with_reason(self, tstore) -> None:
        """R6d: the revocation primitive — supersede with reason, never
        delete."""
        bundle = tstore.load()
        response = bundle.calibration[0]
        revoked = response.model_copy(
            update={
                "id": "revoked_copy",
                "supersedes": response.id,
                "revoked": True,
                "revocation_reason": "user revoked this answer",
            }
        )
        tstore.append(revoked)
        reloaded = tstore.load()
        surviving = {r.id for r in reloaded.calibration}
        assert "revoked_copy" in surviving
        assert response.id not in surviving
        assert status.usable_responses(
            [r for r in reloaded.calibration if r.id == "revoked_copy"]
        ) == []


class TestDistortionVocabulary:
    """R3: bidirectional, template-bound, floor-validated."""

    def test_amplification_copy_is_bidirectional_and_template_bound(self) -> None:
        assert set(distortion.AMPLIFICATION_TEMPLATES) == {
            "urgency",
            "certainty",
            "action_pressure",
            "attention_narrowing",
        }
        assert set(distortion.SUPPRESSION_TEMPLATES) == {
            "minimization",
            "habituation",
            "self_doubt",
        }
        from dude.triggers.contracts import OverlapLevel

        block = distortion.render_distortion_block(
            OverlapLevel.MODERATE, crisis_active=False
        )
        # Both directions render, and every line comes from the registry.
        assert "Amplification candidate" in block
        assert "Suppression candidate" in block
        registry = set(distortion.renderable_templates())
        for line in block.splitlines():
            assert line in registry
        for template in registry:
            validate_copy(template)

    def test_distortion_block_only_at_moderate_and_never_in_crisis(self) -> None:
        from dude.triggers.contracts import OverlapLevel

        assert distortion.render_distortion_block(OverlapLevel.LOW, False) == ""
        assert distortion.render_distortion_block(OverlapLevel.NONE, False) == ""
        assert distortion.render_distortion_block(OverlapLevel.HIGH, True) == ""
        assert distortion.render_distortion_block(OverlapLevel.HIGH, False)

    def test_no_match_never_rendered_as_unexplained_activation(self) -> None:
        """R3 mirrored invariant: NO_TRIGGER_MATCH != ACTIVATION_UNWARRANTED."""
        assert (
            "says nothing about whether your read is right"
            in distortion.NO_MATCH_COPY
        )
        validate_copy(distortion.NO_MATCH_COPY)
        lowered = " ".join(distortion.renderable_templates()).lower()
        for forbidden in ("unexplained activation", "unwarranted", "no reason to feel"):
            assert forbidden not in lowered

    def test_escape_and_protector_vocabulary_not_renderable(self) -> None:
        lowered = " ".join(distortion.renderable_templates()).lower()
        for banned in distortion.NON_RENDERABLE_VOCABULARY:
            assert banned not in lowered
