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

from dude.data import Case, SafetyScanResult, SourceType
from dude.pipeline.engine import analyze, capture
from dude.store.jsonl import CaseStore, StoreError
from dude.voice.stt import SpeechToText, VoiceUnavailable
from dude.voice.tts import TextToSpeech

LOGGER = logging.getLogger("dude.api.app")

# Websocket close code for failed auth (4000-range = application-defined).
WS_UNAUTHORIZED = 4401


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
    existing_ids = {i.id for i in bundle.items}
    imported = 0
    for raw in _json.loads(dataset.read_text(encoding="utf-8")):
        item = PomItem.model_validate({**raw, "source_artifact_id": artifact.id})
        if item.id not in existing_ids:
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
        "items_total": len(existing_ids) + imported,
    }


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def create_router(
    store: CaseStore | None = None,
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
    passes: "PassSet | None" = None,
    prefix: str = "",
    api_key: str = "",
) -> APIRouter:
    """Build the DUDE router with injected dependencies. When stt/tts are
    None the voice endpoint refuses visibly; REST capture always works.
    `passes` defaults to environment resolution (live models with keys,
    visible stubs without); tests inject an explicit PassSet to stay
    hermetic. `api_key` enables X-API-Key auth on every route including
    the websocket (empty = auth off, matching the server.py pattern)."""
    from dude.pipeline.live_passes import resolve_passes
    from dude.pipeline.passes import PassSet

    case_store = store or CaseStore()
    pass_set = passes if passes is not None else resolve_passes()

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
                }
                if last
                else None
            ),
        }

    @router.post("/pom/import-bundled", **guarded)
    def pom_import_bundled() -> dict[str, object]:
        result = import_bundled_pom(case_store)
        if result is None:
            raise HTTPException(status_code=404, detail="Bundled POM not present.")
        return result

    @router.post("/cases/{case_id}/capture", **guarded)
    def rest_capture(case_id: str, request: CaptureRequest) -> dict[str, object]:
        try:
            record, scan = capture(case_store, case_id, request.text)
        except StoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"capture_id": record.id, **_safety_payload(scan)}

    @router.post("/cases/{case_id}/analyze", **guarded)
    def rest_analyze(case_id: str) -> dict[str, object]:
        try:
            result = analyze(case_store, case_id, passes=pass_set)
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
) -> FastAPI:
    """Standalone DUDE app (tests, single-service deployment). The shared
    server (server.py) mounts create_router() under /dude with the
    repo-wide API key instead."""
    from dude.pipeline.passes import PassSet  # noqa: F401  (type reference)

    app = FastAPI(title="DUDE", version="0.2.0")
    app.include_router(
        create_router(store=store, stt=stt, tts=tts, passes=passes)
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
