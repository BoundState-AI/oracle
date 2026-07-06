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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict

from dude.data import Case, SafetyScanResult, SourceType
from dude.pipeline.engine import analyze, capture
from dude.store.jsonl import CaseStore, StoreError
from dude.voice.stt import SpeechToText, VoiceUnavailable
from dude.voice.tts import TextToSpeech

LOGGER = logging.getLogger("dude.api.app")


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def create_app(
    store: CaseStore | None = None,
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
) -> FastAPI:
    """Build the app with injected dependencies. When stt/tts are None the
    voice endpoint refuses visibly; REST capture always works."""
    app = FastAPI(title="DUDE", version="0.2.0")
    case_store = store or CaseStore()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/cases")
    def create_case(request: CreateCaseRequest) -> dict[str, str]:
        case = Case(title=request.title)
        case_store.create_case(case)
        return {"case_id": case.id}

    @app.post("/cases/{case_id}/capture")
    def rest_capture(case_id: str, request: CaptureRequest) -> dict[str, object]:
        try:
            record, scan = capture(case_store, case_id, request.text)
        except StoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"capture_id": record.id, **_safety_payload(scan)}

    @app.post("/cases/{case_id}/analyze")
    def rest_analyze(case_id: str) -> dict[str, object]:
        try:
            result = analyze(case_store, case_id)
        except StoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": result.run.id,
            "mode": result.run.mode.value,
            "served_prior": result.served_prior,
            "summary": result.run.user_facing_summary,
            "crisis_active": result.run.crisis_active,
        }

    @app.websocket("/cases/{case_id}/voice")
    async def voice(websocket: WebSocket, case_id: str) -> None:
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
