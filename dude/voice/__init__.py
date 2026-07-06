#!/usr/bin/env python3
"""
Module: dude.voice
Purpose: Two-way voice for DUDE capture — pluggable speech-to-text
         (Whisper) and text-to-speech behind typed protocols.

Voice is a TRANSPORT, not a fork: every transcript enters the same
capture path as typed text, so the safety floor scans spoken input
exactly as it scans typed input (spec v0.2 I1). No backend, no fake
transcript: a missing engine is a visible refusal, never silence.

Safety Critical: False
Psychologically Critical: False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = False

from dude.voice.stt import (
    SpeechToText,
    TranscriptSegment,
    VoiceUnavailable,
    WhisperLocalSTT,
    resolve_stt,
)
from dude.voice.tts import TextToSpeech, resolve_tts

__all__ = [
    "SpeechToText",
    "TextToSpeech",
    "TranscriptSegment",
    "VoiceUnavailable",
    "WhisperLocalSTT",
    "resolve_stt",
    "resolve_tts",
]
