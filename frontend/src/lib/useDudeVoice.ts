/**
 * useDudeVoice — hold-to-talk voice capture for a DUDE case.
 *
 * Press-and-hold: `start()` opens the microphone and a MediaRecorder
 * (audio/webm where supported); `stop()` finalizes the utterance and sends
 * the accumulated audio through the voice bridge
 * (`/api/dude/voice/[caseId]`), which relays it over the authenticated
 * backend WebSocket and streams frames back as NDJSON. Frames are surfaced
 * to the caller in arrival order via `onFrame`; a binary WAV reply arrives
 * as an `audio` frame and is played here.
 *
 * WHY the WebSocket itself lives server-side: the backend authenticates
 * the WS handshake with an X-API-Key header, which a browser WebSocket
 * cannot send — and the key must never reach the browser. The bridge owns
 * the socket; this hook owns the microphone and the frame stream.
 *
 * FAIL CLOSED, VISIBLY: every failure path (mic denied, recorder
 * unsupported, transport error, non-OK response) emits a `refusal` frame —
 * the UI never pretends voice worked (spec v0.2 I12).
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { InstantRead, SafetyPayload } from "@/lib/dudeApi";

export type VoiceFrame =
  | { type: "transcript"; text: string; capture_id?: string }
  | ({ type: "safety" } & SafetyPayload)
  // Deterministic capture-time first read — never sent on a crisis
  // utterance (the backend omits it; crisis owns the moment).
  | ({ type: "instant_read" } & InstantRead)
  | { type: "reply"; text: string }
  | { type: "refusal"; reason: string }
  | { type: "audio"; wav_base64: string }
  // Emitted only by the no-case bridge (caseId = VOICE_NO_CASE): the
  // utterance was filed into a freshly created, transcript-titled case.
  | { type: "case"; case_id: string; title: string };

/**
 * Pseudo case id routing an utterance to the no-case bridge
 * (`/api/dude/voice/new`), which transcribes it, creates a case titled
 * from the transcript, attaches it, and emits a `case` frame.
 */
export const VOICE_NO_CASE = "new";

interface UseDudeVoiceResult {
  /** True while the microphone is capturing (button held down). */
  recording: boolean;
  /** True while an utterance is in flight to/through the bridge. */
  sending: boolean;
  /** Begin recording (call on press). */
  start: () => Promise<void>;
  /** Stop recording and send the utterance (call on release). */
  stop: () => void;
}

const REFUSAL = (reason: string): VoiceFrame => ({ type: "refusal", reason });

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const candidate of ["audio/webm", "audio/wav", "audio/mp4"]) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate;
  }
  return "";
}

function playWav(base64: string): void {
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  const audio = new Audio(url);
  audio.addEventListener("ended", () => URL.revokeObjectURL(url));
  // Playback failure is non-fatal: the reply text already rendered.
  void audio.play().catch(() => URL.revokeObjectURL(url));
}

export function useDudeVoice(
  caseId: string,
  onFrame: (frame: VoiceFrame) => void
): UseDudeVoiceResult {
  const [recording, setRecording] = useState(false);
  const [sending, setSending] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // Keep the latest callback without re-binding recorder handlers.
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;

  const releaseMicrophone = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  useEffect(() => releaseMicrophone, [releaseMicrophone]);

  const sendUtterance = useCallback(
    async (blob: Blob) => {
      setSending(true);
      try {
        const response = await fetch(
          `/api/dude/voice/${encodeURIComponent(caseId)}`,
          {
            method: "POST",
            headers: { "Content-Type": blob.type || "application/octet-stream" },
            body: blob,
          }
        );
        if (!response.ok || !response.body) {
          onFrameRef.current(
            REFUSAL(`Voice request failed (${response.status}).`)
          );
          return;
        }
        // NDJSON: one frame per line, streamed as the backend produces them.
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffered = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffered += decoder.decode(value, { stream: true });
          const lines = buffered.split("\n");
          buffered = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            let frame: VoiceFrame;
            try {
              frame = JSON.parse(line) as VoiceFrame;
            } catch {
              continue; // Never invent content from a corrupt frame.
            }
            if (frame.type === "audio") {
              playWav(frame.wav_base64);
            }
            onFrameRef.current(frame);
          }
        }
      } catch {
        onFrameRef.current(
          REFUSAL("Voice request could not reach the server.")
        );
      } finally {
        setSending(false);
      }
    },
    [caseId]
  );

  const start = useCallback(async () => {
    if (recorderRef.current || sending) return;
    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      onFrameRef.current(
        REFUSAL("Voice capture is not supported in this browser.")
      );
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      onFrameRef.current(REFUSAL("Microphone access was denied."));
      return;
    }
    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined
      );
    } catch {
      stream.getTracks().forEach((track) => track.stop());
      onFrameRef.current(REFUSAL("Audio recording could not be started."));
      return;
    }

    chunksRef.current = [];
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    });
    recorder.addEventListener("stop", () => {
      const blob = new Blob(chunksRef.current, {
        type: recorder.mimeType || mimeType || "application/octet-stream",
      });
      chunksRef.current = [];
      releaseMicrophone();
      setRecording(false);
      if (blob.size === 0) {
        onFrameRef.current(REFUSAL("No audio was recorded."));
        return;
      }
      void sendUtterance(blob);
    });

    recorderRef.current = recorder;
    streamRef.current = stream;
    recorder.start(250); // Accumulate small chunks while the button is held.
    setRecording(true);
  }, [releaseMicrophone, sendUtterance, sending]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    if (recorder.state !== "inactive") {
      recorder.stop();
    } else {
      releaseMicrophone();
      setRecording(false);
    }
  }, [releaseMicrophone]);

  return { recording, sending, start, stop };
}
