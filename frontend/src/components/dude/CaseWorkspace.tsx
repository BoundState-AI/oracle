/**
 * CaseWorkspace — the DUDE case screen, capture-first: hold-to-talk and
 * text capture at the top, then the latest analysis, then the timeline.
 *
 * Design contract (spec v0.2 I1/I2, §5 + mobile vision v0.1):
 *   - Safety output renders at the TOP, before any other content, and is
 *     never hidden, collapsed, or auto-dismissed (SafetyBanner).
 *   - Backend copy renders VERBATIM — capture acks, safety messages,
 *     replies, refusals, and the analysis summary are backend strings.
 *     This component owns UI chrome labels only ("Capture", "Analyze",
 *     "Timeline", hold-to-talk state).
 *   - served_prior renders the evidence-state badge
 *     "No new data — showing last analysis" — exactly that, nothing about
 *     the user.
 *   - A voice refusal renders its reason plainly and hands the moment to
 *     the text box; voice is never faked.
 *   - Each analysis mode is remembered locally so the home screen can
 *     speak the case's evidence-state line (dudeEvidenceState).
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Scale, Send, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { HoldToTalkButton } from "@/components/dude/HoldToTalkButton";
import { SafetyBanner, withAlert } from "@/components/dude/SafetyBanner";
import {
  analyzeCase,
  captureText,
  fetchCases,
  type AnalysisMode,
  type AnalyzeResponse,
  type SafetyPayload,
} from "@/lib/dudeApi";
import { rememberLastMode } from "@/lib/dudeEvidenceState";
import { useHoldToTalk } from "@/lib/useHoldToTalk";
import { type VoiceFrame } from "@/lib/useDudeVoice";

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
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

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

  const appendAlert = useCallback((payload: SafetyPayload) => {
    setAlerts((current) => withAlert(current, payload));
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
          // Voice failed: hand the moment to the text box, honestly.
          textAreaRef.current?.focus();
          break;
        case "case":
          break; // No-case-bridge frame; this screen is already a case.
        case "audio":
          break; // Played by the hook; the reply text is already rendered.
      }
    },
    [appendAlert, appendEntry]
  );

  const voice = useHoldToTalk(caseId, handleVoiceFrame);

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
      const result = await analyzeCase(caseId);
      setAnalysis(result);
      // Feed the home screen's evidence-state line for this case.
      rememberLastMode(caseId, result.mode);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Analyze failed");
    } finally {
      setAnalyzing(false);
    }
  }, [analyzing, caseId]);

  return (
    <div className="min-h-dvh bg-background pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] text-foreground">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-[-6rem] h-96 w-96 -translate-x-1/2 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-80 bg-[radial-gradient(circle_at_top,rgba(139,92,246,0.14),transparent_60%)]" />
      </div>

      {/* Safety output renders before ALL other content — even the header. */}
      <SafetyBanner alerts={alerts} />
      {analysis?.crisis_active && (
        <div role="alert" className="border-b-2 border-red-500/60 bg-red-950/60">
          <div className="mx-auto flex max-w-xl items-start gap-3 px-6 py-5">
            <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0 text-red-300" />
            {/* Crisis-active analysis copy, verbatim from the backend. */}
            <p className="whitespace-pre-wrap text-base font-medium leading-7 text-red-50">
              {analysis.summary}
            </p>
          </div>
        </div>
      )}

      <header className="pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex max-w-xl items-center gap-3 px-5 py-4">
          <Link
            href="/dude"
            aria-label="Back to DUDE"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-border text-foreground transition-colors hover:bg-accent active:bg-accent"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <h1 className="min-w-0 truncate text-base font-medium text-foreground">
            {title ?? "…"}
          </h1>
        </div>
      </header>

      <main className="mx-auto w-full max-w-xl space-y-6 px-5 pb-10 pt-2">
        {/* Capture first — the case screen opens on "something happened". */}
        <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5 shadow-lg shadow-slate-950/10">
          <div className="flex justify-center pt-2">
            <HoldToTalkButton voice={voice} size="compact" />
          </div>
          <textarea
            ref={textAreaRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="What happened? Facts, messages, dates — raw material."
            rows={3}
            className="mt-5 w-full resize-y rounded-xl border border-border bg-background px-4 py-3 text-base text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-violet-400/40"
          />
          <button
            type="button"
            onClick={() => void handleCapture()}
            disabled={!text.trim() || capturing}
            className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-violet-500 text-sm font-semibold text-white transition-colors hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
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
            onClick={() => void handleAnalyze()}
            disabled={analyzing}
            className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-violet-400/50 bg-violet-500/15 text-sm font-semibold text-violet-100 transition-colors hover:bg-violet-500/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {analyzing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Scale className="h-4 w-4" />
            )}
            Analyze
          </button>
        </section>

        {analysis && (
          <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5">
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
          <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5">
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
