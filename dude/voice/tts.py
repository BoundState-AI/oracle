#!/usr/bin/env python3
"""
Module: dude.voice.tts
Purpose: Text-to-speech protocol + local backend for the "two-way" half
         of voice capture.

Local-first for the same reason as STT (review A19: this product's
transcripts are its most sensitive data; round-tripping them through a
cloud voice API is a privacy decision, not a default). Backend order:
  1. espeak-ng / espeak binary if present (ubiquitous, offline).
  2. Nothing -> resolve_tts() returns None; the surface stays two-way in
     text and says why audio is absent.

Safety Critical: False — TTS renders already-vetted copy; the
banned-phrase floor ran upstream.
Psychologically Critical: False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = False

import logging
import shutil
import subprocess
from typing import Protocol

from dude.voice.stt import VoiceUnavailable

LOGGER = logging.getLogger("dude.voice.tts")

_ESPEAK_TIMEOUT_SECONDS = 30


class TextToSpeech(Protocol):
    """TTS contract: text in, WAV bytes out."""

    def synthesize(self, text: str) -> bytes: ...


class EspeakTTS:
    """Offline TTS via the espeak-ng/espeak binary."""

    def __init__(self) -> None:
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if binary is None:
            raise VoiceUnavailable(
                "No espeak-ng/espeak binary found; spoken replies are "
                "unavailable (text replies still work)."
            )
        self._binary = binary

    def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise VoiceUnavailable("Empty text; nothing to synthesize.")
        try:
            result = subprocess.run(
                [self._binary, "--stdout", text],
                capture_output=True,
                check=True,
                timeout=_ESPEAK_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.error("TTS synthesis failed: %s", exc)
            raise VoiceUnavailable(f"TTS synthesis failed: {exc}") from exc
        return result.stdout


def resolve_tts() -> TextToSpeech | None:
    """Best available backend, or None (reply stays text-only)."""
    try:
        return EspeakTTS()
    except VoiceUnavailable as exc:
        LOGGER.warning("No TTS backend: %s", exc)
        return None
