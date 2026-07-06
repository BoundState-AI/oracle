/**
 * DudeWorkspace — the DUDE home screen: "Something happened."
 *
 * Mobile vision v0.1: the first screen is capture, not case management.
 * A wordmark, one thumb-sized hold-to-talk button, a "What happened?"
 * text fallback, and recent cases with one-line evidence-state statuses.
 * No dashboard chrome, no marketing — this screen is installed as an
 * iPhone PWA and used mid-threat-spiral.
 *
 * Product rules preserved from the case surface:
 *  - safety output renders above everything else and is never
 *    dismissible (SafetyBanner);
 *  - engine copy (transcripts, replies, acks, refusal reasons) is
 *    backend copy rendered VERBATIM; chrome never describes the user;
 *  - a voice refusal shows its reason and hands the moment to the text
 *    input — voice is never faked (spec v0.2 I12).
 *
 * A no-case utterance goes through the no-case bridge (VOICE_NO_CASE):
 * transcript → new case titled from its first ~6 words → attached. The
 * typed path files itself the same way via createCase + captureText.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { HoldToTalkButton } from "@/components/dude/HoldToTalkButton";
import { SafetyBanner, withAlert } from "@/components/dude/SafetyBanner";
import {
  captureText,
  createCase,
  fetchCases,
  type DudeCase,
  type SafetyPayload,
} from "@/lib/dudeApi";
import { titleFromUtterance, VOICE_INTAKE_TITLE } from "@/lib/dudeCaseTitle";
import { evidenceStateLine } from "@/lib/dudeEvidenceState";
import { useHoldToTalk } from "@/lib/useHoldToTalk";
import { VOICE_NO_CASE, type VoiceFrame } from "@/lib/useDudeVoice";

interface MomentEntry {
  id: number;
  kind: "capture" | "transcript" | "reply" | "refusal";
  text: string;
}

// Structural labels only; the text under each is backend copy, verbatim.
const ENTRY_CHROME: Record<MomentEntry["kind"], string> = {
  capture: "Captured",
  transcript: "Transcript",
  reply: "Reply",
  refusal: "Voice refusal",
};

interface FiledCase {
  case_id: string;
  title: string;
}

export function DudeWorkspace() {
  const [cases, setCases] = useState<DudeCase[]>([]);
  const [loadingCases, setLoadingCases] = useState(true);
  const [alerts, setAlerts] = useState<SafetyPayload[]>([]);
  const [entries, setEntries] = useState<MomentEntry[]>([]);
  const [filedCase, setFiledCase] = useState<FiledCase | null>(null);
  const [text, setText] = useState("");
  const [filing, setFiling] = useState(false);

  const nextEntryId = useRef(0);
  const textInputRef = useRef<HTMLInputElement>(null);
  // Per-utterance memory: on a refusal after transcription but before the
  // case existed, the transcript falls back into the text input so the
  // words are never lost.
  const utteranceTranscript = useRef<string | null>(null);
  const utteranceFiled = useRef(false);

  const refreshCases = useCallback(() => {
    fetchCases()
      .then(setCases)
      .catch(() => toast.error("Could not load cases"))
      .finally(() => setLoadingCases(false));
  }, []);

  useEffect(() => {
    refreshCases();
  }, [refreshCases]);

  const appendEntry = useCallback(
    (kind: MomentEntry["kind"], entryText: string) => {
      setEntries((current) => [
        { id: nextEntryId.current++, kind, text: entryText },
        ...current,
      ]);
    },
    []
  );

  const appendAlert = useCallback((payload: SafetyPayload) => {
    setAlerts((current) => withAlert(current, payload));
  }, []);

  const handleVoiceFrame = useCallback(
    (frame: VoiceFrame) => {
      switch (frame.type) {
        case "transcript":
          utteranceTranscript.current = frame.text;
          appendEntry("transcript", frame.text);
          break;
        case "safety":
          appendAlert({
            crisis: frame.crisis,
            message: frame.message,
            flags: frame.flags,
            resources: frame.resources,
          });
          break;
        case "reply":
          appendEntry("reply", frame.text);
          break;
        case "case":
          utteranceFiled.current = true;
          setFiledCase({ case_id: frame.case_id, title: frame.title });
          refreshCases();
          break;
        case "refusal":
          appendEntry("refusal", frame.reason);
          // Fall back to the text path: keep the transcribed words if the
          // filing failed, and put the cursor where typing works.
          if (utteranceTranscript.current && !utteranceFiled.current) {
            setText(utteranceTranscript.current);
          }
          textInputRef.current?.focus();
          break;
        case "audio":
          break; // Played by the hook; the reply text already rendered.
      }
    },
    [appendAlert, appendEntry, refreshCases]
  );

  const voice = useHoldToTalk(VOICE_NO_CASE, handleVoiceFrame);

  const startUtterance = useCallback(() => {
    utteranceTranscript.current = null;
    utteranceFiled.current = false;
    return voice.start();
  }, [voice]);

  const handleTextSubmit = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || filing) return;
    setFiling(true);
    try {
      // Same filing rule as voice: title from the first ~6 words, the
      // full text attached as the case's first capture.
      const title = titleFromUtterance(trimmed);
      const { case_id } = await createCase(title);
      const response = await captureText(case_id, trimmed);
      setText("");
      appendEntry("capture", response.message);
      if (response.crisis || response.flags.length > 0) {
        appendAlert({
          crisis: response.crisis,
          message: response.message,
          flags: response.flags,
          resources: response.resources,
        });
      }
      setFiledCase({ case_id, title });
      refreshCases();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not file it");
    } finally {
      setFiling(false);
    }
  }, [text, filing, appendEntry, appendAlert, refreshCases]);

  const visibleCases = cases.filter(
    // The voice-intake case is bridge plumbing, never a user case.
    (dudeCase) => dudeCase.title !== VOICE_INTAKE_TITLE
  );

  return (
    <div className="min-h-dvh bg-background pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] text-foreground">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-[-6rem] h-96 w-96 -translate-x-1/2 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-80 bg-[radial-gradient(circle_at_top,rgba(139,92,246,0.14),transparent_60%)]" />
      </div>

      {/* Safety output renders before ALL other content, always. */}
      <SafetyBanner alerts={alerts} />

      <main className="mx-auto w-full max-w-md px-6 pt-[calc(env(safe-area-inset-top)+3.5rem)]">
        <section className="flex flex-col items-center gap-8 text-center">
          <h1 className="pl-[0.35em] font-mono text-5xl font-semibold tracking-[0.35em] text-foreground">
            DUDE
          </h1>

          <HoldToTalkButton
            voice={{ ...voice, start: startUtterance }}
            size="large"
          />

          <form
            className="w-full"
            onSubmit={(event) => {
              event.preventDefault();
              void handleTextSubmit();
            }}
          >
            <label
              htmlFor="dude-what-happened"
              className="block text-lg font-medium text-foreground"
            >
              What happened?
            </label>
            <div className="mt-3 flex gap-2">
              <input
                id="dude-what-happened"
                ref={textInputRef}
                type="text"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Type it instead"
                autoComplete="off"
                className="h-13 w-full rounded-xl border border-border bg-card/70 px-4 text-base text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-violet-400/40"
              />
              <button
                type="submit"
                disabled={!text.trim() || filing}
                aria-label="File it"
                className="flex h-13 w-14 shrink-0 items-center justify-center rounded-xl bg-violet-500 text-white transition-colors hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {filing ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <ArrowUpRight className="h-5 w-5" />
                )}
              </button>
            </div>
          </form>
        </section>

        {(filedCase || entries.length > 0) && (
          <section className="mt-10 space-y-3">
            {filedCase && (
              <Link
                href={`/dude/case/${encodeURIComponent(filedCase.case_id)}`}
                className="flex min-h-14 items-center justify-between gap-3 rounded-2xl border border-violet-400/40 bg-violet-500/10 px-4 py-3 transition-colors hover:bg-violet-500/20"
              >
                <span className="min-w-0">
                  <span className="block text-[10px] font-semibold uppercase tracking-[0.2em] text-violet-300">
                    Filed as
                  </span>
                  <span className="block truncate text-sm font-medium text-foreground">
                    {filedCase.title}
                  </span>
                </span>
                <ArrowUpRight className="h-5 w-5 shrink-0 text-violet-300" />
              </Link>
            )}
            <ul className="space-y-2">
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  className={`rounded-2xl border px-4 py-3 ${
                    entry.kind === "refusal"
                      ? "border-destructive/50 bg-destructive/10"
                      : "border-border/60 bg-card/60"
                  }`}
                >
                  <p
                    className={`text-[10px] font-semibold uppercase tracking-[0.2em] ${
                      entry.kind === "refusal"
                        ? "text-red-300"
                        : "text-muted-foreground"
                    }`}
                  >
                    {ENTRY_CHROME[entry.kind]}
                  </p>
                  {/* Backend copy (transcript, reply, ack, refusal reason)
                      rendered verbatim. */}
                  <p
                    className={`mt-1 whitespace-pre-wrap text-sm leading-6 ${
                      entry.kind === "refusal"
                        ? "text-red-100/90"
                        : "text-foreground"
                    }`}
                  >
                    {entry.text}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="mt-12 pb-10">
          <h2 className="text-xs font-semibold uppercase tracking-[0.25em] text-muted-foreground">
            Recent cases
          </h2>
          {loadingCases ? (
            <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </p>
          ) : visibleCases.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">No cases yet.</p>
          ) : (
            <ul className="mt-3 divide-y divide-border/50">
              {visibleCases.map((dudeCase) => (
                <li key={dudeCase.case_id}>
                  <Link
                    href={`/dude/case/${encodeURIComponent(dudeCase.case_id)}`}
                    className="block min-h-14 rounded-xl px-3 py-3.5 transition-colors hover:bg-accent active:bg-accent"
                  >
                    <span className="block truncate text-base font-medium text-foreground">
                      {dudeCase.title}
                    </span>
                    <span className="mt-0.5 block text-sm text-muted-foreground">
                      {evidenceStateLine(dudeCase.case_id)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  );
}
