/**
 * useHoldToTalk — hold-to-talk interaction state on top of useDudeVoice.
 *
 * Adds the release-phase truth the mobile vision demands: while the
 * button is held the mic is visibly recording; the moment it is released
 * the UI shows "structuring…" until the first backend frame arrives
 * (transcript or refusal). The screen never sits silent and never
 * pretends — a refusal frame is the only way "structuring…" resolves
 * without content.
 */

"use client";

import { useCallback, useState } from "react";

import { useDudeVoice, type VoiceFrame } from "@/lib/useDudeVoice";

export interface HoldToTalkState {
  /** True while the microphone is capturing (button held down). */
  recording: boolean;
  /** True while an utterance is in flight to/through the bridge. */
  sending: boolean;
  /** True from release until the utterance's first frame arrives. */
  structuring: boolean;
  /** Begin recording (call on press). */
  start: () => Promise<void>;
  /** Stop recording and send the utterance (call on release). */
  stop: () => void;
}

export function useHoldToTalk(
  caseId: string,
  onFrame: (frame: VoiceFrame) => void
): HoldToTalkState {
  const [structuring, setStructuring] = useState(false);

  // useDudeVoice keeps the latest handler in its own ref, so binding on
  // `onFrame` identity here never re-binds recorder handlers downstream.
  const handleFrame = useCallback(
    (frame: VoiceFrame) => {
      setStructuring(false); // First frame arrived: the backend is talking.
      onFrame(frame);
    },
    [onFrame]
  );

  const voice = useDudeVoice(caseId, handleFrame);

  const stop = useCallback(() => {
    // Only a release that actually ends a recording enters "structuring…"
    // — pointer-leave after the recorder already stopped changes nothing.
    if (voice.recording) setStructuring(true);
    voice.stop();
  }, [voice]);

  // A stream that ends without delivering a single frame must not strand
  // "structuring…" on screen. Derived from the sending transition during
  // render (React's previous-render pattern) — both bridges fail closed
  // with a refusal frame, so this net exists only for the pathological
  // all-frames-corrupt stream.
  const [prevSending, setPrevSending] = useState(voice.sending);
  if (prevSending !== voice.sending) {
    setPrevSending(voice.sending);
    if (!voice.sending && structuring) setStructuring(false);
  }

  return {
    recording: voice.recording,
    sending: voice.sending,
    structuring,
    start: voice.start,
    stop,
  };
}
