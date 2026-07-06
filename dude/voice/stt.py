#!/usr/bin/env python3
"""
Module: dude.voice.stt
Purpose: Speech-to-text protocol + Whisper backend (spec v0.2 §6 voice
         phase; user requirement: "two-way voice streaming, whisper is
         fine").

The protocol is the contract; backends are resolved at startup:
  1. faster-whisper (local CTranslate2 Whisper) if importable —
     preferred: audio never leaves the machine, which matters for this
     product's threat model (review A19).
  2. Nothing -> resolve_stt() returns None and the surface refuses
     voice capture visibly (fail closed; text capture still works).

A future cloud Whisper (OpenAI API) backend belongs behind the same
protocol and requires the privacy data-flow review before enabling.

Safety Critical: True — a dropped or fabricated transcript is user
evidence lost or invented; the safety floor scans what this returns.
Psychologically Critical: True

Never-suppress-error: transcription failures raise VoiceUnavailable
with the original cause; nothing returns an empty transcript on error.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import io
import logging
import os
from typing import Protocol

from pydantic import Field

from dude.data.base import DudeModel

LOGGER = logging.getLogger("dude.voice.stt")

# Model size is an env knob; "base" keeps first-run download small while
# remaining usable for conversational dictation. Larger models are a
# deployment decision, not a code change.
WHISPER_MODEL_ENV = "DUDE_WHISPER_MODEL"
DEFAULT_WHISPER_MODEL = "base"


class VoiceUnavailable(Exception):
    """No usable STT/TTS backend, or a backend failed mid-utterance."""


class TranscriptSegment(DudeModel):
    """One transcribed span. Confidence is internal float material — the
    surface renders text, never fake precision."""

    text: str
    start_seconds: float = Field(ge=0.0, default=0.0)
    end_seconds: float = Field(ge=0.0, default=0.0)
    confidence: float | None = None


class SpeechToText(Protocol):
    """STT contract: full-utterance transcription of a WAV/PCM payload.

    Streaming is implemented at the transport layer (the websocket
    accumulates chunks and transcribes on utterance end); backends that
    support true incremental decoding may transcribe partials with the
    same signature on partial buffers."""

    def transcribe(self, audio: bytes) -> list[TranscriptSegment]: ...


class WhisperLocalSTT:
    """Local Whisper via faster-whisper. Lazy import: the dependency is
    optional and its absence must produce a refusal, not an ImportError
    at package import time."""

    def __init__(self, model_name: str | None = None) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceUnavailable(
                "faster-whisper is not installed; voice capture is "
                "unavailable (pip install faster-whisper)."
            ) from exc
        name = model_name or os.environ.get(WHISPER_MODEL_ENV, DEFAULT_WHISPER_MODEL)
        LOGGER.info("Loading local Whisper model %r", name)
        self._model = WhisperModel(name, device="auto", compute_type="auto")

    def transcribe(self, audio: bytes) -> list[TranscriptSegment]:
        if not audio:
            raise VoiceUnavailable("Empty audio payload; nothing to transcribe.")
        try:
            segments, _info = self._model.transcribe(io.BytesIO(audio))
            return [
                TranscriptSegment(
                    text=s.text.strip(),
                    start_seconds=float(s.start),
                    end_seconds=float(s.end),
                    confidence=(
                        float(s.avg_logprob) if s.avg_logprob is not None else None
                    ),
                )
                for s in segments
                if s.text.strip()
            ]
        except Exception as exc:
            LOGGER.error("Whisper transcription failed: %s", exc)
            raise VoiceUnavailable(f"Transcription failed: {exc}") from exc


def resolve_stt() -> SpeechToText | None:
    """Best available backend, or None (surface must refuse visibly)."""
    try:
        return WhisperLocalSTT()
    except VoiceUnavailable as exc:
        LOGGER.warning("No STT backend: %s", exc)
        return None
