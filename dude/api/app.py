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
