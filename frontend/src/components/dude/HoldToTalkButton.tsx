/**
 * HoldToTalkButton — the primary DUDE gesture (mobile vision v0.1).
 *
 * A large circular press-and-hold control sized for a thumb. Pointer
 * events unify touch/pen/mouse; `touch-action: none`, user-select
 * suppression, and context-menu/touch-callout prevention keep iOS
 * long-press behaviors (scroll, magnifier, callout) from stealing the
 * hold in a standalone PWA.
 *
 * State copy here is interaction chrome only ("Hold to talk",
 * "Release to send", "structuring…") — everything the engine says
 * arrives as backend frames and renders verbatim elsewhere.
 */

"use client";

import { Loader2, Mic } from "lucide-react";

import type { HoldToTalkState } from "@/lib/useHoldToTalk";

const SIZE_CLASSES = {
  // Home screen: the screen's one instrument.
  large: "h-40 w-40",
  // Case screen: capture-first, but sharing the screen with the record.
  compact: "h-28 w-28",
} as const;

function stateLabel(voice: HoldToTalkState): string {
  if (voice.recording) return "Release to send";
  if (voice.structuring) return "structuring…";
  if (voice.sending) return "Listening to the reply…";
  return "Hold to talk";
}

export function HoldToTalkButton({
  voice,
  size = "large",
}: {
  voice: HoldToTalkState;
  size?: keyof typeof SIZE_CLASSES;
}) {
  const busy = voice.sending || voice.structuring;

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative">
        {voice.recording && (
          // Recording indicator: a slow pulse ring around the held button.
          <span
            aria-hidden
            className="absolute -inset-3 animate-ping rounded-full bg-red-500/25"
          />
        )}
        <button
          type="button"
          aria-label="Hold to talk"
          aria-pressed={voice.recording}
          disabled={busy && !voice.recording}
          onPointerDown={(event) => {
            event.preventDefault();
            void voice.start();
          }}
          onPointerUp={voice.stop}
          onPointerLeave={voice.stop}
          onPointerCancel={voice.stop}
          onContextMenu={(event) => event.preventDefault()}
          style={{ WebkitTouchCallout: "none" }}
          className={`relative flex ${SIZE_CLASSES[size]} touch-none select-none items-center justify-center rounded-full border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300/60 disabled:cursor-not-allowed disabled:opacity-50 ${
            voice.recording
              ? "border-red-400/70 bg-red-500/25 text-red-100 shadow-[0_0_60px_rgba(239,68,68,0.35)]"
              : "border-violet-400/50 bg-violet-500/20 text-violet-100 shadow-[0_0_60px_rgba(139,92,246,0.25)] active:bg-violet-500/35"
          }`}
        >
          {busy && !voice.recording ? (
            <Loader2
              className={`animate-spin ${size === "large" ? "h-12 w-12" : "h-8 w-8"}`}
            />
          ) : (
            <Mic className={size === "large" ? "h-12 w-12" : "h-8 w-8"} />
          )}
        </button>
      </div>
      <p
        role="status"
        className={`text-sm font-medium ${
          voice.recording
            ? "text-red-200"
            : busy
              ? "text-violet-200"
              : "text-muted-foreground"
        }`}
      >
        {stateLabel(voice)}
      </p>
    </div>
  );
}
