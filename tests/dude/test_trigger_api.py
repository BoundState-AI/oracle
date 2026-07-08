"""Trigger Calibration Engine API surface (dude.api.app; trigger spec
v1.1 R3/R5/R6/R8).

The load-bearing assertions: case_detail serves the run's single overlap
statistic as a LEVEL WORD plus vetted template copy verbatim; proposals
await user confirm/deny (a disposition is a superseding record); the Lab
routes never leak intensity scores or raw response text; and calibration
answers are stamped server-side (declared scale, session, state at
capture — crisis-time answers quarantine by construction).

Fakes are injected through create_app() — no monkeypatching, no
dependency on the git-excluded seed source.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from dude.api.app import create_app
from dude.data import Case
from dude.pipeline.passes import PassSet
from dude.store.jsonl import CaseStore
from dude.triggers import distortion
from dude.triggers.assess import StubAssessor
from dude.triggers.contracts import (
    DEFAULT_USER_ID,
    CalibrationPair,
    CalibrationPrompt,
    CaseTriggerAssessment,
    FeatureCitation,
    FeatureType,
    PersonalTriggerProfile,
    ProvenanceClass,
    TriggerCalibrationResponse,
    TriggerFamily,
    TriggerFamilyStatus,
    TriggerFeature,
)
from dude.triggers.store import TriggerStore

CRISIS_UTTERANCE = "He said he's going to kill me if I leave."
# Contains the prefilter cue "scope" so the seeded family is a candidate.
CASE_TEXT = "The audit expanded with no stated scope and no explanation."

FAMILY_LABEL = "Authority with unclear scope"


def _client(tmp_path) -> tuple[TestClient, CaseStore, str]:
    store = CaseStore(root=tmp_path / "dude_home")
    case = Case(title="trigger api case")
    store.create_case(case)
    # Explicit stubs keep tests hermetic even with provider keys present.
    app = create_app(store=store, passes=PassSet(), assessor=StubAssessor())
    return TestClient(app), store, case.id


def _seed_family(store: CaseStore) -> tuple[TriggerStore, TriggerFamily]:
    """One self_report_supported family so confirmed assessments feed the
    overlap statistic (R11 render set)."""
    tstore = TriggerStore(store)
    family = TriggerFamily(
        slug="unclear_scope_authority",
        label=FAMILY_LABEL,
        description="An authority acts without a legible scope.",
        features=[
            TriggerFeature(
                feature_slug="scope_unclear",
                description="No stated scope for the intrusion.",
                feature_type=FeatureType.REQUIRED,
                provenance_class=ProvenanceClass.INTERPERSONAL_PERFORMED,
            )
        ],
        prefilter_cues=["scope"],
    )
    tstore.append(family)
    tstore.append(
        PersonalTriggerProfile(
            user_id=DEFAULT_USER_ID,
            trigger_family_id=family.id,
            family_slug=family.slug,
            status=TriggerFamilyStatus.SELF_REPORT_SUPPORTED,
        )
    )
    return tstore, family


def _proposal(case_id: str, family: TriggerFamily) -> CaseTriggerAssessment:
    return CaseTriggerAssessment(
        case_id=case_id,
        user_id=DEFAULT_USER_ID,
        trigger_family_id=family.id,
        family_slug=family.slug,
        matched_features=[
            FeatureCitation(feature_slug="scope_unclear", span="no stated scope")
        ],
        model_run_id="model-run-1",
    )


class TestCaseDetailTriggerView:
    def test_no_match_serves_level_word_and_exact_no_match_copy(
        self, tmp_path
    ) -> None:
        client, _store, case_id = _client(tmp_path)
        client.post(f"/cases/{case_id}/capture", json={"text": "Quiet day."})
        client.post(f"/cases/{case_id}/analyze")
        detail = client.get(f"/cases/{case_id}").json()
        run = detail["last_run"]
        assert run["trigger_overlap"] == "none"
        assert run["overlap_labels"] == []
        # R3 mirrored invariant: the exact vetted copy, never a blank.
        assert run["no_match_copy"] == distortion.NO_MATCH_COPY
        # R3: no distortion block below moderate overlap.
        assert run["distortion_block"] == ""
        assert detail["trigger_proposals"] == []
        assert detail["possible_overlap_note"] == ""

    def test_pending_proposal_lists_label_and_vetted_note(self, tmp_path) -> None:
        client, store, case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        tstore.append(_proposal(case_id, family))
        detail = client.get(f"/cases/{case_id}").json()
        assert [p["label"] for p in detail["trigger_proposals"]] == [FAMILY_LABEL]
        # R5: unconfirmed renders as possibility, from the vetted template.
        assert detail["possible_overlap_note"] == distortion.render_possible_overlap(
            [FAMILY_LABEL]
        )

    def test_confirmed_overlap_feeds_next_run_as_level_word(self, tmp_path) -> None:
        client, store, case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        proposal = _proposal(case_id, family)
        tstore.append(proposal)
        confirmed = client.post(
            f"/cases/{case_id}/assessments/{proposal.id}/confirm"
        )
        assert confirmed.status_code == 200
        # New evidence reopens the gate; the next run counts the
        # confirmed family in the single overlap statistic (R8/R9).
        client.post(f"/cases/{case_id}/capture", json={"text": CASE_TEXT})
        client.post(f"/cases/{case_id}/analyze")
        detail = client.get(f"/cases/{case_id}").json()
        assert detail["last_run"]["trigger_overlap"] == "low"
        assert detail["last_run"]["overlap_labels"] == [FAMILY_LABEL]
        assert detail["trigger_proposals"] == []


class TestInstantRead:
    """Capture-time deterministic first read: candidates from the
    pre-filter as an R8 hint word plus vetted possibility copy — present
    on benign captures, omitted entirely on crisis (R2), never scores."""

    def test_benign_capture_with_matching_cue_gets_instant_read(
        self, tmp_path
    ) -> None:
        client, store, case_id = _client(tmp_path)
        _seed_family(store)
        body = client.post(
            f"/cases/{case_id}/capture", json={"text": CASE_TEXT}
        ).json()
        instant = body["instant_read"]
        # Sentinel: exactly these keys — no scores, no calibration text.
        assert set(instant) == {
            "overlap_hint",
            "candidate_labels",
            "note",
            "verdict_line",
        }
        assert instant["overlap_hint"] == "low"  # one candidate (R8)
        assert instant["candidate_labels"] == [FAMILY_LABEL]
        # Possibility framing only — candidates are resemblance, never
        # confirmed matches (R5): the exact vetted template.
        assert instant["note"] == distortion.render_possible_overlap(
            [FAMILY_LABEL]
        )
        assert (
            instant["verdict_line"]
            == "Trigger overlap does not reduce the weight of observed evidence."
        )

    def test_benign_capture_without_cues_gets_no_match_copy(self, tmp_path) -> None:
        client, store, case_id = _client(tmp_path)
        _seed_family(store)
        body = client.post(
            f"/cases/{case_id}/capture", json={"text": "Quiet day, nothing new."}
        ).json()
        instant = body["instant_read"]
        assert instant["overlap_hint"] == "none"
        assert instant["candidate_labels"] == []
        # R3 mirrored invariant: the exact vetted no-match copy.
        assert instant["note"] == distortion.NO_MATCH_COPY

    def test_crisis_capture_omits_instant_read_entirely(self, tmp_path) -> None:
        """R2: crisis owns the moment — even with a matching cue, the
        payload carries no instant_read key at all."""
        client, store, case_id = _client(tmp_path)
        tstore, _family = _seed_family(store)
        # A second family whose cue matches the crisis utterance ("leave"),
        # proving omission is the crisis rule, not a missing candidate.
        cued = TriggerFamily(
            slug="departure_threat",
            label="Threats tied to leaving",
            description="Escalation framed around departure.",
            features=[
                TriggerFeature(
                    feature_slug="departure_framed",
                    description="The threat is conditioned on leaving.",
                    feature_type=FeatureType.REQUIRED,
                    provenance_class=ProvenanceClass.INTERPERSONAL_PERFORMED,
                )
            ],
            prefilter_cues=["leave"],
        )
        tstore.append(cued)
        tstore.append(
            PersonalTriggerProfile(
                user_id=DEFAULT_USER_ID,
                trigger_family_id=cued.id,
                family_slug=cued.slug,
                status=TriggerFamilyStatus.SELF_REPORT_SUPPORTED,
            )
        )
        body = client.post(
            f"/cases/{case_id}/capture", json={"text": CRISIS_UTTERANCE}
        ).json()
        assert body["crisis"] is True
        assert "instant_read" not in body

    def test_no_seeded_families_means_no_instant_read(self, tmp_path) -> None:
        """With nothing calibrated, 'no calibrated pattern matched' would
        overclaim — the object is omitted, not faked."""
        client, _store, case_id = _client(tmp_path)
        body = client.post(
            f"/cases/{case_id}/capture", json={"text": CASE_TEXT}
        ).json()
        assert "instant_read" not in body

    def test_copy_passes_banned_phrase_floor_and_leaks_no_scores(
        self, tmp_path
    ) -> None:
        from dude.core.loop import validate_copy

        client, store, case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        prompt = CalibrationPrompt(
            prompt_slug="scope_scenario",
            text="An audit expands with no stated scope.",
            family_slug=family.slug,
        )
        tstore.append(prompt)
        tstore.append(
            TriggerCalibrationResponse(
                user_id=DEFAULT_USER_ID,
                prompt_id=prompt.id,
                session_id="round_1",
                raw_score=4,
                declared_scale_min=0,
                declared_scale_max=5,
                raw_response_text="SENTINEL-RAW-ANSWER",
            )
        )
        response = client.post(
            f"/cases/{case_id}/capture", json={"text": CASE_TEXT}
        )
        instant = response.json()["instant_read"]
        validate_copy(instant["note"])  # must not raise
        validate_copy(instant["verdict_line"])
        # R6: no intensity scores and no calibration text on this surface.
        assert "SENTINEL-RAW-ANSWER" not in response.text
        assert "raw_score" not in response.text
        assert "raw_response_text" not in response.text


class TestAssessmentDisposition:
    def test_confirm_supersedes_with_user_confirmed(self, tmp_path) -> None:
        client, store, case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        proposal = _proposal(case_id, family)
        tstore.append(proposal)
        response = client.post(
            f"/cases/{case_id}/assessments/{proposal.id}/confirm"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_confirmed"] is True
        assert body["supersedes"] == proposal.id
        resolved = tstore.load().assessments
        assert [a.user_confirmed for a in resolved] == [True]
        # The superseded id resolves away — a second disposition is 404.
        again = client.post(f"/cases/{case_id}/assessments/{proposal.id}/confirm")
        assert again.status_code == 404

    def test_deny_supersedes_and_disposed_conflicts(self, tmp_path) -> None:
        client, store, case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        proposal = _proposal(case_id, family)
        tstore.append(proposal)
        denied = client.post(f"/cases/{case_id}/assessments/{proposal.id}/deny")
        assert denied.status_code == 200
        assert denied.json()["user_denied"] is True
        # Disposing the disposed record conflicts instead of re-writing.
        conflict = client.post(
            f"/cases/{case_id}/assessments/{denied.json()['assessment_id']}/confirm"
        )
        assert conflict.status_code == 409

    def test_unknown_assessment_is_404(self, tmp_path) -> None:
        client, _store, case_id = _client(tmp_path)
        response = client.post(f"/cases/{case_id}/assessments/nope/confirm")
        assert response.status_code == 404


class TestLabFamilies:
    def test_families_serve_labels_status_and_source_types_only(
        self, tmp_path
    ) -> None:
        client, store, _case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        prompt = CalibrationPrompt(
            prompt_slug="scope_scenario",
            text="An audit expands with no stated scope.",
            family_slug=family.slug,
        )
        tstore.append(prompt)
        tstore.append(
            TriggerCalibrationResponse(
                user_id=DEFAULT_USER_ID,
                prompt_id=prompt.id,
                session_id="round_1",
                raw_score=4,
                declared_scale_min=0,
                declared_scale_max=5,
                raw_response_text="SENTINEL-RAW-ANSWER",
            )
        )
        response = client.get("/triggers/families")
        assert response.status_code == 200
        listing = response.json()
        entry = next(e for e in listing if e["slug"] == family.slug)
        assert entry["label"] == FAMILY_LABEL
        assert entry["status"] == "self_report_supported"
        assert entry["calibration"] == "neutral"
        assert entry["fire_rate_caveat"] == ""
        assert entry["features"][0]["description"]
        assert {"source_type": "calibration_response", "count": 1} in entry[
            "evidence_sources"
        ]
        # R6: no raw scores and no response text on any default surface.
        assert "SENTINEL-RAW-ANSWER" not in response.text
        assert "raw_score" not in response.text
        assert "raw_response_text" not in response.text


class TestCalibrationFlow:
    def _seed_prompts(
        self, tstore: TriggerStore, family: TriggerFamily
    ) -> tuple[CalibrationPrompt, CalibrationPrompt, CalibrationPrompt]:
        high = CalibrationPrompt(
            prompt_slug="pair_high",
            text="The audit expands and nobody will say why.",
            family_slug=family.slug,
        )
        low = CalibrationPrompt(
            prompt_slug="pair_low",
            text="The audit expands with a written scope and appeal path.",
            family_slug=family.slug,
            is_negative_control=True,
        )
        single = CalibrationPrompt(
            prompt_slug="single_scenario",
            text="A rule changes overnight without notice.",
            family_slug=family.slug,
        )
        for prompt in (high, low, single):
            tstore.append(prompt)
        tstore.append(
            CalibrationPair(
                family_slug=family.slug,
                dimension="scope_clarity",
                high_arm_prompt_id=high.id,
                low_arm_prompt_id=low.id,
            )
        )
        return high, low, single

    def test_pending_groups_pairs_and_answers_retire_prompts(
        self, tmp_path
    ) -> None:
        client, store, _case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        _high, _low, single = self._seed_prompts(tstore, family)
        pending = client.get("/triggers/calibration/pending").json()
        assert [u["kind"] for u in pending] == ["pair", "single"]
        assert len(pending[0]["prompts"]) == 2
        answered = client.post(
            "/triggers/calibration",
            json={"prompt_id": single.id, "raw_score": 3},
        )
        assert answered.status_code == 200
        assert answered.json()["quarantined"] is False
        remaining = client.get("/triggers/calibration/pending").json()
        assert [u["kind"] for u in remaining] == ["pair"]
        stored = tstore.load().calibration[-1]
        # Server-stamped, never caller-supplied (§13/R6f).
        assert (stored.declared_scale_min, stored.declared_scale_max) == (0, 5)
        assert stored.session_id.startswith("lab_")
        assert stored.state_at_capture.crisis_flag_active is False

    def test_crisis_time_answer_is_quarantined(self, tmp_path) -> None:
        client, store, case_id = _client(tmp_path)
        tstore, family = _seed_family(store)
        _high, _low, single = self._seed_prompts(tstore, family)
        # The capture's safety floor persists a crisis SafetyEvent.
        client.post(f"/cases/{case_id}/capture", json={"text": CRISIS_UTTERANCE})
        answered = client.post(
            "/triggers/calibration",
            json={"prompt_id": single.id, "raw_score": 5},
        )
        assert answered.status_code == 200
        assert answered.json()["quarantined"] is True
        stored = tstore.load().calibration[-1]
        assert stored.state_at_capture.crisis_flag_active is True
        assert stored.quarantined is True

    def test_unknown_prompt_is_404(self, tmp_path) -> None:
        client, _store, _case_id = _client(tmp_path)
        response = client.post(
            "/triggers/calibration", json={"prompt_id": "nope", "raw_score": 2}
        )
        assert response.status_code == 404
