#!/usr/bin/env python3
"""
Module: dude.api.app
Purpose: FastAPI surface — REST case operations + the two-way voice
         websocket (spec v0.2 §2; voice per user requirement).

Voice websocket protocol (/cases/{case_id}/voice):
  client -> server:  binary frames  = audio chunks (WAV/PCM)
                     text frame     = JSON {"type": "end"} to close an
                                      utterance, {"type": "bye"} to hang up
  server -> client:  {"type": "transcript", "text": ...}
                     {"type": "safety", "crisis": bool, "message": ...,
                      "resources": [...]}          — only when flags fire
                     {"type": "instant_read", "overlap_hint": ...,
                      "candidate_labels": [...], "note": ...,
                      "verdict_line": ...}         — deterministic first
                                                     read; never on crisis
                     {"type": "reply", "text": ...} — evidence-state copy
                     binary frame                   — WAV of the reply,
                                                      only if TTS available
                     {"type": "refusal", "reason": ...}

Ordering is the capture contract (v0.2 I1): transcript -> safety scan +
SafetyEvent persist (inside pipeline.capture) -> reply. A safety message,
when present, is sent BEFORE the reply, and the spoken reply for a crisis
utterance is the crisis message itself — never analysis copy.

Dependency injection over globals: create_app(store, stt, tts) so tests
exercise the full websocket path with fakes, no monkeypatching.

Safety Critical: True — this surface renders crisis resources and
refusals; swallowing either is the cardinal failure mode.
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
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ConfigDict

from dude.core.loop import validate_copy
from dude.data import AnalysisRun, Case, SafetyScanResult, SourceType
from dude.pipeline.engine import analyze, capture
from dude.store.jsonl import CaseStore, StoreError
from dude.triggers import assess as trigger_assess
from dude.triggers import distortion
from dude.triggers.contracts import (
    DEFAULT_USER_ID,
    CalibrationPrompt,
    EvidenceSourceType,
    OverlapLevel,
    TriggerFamilyStatus,
)
from dude.triggers.store import TriggerBundle, TriggerStore
from dude.voice.stt import SpeechToText, VoiceUnavailable
from dude.voice.tts import TextToSpeech

LOGGER = logging.getLogger("dude.api.app")

# Websocket close code for failed auth (4000-range = application-defined).
WS_UNAUTHORIZED = 4401

# The Lab tap scale (spec v1 §8). The server declares the scale; the
# contract computes out_of_range from it and never clamps the raw score.
LAB_SCALE_MIN = 0
LAB_SCALE_MAX = 5

# R6f state stamp: a crisis SafetyEvent anywhere in the store within this
# window marks calibration as captured under an active crisis flag, which
# the contract force-quarantines (provisional pending reconfirmation).
CRISIS_STATE_WINDOW = timedelta(hours=24)


def import_bundled_pom(case_store: CaseStore) -> dict[str, object] | None:
    """Idempotently import the repo-bundled, Oracle-reviewed POM (manual +
    dataset) into this deployment's store. Keyed on artifact hash and item
    ids, append-only — safe to run on every startup (DUDE_POM_AUTOIMPORT)
    and via the guarded route. Returns None if no bundle ships with this
    build."""
    import json as _json
    from pathlib import Path

    from dude.pom.contracts import PomItem, SourceArtifact
    from dude.pom.store import PomStore

    sources = Path(__file__).resolve().parent.parent / "pom" / "sources"
    manual = sources / "joseph_operating_manual_v1.md"
    dataset = sources / "joseph_pom_dataset_v1.json"
    if not manual.exists() or not dataset.exists():
        return None
    pom = PomStore(case_store)
    bundle = pom.load()
    content = manual.read_text(encoding="utf-8")
    probe = SourceArtifact(user_id="joseph", title="probe", content=content)
    artifact = next(
        (a for a in bundle.source_artifacts
         if a.content_sha256 == probe.content_sha256),
        None,
    )
    if artifact is None:
        artifact = SourceArtifact(
            user_id="joseph",
            title="Joseph Operating Manual v1",
            content=content,
        )
        pom.append(artifact)
    # WHY content keying: dataset rows carry no ids, so id-based dedupe
    # minted fresh uuids every boot and re-imported all 180 items per
    # deploy (found in production: 1980 items after 11 deploys).
    def _key(statement: str, category: str) -> tuple[str, str]:
        return (" ".join(statement.split()).lower(), category)

    existing_keys = {_key(i.statement, i.category.value) for i in bundle.items}
    imported = 0
    for raw in _json.loads(dataset.read_text(encoding="utf-8")):
        item = PomItem.model_validate({**raw, "source_artifact_id": artifact.id})
        if _key(item.statement, item.category.value) not in existing_keys:
            existing_keys.add(_key(item.statement, item.category.value))
            pom.append(item)
            imported += 1
    LOGGER.info("Bundled POM import: %d new items", imported)

    # Trigger profile seed (spec v0.1 §8, T1–T7): idempotent by name.
    triggers_file = sources / "joseph_triggers_v1.json"
    if triggers_file.exists():
        from dude.data import TriggerPattern

        existing_names = {t.name for t in case_store.load_triggers()}
        seeded = 0
        for raw in _json.loads(triggers_file.read_text(encoding="utf-8")):
            if raw["name"] not in existing_names:
                case_store.append_trigger(TriggerPattern.model_validate(raw))
                seeded += 1
        LOGGER.info("Trigger profile seed: %d new triggers", seeded)
    return {
        "artifact_sha256": artifact.content_sha256,
        "items_imported": imported,
        "items_total": len(existing_keys),
    }


def _trigger_view(
    case_store: CaseStore, case_id: str, last: AnalysisRun | None
) -> dict[str, object]:
    """Trigger-engine view for case_detail (trigger spec v1.1 R3/R5/R8):
    the run's single overlap statistic as a LEVEL WORD with de-identified
    family labels, the live proposals awaiting user disposition, and the
    vetted template copy verbatim — never scores, never calibration text."""
    tb = TriggerStore(case_store).load()
    proposals = trigger_assess.pending_proposals(tb, case_id, DEFAULT_USER_ID)
    labels = [family.label for _a, family in proposals]
    run_fields: dict[str, object] = {}
    if last is not None:
        run_fields = {
            "trigger_overlap": last.trigger_overlap,
            "overlap_labels": trigger_assess.confirmed_overlap_labels(
                tb, case_id, DEFAULT_USER_ID
            ),
            # R3/R2 render rules live in the renderer: empty below
            # moderate overlap and always empty while a crisis is active.
            "distortion_block": distortion.render_distortion_block(
                OverlapLevel(last.trigger_overlap), last.crisis_active
            ),
            # R3 mirrored invariant: the exact vetted no-match copy, so
            # the UI never paraphrases NO_TRIGGER_MATCH into a verdict.
            "no_match_copy": distortion.NO_MATCH_COPY,
        }
    return {
        "run": run_fields,
        "proposals": [
            {"assessment_id": a.id, "label": family.label}
            for a, family in proposals
        ],
        "note": distortion.render_possible_overlap(labels) if labels else "",
    }


def _instant_read(
    case_store: CaseStore, text: str, scan: SafetyScanResult
) -> dict[str, object] | None:
    """Deterministic first read at capture (founder brief: "PTSD trigger
    or warranted?" needs a first answer INSTANTLY, not after the model
    passes). Runs ONLY the substring pre-filter (trigger_assess.prefilter)
    over the seeded families — no model call, sub-second — and is honest
    about what that is: cue RESEMBLANCE nominating CANDIDATES, never
    confirmed matches ("possible" copy only, R5). Vetted template copy
    exclusively, validated against the banned-phrase floor; never scores,
    never calibration text (R6). Returns None when the scan is a crisis
    (R2 — crisis owns the moment) or when no families are seeded (with
    nothing calibrated, "no calibrated pattern matched" would overclaim).
    """
    if scan.crisis:
        return None
    tb = TriggerStore(case_store).load()
    by_id = {f.id: f for f in tb.families}
    families = [
        by_id[p.trigger_family_id]
        for p in tb.profiles_for(DEFAULT_USER_ID)
        if p.status is not TriggerFamilyStatus.RETIRED
        and p.trigger_family_id in by_id
    ]
    if not families:
        return None
    candidates = trigger_assess.prefilter(families, text)
    labels = sorted({f.label for f in candidates})
    # WHY overlap_level with empty rates: the hint word reuses the exact
    # R8 count thresholds (0=none / 1=low / 2=moderate / >=3=high) over
    # the CANDIDATE count; fire-rate discounting applies to confirmed
    # matches only, so rates stay empty here.
    level, _counted, _low_diag = trigger_assess.overlap_level(
        [f.slug for f in candidates], {}
    )
    note = (
        distortion.render_possible_overlap(labels)
        if labels
        else distortion.NO_MATCH_COPY
    )
    return {
        "overlap_hint": level.value,
        "candidate_labels": labels,
        "note": validate_copy(note),
        "verdict_line": validate_copy(distortion.EVIDENCE_EFFECT_COPY),
    }


def _evidence_source_counts(
    tb: TriggerBundle, family_slug: str
) -> list[dict[str, object]]:
    """Evidence SOURCE TYPES with counts for the Lab's per-family "why"
    (R6c: provenance renders; response text and scores never do).
    Calibration responses and pair contrasts count from their own streams;
    the evidence stream covers the remaining types (its per-family
    calibration_response summary rows would double-count the stream)."""
    prompt_ids = {p.id for p in tb.prompts if p.family_slug == family_slug}
    counts: dict[str, int] = {}
    usable = [
        r
        for r in tb.calibration
        if r.prompt_id in prompt_ids and not r.quarantined and not r.revoked
    ]
    if usable:
        counts[EvidenceSourceType.CALIBRATION_RESPONSE.value] = len(usable)
    contrasts = [c for c in tb.contrasts if c.family_slug == family_slug]
    if contrasts:
        counts[EvidenceSourceType.MATCHED_PAIR_CONTRAST.value] = len(contrasts)
    stream_backed = {
        EvidenceSourceType.CALIBRATION_RESPONSE,
        EvidenceSourceType.MATCHED_PAIR_CONTRAST,
    }
    for record in tb.evidence:
        if record.family_slug == family_slug and record.source_type not in stream_backed:
            key = record.source_type.value
            counts[key] = counts.get(key, 0) + 1
    return [
        {"source_type": source, "count": count}
        for source, count in sorted(counts.items())
    ]


def _pending_units(tb: TriggerBundle) -> list[dict[str, object]]:
    """Unanswered calibration prompts as rating units (v1 §2/§8): a
    matched pair with BOTH arms unanswered is one two-scenario unit (the
    "which hits harder" chrome lives in the UI); everything else single.
    Prompt text only — prior answers and scores are never served."""
    answered = {r.prompt_id for r in tb.calibration if not r.revoked}
    by_id = {p.id: p for p in tb.prompts}
    units: list[dict[str, object]] = []
    in_pair: set[str] = set()
    for pair in tb.pairs:
        high = by_id.get(pair.high_arm_prompt_id)
        low = by_id.get(pair.low_arm_prompt_id)
        if high and low and high.id not in answered and low.id not in answered:
            units.append(
                {
                    "kind": "pair",
                    "pair_id": pair.id,
                    "prompts": [_prompt_view(high), _prompt_view(low)],
                }
            )
            in_pair.update({high.id, low.id})
    units.extend(
        {"kind": "single", "pair_id": None, "prompts": [_prompt_view(prompt)]}
        for prompt in tb.prompts
        if prompt.id not in answered and prompt.id not in in_pair
    )
    return units


def _prompt_view(prompt: CalibrationPrompt) -> dict[str, str]:
    return {"prompt_id": prompt.id, "text": prompt.text}


def _recent_crisis(store: CaseStore) -> bool:
    """Whether any case recorded a crisis SafetyEvent inside the window —
    the backend-computed input to state_at_capture (R6f). Never trusted
    from the caller."""
    cutoff = datetime.now(timezone.utc) - CRISIS_STATE_WINDOW
    for case_id in store.list_case_ids():
        bundle = store.load_case(case_id)
        if any(e.crisis and e.recorded_at >= cutoff for e in bundle.safety_events):
            return True
    return False


def _lab_session_id() -> str:
    """One Lab sitting per UTC day: coarser than the 24h separation floor
    in status math, so a burst of ratings never counts as two sessions."""
    return f"lab_{datetime.now(timezone.utc):%Y%m%d}"


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class CalibrationAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_id: str
    raw_score: int
    raw_response_text: str = ""


def create_router(
    store: CaseStore | None = None,
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
    passes: "PassSet | None" = None,
    prefix: str = "",
    api_key: str = "",
    assessor: "TriggerAssessor | None" = None,
) -> APIRouter:
    """Build the DUDE router with injected dependencies. When stt/tts are
    None the voice endpoint refuses visibly; REST capture always works.
    `passes` and `assessor` default to environment resolution (live models
    with keys, visible stubs without); tests inject explicit fakes to stay
    hermetic. `api_key` enables X-API-Key auth on every route including
    the websocket (empty = auth off, matching the server.py pattern)."""
    from dude.pipeline.live_passes import resolve_passes
    from dude.pipeline.passes import PassSet
    from dude.triggers.assess import TriggerAssessor, resolve_assessor  # noqa: F401

    case_store = store or CaseStore()
    pass_set = passes if passes is not None else resolve_passes()
    assessor = assessor if assessor is not None else resolve_assessor()

    async def verify_key(request: Request) -> None:
        if api_key and request.headers.get("X-API-Key", "") != api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

    # WHY per-route dependencies instead of router-level: a router-level
    # Request-typed dependency also binds to the websocket route, where no
    # Request exists, and fails at call time. REST routes carry the guard;
    # the websocket authenticates manually before accept.
    guarded = {"dependencies": [Depends(verify_key)]}
    router = APIRouter(prefix=prefix)

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/cases", **guarded)
    def create_case(request: CreateCaseRequest) -> dict[str, str]:
        case = Case(title=request.title)
        case_store.create_case(case)
        return {"case_id": case.id}

    @router.get("/cases", **guarded)
    def list_cases() -> list[dict[str, str]]:
        listing = []
        for case_id in case_store.list_case_ids():
            bundle = case_store.load_case(case_id)
            listing.append(
                {
                    "case_id": case_id,
                    "title": bundle.case.title,
                    "status": bundle.case.status.value,
                }
            )
        return listing

    @router.get("/cases/{case_id}", **guarded)
    def case_detail(case_id: str) -> dict[str, object]:
        """Full case view for the UI: reality (observed/inferred/unknown),
        models (hypotheses + adversary annotations + falsifiers), and the
        latest run. Bands are the external vocabulary — no numbers."""
        try:
            bundle = case_store.load_case(case_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        last = bundle.analysis_runs[-1] if bundle.analysis_runs else None

        def _norm(text: str) -> str:
            # Near-duplicate key: pre-idempotence runs stored the same
            # statement under varying subjects/phrasings. Person-name and
            # punctuation variance collapses; content stays the judge.
            import re as _re

            lowered = text.lower()
            for phrase in ("the capture author", "the author", "the user",
                           "author", "dude", "joe"):
                lowered = lowered.replace(phrase, "@")
            return _re.sub(r"[^a-z0-9@]+", " ", lowered).strip()[:160]

        def _dude(text: str) -> str:
            # Display-name transform only — the append-only store keeps
            # original wording; the person is Dude on every surface.
            import re as _re

            out = _re.sub(r"\b[Tt]he (capture )?author('s)?\b",
                          lambda m: "Dude's" if m.group(2) else "Dude", text)
            out = _re.sub(r"\b[Tt]he user('s)?\b",
                          lambda m: "Dude's" if m.group(1) else "Dude", out)
            out = _re.sub(r"^Author\b", "Dude", out)
            return out

        def _dedupe(items: list, key) -> list:
            # WHY display-level dedupe: pre-idempotence runs appended
            # duplicate records; the store is append-only by design, so
            # the view collapses exact repeats instead of rewriting
            # history. First occurrence wins, order preserved.
            seen: set = set()
            out = []
            for item in items:
                k = key(item)
                if k not in seen:
                    seen.add(k)
                    out.append(item)
            return out

        bundle.observations = _dedupe(
            bundle.observations, lambda o: _norm(o.statement)
        )
        bundle.interpretations = _dedupe(
            bundle.interpretations, lambda i: _norm(i.statement)
        )
        bundle.unknowns = _dedupe(bundle.unknowns, lambda u: _norm(u.statement))
        live_hyps = [
            h for h in bundle.hypotheses if h.is_live() or h.not_credible_here
        ]
        live_hyps = _dedupe(
            sorted(live_hyps, key=lambda h: -len(h.annotations)),
            lambda h: (h.archetype.value, h.title.lower()),
        )
        bundle.hypotheses = live_hyps
        trigger_view = _trigger_view(case_store, case_id, last)
        return {
            "case_id": bundle.case.id,
            "title": bundle.case.title,
            "status": bundle.case.status.value,
            "observed": [
                {"statement": _dude(o.statement), "user_confirmed": o.user_confirmed}
                for o in bundle.observations
            ],
            "inferred": [_dude(i.statement) for i in bundle.interpretations],
            "unknown": [
                {
                    "statement": _dude(u.statement),
                    "importance": u.importance.value,
                    "pursuit": u.pursuit.value,
                }
                for u in bundle.unknowns
            ],
            "hypotheses": [
                {
                    "title": h.title,
                    "description": h.description,
                    "archetype": h.archetype.value,
                    "band": h.band.value,
                    "harm_class": h.harm_class.value,
                    "falsifiers": h.falsifiers,
                    "not_credible_here": h.not_credible_here,
                    "attacks": [
                        {
                            "attack": a.attack,
                            "unsupported_links": a.unsupported_links,
                        }
                        for a in h.annotations
                    ],
                }
                for h in bundle.hypotheses
            ],
            "last_run": (
                {
                    "mode": last.mode.value,
                    "summary": last.user_facing_summary,
                    "crisis_active": last.crisis_active,
                    "refusals": [r.pass_name for r in last.refusals],
                    "trigger_matches": [
                        m.trigger_name for m in last.trigger_matches
                    ],
                    "trigger_total": len(case_store.load_triggers()),
                    "adjustment_note": last.adjustment.user_facing_note,
                    "adjustment_effect": last.adjustment.net_effect.value,
                    # Trigger spec v1.1 R3/R8 display feed — level word,
                    # labels, and vetted copy from _trigger_view.
                    **trigger_view["run"],
                }
                if last
                else None
            ),
            # R5: proposals awaiting the user's confirm/deny, live from
            # the trigger store (a disposed proposal drops out on refresh).
            "trigger_proposals": trigger_view["proposals"],
            "possible_overlap_note": trigger_view["note"],
        }

    @router.post("/pom/import-bundled", **guarded)
    def pom_import_bundled() -> dict[str, object]:
        result = import_bundled_pom(case_store)
        if result is None:
            raise HTTPException(status_code=404, detail="Bundled POM not present.")
        return result

    @router.post("/triggers/seed", **guarded)
    async def trigger_seed(request: Request) -> dict[str, object]:
        """Import the calibration source (git-excluded per trigger spec
        v1.1 R6) into this deployment's trigger store. The full-fidelity
        markdown arrives as the request body over the authed channel —
        it never ships in the build image. Idempotent by family slug."""
        import tempfile
        from pathlib import Path as _Path

        from dude.triggers.seed import SeedError, import_seed
        from dude.triggers.store import TriggerStore

        body = (await request.body()).decode("utf-8")
        if "TRIGGER" not in body.upper():
            raise HTTPException(status_code=422, detail="Not a calibration source.")
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(body)
            temp_path = _Path(handle.name)
        try:
            report = import_seed(TriggerStore(case_store), source_path=temp_path)
        except SeedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return report.__dict__

    def _dispose_assessment(
        case_id: str, assessment_id: str, confirm: bool
    ) -> dict[str, object]:
        """R5: the user disposes. Confirmation/denial is a SUPERSEDING
        record (contracts in dude.triggers.contracts), never a flag flip;
        an already-disposed proposal conflicts instead of double-writing."""
        from dude.triggers.assess import confirm_assessment, deny_assessment

        tstore = TriggerStore(case_store)
        tb = tstore.load()
        assessment = next(
            (
                a
                for a in tb.assessments
                if a.id == assessment_id and a.case_id == case_id
            ),
            None,
        )
        if assessment is None:
            raise HTTPException(
                status_code=404, detail="Unknown assessment for this case."
            )
        if assessment.user_confirmed or assessment.user_denied:
            raise HTTPException(
                status_code=409,
                detail="Assessment already carries a user disposition.",
            )
        updated = (confirm_assessment if confirm else deny_assessment)(
            tstore, assessment
        )
        return {
            "assessment_id": updated.id,
            "supersedes": assessment.id,
            "user_confirmed": updated.user_confirmed,
            "user_denied": updated.user_denied,
        }

    @router.post(
        "/cases/{case_id}/assessments/{assessment_id}/confirm", **guarded
    )
    def confirm_trigger_assessment(
        case_id: str, assessment_id: str
    ) -> dict[str, object]:
        return _dispose_assessment(case_id, assessment_id, confirm=True)

    @router.post("/cases/{case_id}/assessments/{assessment_id}/deny", **guarded)
    def deny_trigger_assessment(
        case_id: str, assessment_id: str
    ) -> dict[str, object]:
        return _dispose_assessment(case_id, assessment_id, confirm=False)

    @router.get("/triggers/families", **guarded)
    def trigger_families() -> list[dict[str, object]]:
        """Lab family list (v1.1 R6c): label, status word, calibration
        tag, feature descriptions, and evidence SOURCE TYPES with counts.
        Intensity scores and raw_response_text never leave the store on
        this surface — the fire-rate caveat renders as the vetted template
        string, never as a rate."""
        from dude.triggers.assess import FIRE_RATE_CEILING, fire_rates

        tb = TriggerStore(case_store).load()
        rates = fire_rates(tb.assessments)
        by_id = {f.id: f for f in tb.families}
        listing: list[dict[str, object]] = []
        for profile in tb.profiles_for(DEFAULT_USER_ID):
            family = by_id.get(profile.trigger_family_id)
            if family is None:
                continue
            listing.append(
                {
                    "slug": family.slug,
                    "label": family.label,
                    "description": family.description,
                    "status": profile.status.value,
                    "calibration": profile.calibration.value,
                    "fire_rate_caveat": (
                        distortion.render_low_diagnostic(family.label)
                        if rates.get(family.slug, 0.0)
                        > FIRE_RATE_CEILING
                        else ""
                    ),
                    "features": [
                        {
                            "slug": feature.feature_slug,
                            "description": feature.description,
                            "feature_type": feature.feature_type.value,
                        }
                        for feature in family.features
                    ],
                    "evidence_sources": _evidence_source_counts(tb, family.slug),
                }
            )
        return listing

    @router.get("/triggers/calibration/pending", **guarded)
    def calibration_pending() -> list[dict[str, object]]:
        return _pending_units(TriggerStore(case_store).load())

    @router.post("/triggers/calibration", **guarded)
    def calibration_answer(request: CalibrationAnswerRequest) -> dict[str, object]:
        """One Lab rating -> a TriggerCalibrationResponse. The backend
        stamps state_at_capture and the declared scale (R6f/§13);
        out-of-range and crisis quarantine are computed by the contract,
        never trusted from the caller."""
        from dude.triggers.contracts import (
            CaptureState,
            TriggerCalibrationResponse,
        )

        tstore = TriggerStore(case_store)
        prompt = next(
            (p for p in tstore.load().prompts if p.id == request.prompt_id), None
        )
        if prompt is None:
            raise HTTPException(
                status_code=404, detail="Unknown calibration prompt."
            )
        response = TriggerCalibrationResponse(
            user_id=DEFAULT_USER_ID,
            prompt_id=prompt.id,
            session_id=_lab_session_id(),
            raw_score=request.raw_score,
            declared_scale_min=LAB_SCALE_MIN,
            declared_scale_max=LAB_SCALE_MAX,
            raw_response_text=(
                request.raw_response_text
                or f"Rated {request.raw_score} on the Lab "
                f"{LAB_SCALE_MIN}-{LAB_SCALE_MAX} scale."
            ),
            state_at_capture=CaptureState(
                crisis_flag_active=_recent_crisis(case_store)
            ),
        )
        tstore.append(response)
        return {
            "response_id": response.id,
            "out_of_range": response.out_of_range,
            "quarantined": response.quarantined,
        }

    @router.post("/cases/{case_id}/capture", **guarded)
    def rest_capture(case_id: str, request: CaptureRequest) -> dict[str, object]:
        try:
            record, scan = capture(case_store, case_id, request.text)
        except StoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        payload: dict[str, object] = {
            "capture_id": record.id,
            **_safety_payload(scan),
        }
        # Instant deterministic read (candidates, not matches); omitted
        # entirely on a crisis scan — crisis owns the moment (R2).
        instant = _instant_read(case_store, request.text, scan)
        if instant is not None:
            payload["instant_read"] = instant
        return payload

    @router.post("/cases/{case_id}/analyze", **guarded)
    def rest_analyze(case_id: str) -> dict[str, object]:
        # WHY a sync def: Starlette runs it on a worker thread and never
        # cancels it on client disconnect, so a long model run always
        # persists its AnalysisRun (analyze() appends before returning)
        # even if the browser or the 120s frontend proxy gives up first.
        try:
            result = analyze(case_store, case_id, passes=pass_set, assessor=assessor)
        except StoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": result.run.id,
            "mode": result.run.mode.value,
            "served_prior": result.served_prior,
            "summary": result.run.user_facing_summary,
            "crisis_active": result.run.crisis_active,
        }

    @router.websocket("/cases/{case_id}/voice")
    async def voice(websocket: WebSocket, case_id: str) -> None:
        # WHY manual auth here: Request-typed dependencies don't run on
        # websocket routes, so the router-level guard cannot cover this
        # endpoint — the check is done explicitly before accept.
        if api_key and websocket.headers.get("X-API-Key", "") != api_key:
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        await websocket.accept()
        if stt is None:
            # Fail closed, visibly: no backend means no voice, said out loud.
            await websocket.send_json(
                {
                    "type": "refusal",
                    "reason": "No speech-to-text backend is available; "
                    "use text capture.",
                }
            )
            await websocket.close()
            return
        buffer = bytearray()
        try:
            while True:
                message = await websocket.receive()
                # Raw receive() reports disconnects as a message, it does
                # not raise — missing this check makes the loop call
                # receive() again after the socket is gone.
                if message.get("type") == "websocket.disconnect":
                    LOGGER.info("Voice session for case %s closed", case_id)
                    return
                if message.get("bytes") is not None:
                    buffer.extend(message["bytes"])
                    continue
                if message.get("text") is not None:
                    kind = _control_kind(message["text"])
                    if kind == "end":
                        await _finish_utterance(
                            websocket, case_store, case_id, stt, tts, bytes(buffer)
                        )
                        buffer.clear()
                    elif kind == "bye":
                        await websocket.close()
                        return
        except WebSocketDisconnect:
            LOGGER.info("Voice session for case %s disconnected", case_id)

    return router


def create_app(
    store: CaseStore | None = None,
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
    passes: "PassSet | None" = None,
    assessor: "TriggerAssessor | None" = None,
) -> FastAPI:
    """Standalone DUDE app (tests, single-service deployment). The shared
    server (server.py) mounts create_router() under /dude with the
    repo-wide API key instead."""
    from dude.pipeline.passes import PassSet  # noqa: F401  (type reference)
    from dude.triggers.assess import TriggerAssessor  # noqa: F401  (type ref)

    app = FastAPI(title="DUDE", version="0.2.0")
    app.include_router(
        create_router(
            store=store, stt=stt, tts=tts, passes=passes, assessor=assessor
        )
    )
    return app


def _control_kind(raw: str) -> str:
    import json

    try:
        return str(json.loads(raw).get("type", ""))
    except (ValueError, AttributeError):
        return ""


async def _finish_utterance(
    websocket: WebSocket,
    store: CaseStore,
    case_id: str,
    stt: SpeechToText,
    tts: TextToSpeech | None,
    audio: bytes,
) -> None:
    """One utterance: transcribe -> capture (safety floor + persist,
    v0.2 I1 ordering) -> transcript, safety, reply (text, then audio)."""
    try:
        segments = stt.transcribe(audio)
    except VoiceUnavailable as exc:
        await websocket.send_json({"type": "refusal", "reason": str(exc)})
        return
    transcript = " ".join(s.text for s in segments).strip()
    if not transcript:
        await websocket.send_json(
            {"type": "refusal", "reason": "Nothing was transcribed."}
        )
        return
    try:
        record, scan = capture(store, case_id, transcript, SourceType.VOICE)
    except StoreError as exc:
        await websocket.send_json({"type": "refusal", "reason": str(exc)})
        return
    await websocket.send_json(
        {"type": "transcript", "text": transcript, "capture_id": record.id}
    )
    if scan.flags:
        await websocket.send_json({"type": "safety", **_safety_payload(scan)})
    # Instant deterministic read on the spoken path too — None on a
    # crisis scan (R2), so no frame competes with the resources above.
    instant = _instant_read(store, transcript, scan)
    if instant is not None:
        await websocket.send_json({"type": "instant_read", **instant})
    # WHY the crisis message IS the spoken reply: on a crisis utterance the
    # only correct voice response is the resources, not capture chrome.
    reply = (
        scan.user_facing_message
        if scan.crisis
        else "Got it. I'm separating what happened from what it might mean. "
        "Say more, or ask for the analysis."
    )
    await websocket.send_json({"type": "reply", "text": reply})
    if tts is not None:
        try:
            await websocket.send_bytes(tts.synthesize(reply))
        except VoiceUnavailable as exc:
            await websocket.send_json({"type": "refusal", "reason": str(exc)})


def _safety_payload(scan: SafetyScanResult) -> dict[str, object]:
    return {
        "crisis": scan.crisis,
        "message": scan.user_facing_message,
        "flags": [f.category.value for f in scan.flags],
        "resources": [
            {"name": r.name, "contact": r.contact, "note": r.note}
            for r in scan.resources
        ],
    }
