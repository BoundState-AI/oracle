/**
 * CaseWorkspace — the DUDE case screen: capture (text + hold-to-talk
 * voice), analyze, and the latest analysis.
 *
 * Design contract (spec v0.2 I1/I2, §5):
 *   - Safety output renders at the TOP, before any other content, and is
 *     never hidden, collapsed, or auto-dismissed (SafetyBanner).
 *   - Backend copy renders VERBATIM — capture acks, safety messages,
 *     replies, refusals, and the analysis summary are backend strings.
 *     This component owns UI chrome labels only ("Capture", "Analyze",
 *     "Timeline", "Hold to talk").
 *   - served_prior renders the evidence-state badge
 *     "No new data — showing last analysis" — exactly that, nothing about
 *     the user.
 *   - A voice refusal renders its reason plainly; voice is never faked.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Compass,
  Loader2,
  Mic,
  Scale,
  Send,
  ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

import { SafetyBanner } from "@/components/dude/SafetyBanner";
import {
  analyzeCase,
  captureText,
  fetchCases,
  type AnalysisMode,
  type AnalyzeResponse,
  type SafetyPayload,
} from "@/lib/dudeApi";
import { useDudeVoice, type VoiceFrame } from "@/lib/useDudeVoice";

const MODE_LABELS: Record<AnalysisMode, string> = {
  new_evidence: "new_evidence",
  new_hypothesis_reanalysis: "new_hypothesis_reanalysis",
  scope_change: "scope_change",
  no_new_data: "no_new_data",
};

// Exact evidence-state copy required for served_prior (no paraphrase).
const SERVED_PRIOR_BADGE = "No new data — showing last analysis";

interface TimelineEntry {
  id: number;
  kind: "capture" | "transcript" | "reply" | "refusal";
  text: string;
}

const TIMELINE_CHROME: Record<TimelineEntry["kind"], string> = {
  capture: "Capture",
  transcript: "Transcript",
  reply: "Reply",
  refusal: "Voice refusal",
};

export function CaseWorkspace({ caseId }: { caseId: string }) {
  const [title, setTitle] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<SafetyPayload[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [text, setText] = useState("");
  const [capturing, setCapturing] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const nextEntryId = useRef(0);

  useEffect(() => {
    fetchCases()
      .then((cases) => {
        const match = cases.find((c) => c.case_id === caseId);
        setTitle(match ? match.title : caseId);
      })
      .catch(() => setTitle(caseId));
  }, [caseId]);

  const appendEntry = useCallback(
    (kind: TimelineEntry["kind"], entryText: string) => {
      setTimeline((entries) => [
        { id: nextEntryId.current++, kind, text: entryText },
        ...entries,
      ]);
    },
    []
  );

  // Never remove, always surface: exact duplicates collapse into one so a
  // repeated crisis fires once visually, but nothing is ever dismissed.
  const appendAlert = useCallback((payload: SafetyPayload) => {
    setAlerts((current) => {
      const key = JSON.stringify(payload);
      if (current.some((existing) => JSON.stringify(existing) === key)) {
        return current;
      }
      return [...current, payload];
    });
  }, []);

  const handleVoiceFrame = useCallback(
    (frame: VoiceFrame) => {
      switch (frame.type) {
        case "transcript":
          appendEntry("transcript", frame.text);
          break;
        case "safety":
          // Any safety frame renders prominently — crisis or chronic flags.
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
        case "refusal":
          appendEntry("refusal", frame.reason);
          break;
        case "audio":
          break; // Played by the hook; the reply text is already rendered.
      }
    },
    [appendAlert, appendEntry]
  );

  const voice = useDudeVoice(caseId, handleVoiceFrame);

  const handleCapture = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || capturing) return;
    setCapturing(true);
    try {
      const response = await captureText(caseId, trimmed);
      setText("");
      // The backend acknowledgement message renders verbatim.
      appendEntry("capture", response.message);
      if (response.crisis || response.flags.length > 0) {
        appendAlert({
          crisis: response.crisis,
          message: response.message,
          flags: response.flags,
          resources: response.resources,
        });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Capture failed");
    } finally {
      setCapturing(false);
    }
  }, [text, capturing, caseId, appendEntry, appendAlert]);

  const handleAnalyze = useCallback(async () => {
    if (analyzing) return;
    setAnalyzing(true);
    try {
      setAnalysis(await analyzeCase(caseId));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Analyze failed");
    } finally {
      setAnalyzing(false);
    }
  }, [analyzing, caseId]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-10%] top-[-8rem] h-80 w-80 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-72 bg-[radial-gradient(circle_at_top,rgba(139,92,246,0.12),transparent_55%)]" />
      </div>

      {/* Safety output renders before ALL other content — even the header. */}
      <SafetyBanner alerts={alerts} />
      {analysis?.crisis_active && (
        <div role="alert" className="border-b-2 border-red-500/60 bg-red-950/60">
          <div className="mx-auto flex max-w-4xl items-start gap-3 px-6 py-5">
            <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0 text-red-300" />
            {/* Crisis-active analysis copy, verbatim from the backend. */}
            <p className="whitespace-pre-wrap text-base font-medium leading-7 text-red-50">
              {analysis.summary}
            </p>
          </div>
        </div>
      )}

      <header className="border-b border-border/80 bg-background/70 backdrop-blur-sm">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <Compass className="h-5 w-5 shrink-0 text-violet-400" />
            <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              DUDE
            </span>
            <span className="truncate text-sm font-medium text-foreground">
              {title ?? "…"}
            </span>
          </div>
          <Link
            href="/dude"
            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border border-border px-4 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            <ArrowLeft className="h-4 w-4" />
            Cases
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-8 px-6 py-10">
        <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6 shadow-lg shadow-slate-950/10">
          <h1 className="text-lg font-semibold text-foreground">Capture</h1>
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="What happened? Facts, messages, dates — raw material."
            rows={4}
            className="mt-4 w-full resize-y rounded-lg border border-border bg-background px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-violet-400/40"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void handleCapture()}
              disabled={!text.trim() || capturing}
              className="inline-flex h-11 items-center gap-2 rounded-lg bg-violet-500 px-5 text-sm font-semibold text-white transition-colors hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {capturing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Capture
            </button>
            <button
              type="button"
              onPointerDown={(event) => {
                event.preventDefault();
                void voice.start();
              }}
              onPointerUp={voice.stop}
              onPointerLeave={voice.stop}
              onPointerCancel={voice.stop}
              onContextMenu={(event) => event.preventDefault()}
              disabled={voice.sending}
              className={`inline-flex h-11 touch-none select-none items-center gap-2 rounded-lg border px-5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                voice.recording
                  ? "border-red-400/60 bg-red-500/20 text-red-200"
                  : "border-violet-400/40 bg-violet-400/10 text-violet-200 hover:bg-violet-400/20"
              }`}
            >
              {voice.sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Mic className="h-4 w-4" />
              )}
              {voice.recording
                ? "Recording — release to send"
                : voice.sending
                  ? "Sending…"
                  : "Hold to talk"}
            </button>
            <button
              type="button"
              onClick={() => void handleAnalyze()}
              disabled={analyzing}
              className="ml-auto inline-flex h-11 items-center gap-2 rounded-lg border border-border px-5 text-sm font-semibold text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              {analyzing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Scale className="h-4 w-4" />
              )}
              Analyze
            </button>
          </div>
        </section>

        {analysis && (
          <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6">
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">
                Analysis
              </h2>
              <span className="rounded-full border border-violet-400/25 bg-violet-400/10 px-3 py-0.5 text-[10px] font-medium uppercase tracking-[0.2em] text-violet-200">
                {MODE_LABELS[analysis.mode] ?? analysis.mode}
              </span>
              {analysis.served_prior && (
                <span className="rounded-full border border-border bg-secondary px-3 py-0.5 text-[11px] font-medium text-secondary-foreground">
                  {SERVED_PRIOR_BADGE}
                </span>
              )}
              <span className="ml-auto text-xs text-muted-foreground">
                run {analysis.run_id}
              </span>
            </div>
            {/* The summary is backend copy and renders verbatim. */}
            <p className="whitespace-pre-wrap text-sm leading-7 text-foreground">
              {analysis.summary}
            </p>
          </section>
        )}

        {timeline.length > 0 && (
          <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6">
            <h2 className="text-base font-semibold text-foreground">
              Timeline
            </h2>
            <ul className="mt-4 space-y-3">
              {timeline.map((entry) => (
                <li
                  key={entry.id}
                  className={`rounded-xl border p-4 ${
                    entry.kind === "refusal"
                      ? "border-destructive/50 bg-destructive/10"
                      : "border-border/60 bg-background/40"
                  }`}
                >
                  <p
                    className={`text-[10px] font-semibold uppercase tracking-[0.2em] ${
                      entry.kind === "refusal"
                        ? "text-red-300"
                        : "text-muted-foreground"
                    }`}
                  >
                    {TIMELINE_CHROME[entry.kind]}
                  </p>
                  {/* Entry text is backend copy (ack, transcript, reply,
                      refusal reason) rendered verbatim. */}
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
      </main>
    </div>
  );
}
