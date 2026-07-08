/**
 * CaseWorkspace — the DUDE case screen, capture-first: hold-to-talk and
 * text capture at the top, then the PRIMARY Reality Check card, then the
 * collapsed "How the sausage is made" detail (Reality, Models, Timeline).
 *
 * Design contract (spec v0.2 I1/I2, §5 + mobile vision v0.1 + founder
 * brief "answer 'PTSD or real?' in five seconds"):
 *   - Safety output renders at the TOP, before any other content, and is
 *     never hidden, collapsed, or auto-dismissed (SafetyBanner).
 *   - Backend copy renders VERBATIM — capture acks, safety messages,
 *     replies, refusals, and the analysis summary are backend strings.
 *     This component owns UI chrome labels only ("Capture", "Analyze",
 *     "Timeline", "How the sausage is made", hold-to-talk state).
 *   - The Reality Check card (RealityCheck.tsx) is the default view; the
 *     epistemology — Reality, Models, Timeline — lives behind the sausage
 *     toggle, collapsed by default, its open state remembered per case in
 *     localStorage.
 *   - A voice refusal renders its reason plainly and hands the moment to
 *     the text box; voice is never faked.
 *   - Each analysis mode is remembered locally so the home screen can
 *     speak the case's evidence-state line (dudeEvidenceState).
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ChevronDown,
  Loader2,
  Scale,
  Send,
  ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

import { CalibrationLab } from "@/components/dude/CalibrationLab";
import { HoldToTalkButton } from "@/components/dude/HoldToTalkButton";
import { RealityCheck } from "@/components/dude/RealityCheck";
import {
  ModelsSection,
  RealitySection,
} from "@/components/dude/RealityModels";
import { SafetyBanner, withAlert } from "@/components/dude/SafetyBanner";
import {
  analyzeCase,
  captureText,
  fetchCaseDetail,
  fetchCases,
  type AnalyzeResponse,
  type CaseDetail,
  type InstantRead,
  type SafetyPayload,
} from "@/lib/dudeApi";
import { rememberLastMode } from "@/lib/dudeEvidenceState";
import { useHoldToTalk } from "@/lib/useHoldToTalk";
import { type VoiceFrame } from "@/lib/useDudeVoice";

// Per-case persistence for the sausage toggle — reopening a case restores
// whether its detail view was left expanded.
const SAUSAGE_OPEN_PREFIX = "dude:sausage-open:";

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
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [text, setText] = useState("");
  const [capturing, setCapturing] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  // The capture response's deterministic first read — shown until the
  // next analyze replaces it with the full Reality Check data.
  const [instantRead, setInstantRead] = useState<InstantRead | null>(null);
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

  // Reality + Models come from GET /cases/{id}. A failed refresh keeps the
  // last-known sections on screen rather than blanking them mid-session;
  // capture/analyze surface their own errors via toast, so this refresh
  // never double-reports.
  const refreshDetail = useCallback(async () => {
    try {
      setDetail(await fetchCaseDetail(caseId));
    } catch {
      // Intentionally quiet — see WHY above.
    }
  }, [caseId]);

  useEffect(() => {
    void refreshDetail();
  }, [refreshDetail]);

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
          // A crisis clears any earlier first read — crisis owns the
          // moment (the backend also stops sending instant_read frames).
          if (frame.crisis) setInstantRead(null);
          break;
        case "instant_read":
          // Deterministic first read on the spoken path, verbatim fields.
          setInstantRead(frame);
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
      // Instant first read, when the backend sent one. Absent on crisis
      // (crisis owns the moment) — clearing keeps no stale read around.
      setInstantRead(response.instant_read ?? null);
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
      // New evidence may have landed in Reality — refresh the sections.
      void refreshDetail();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Capture failed");
    } finally {
      setCapturing(false);
    }
  }, [text, capturing, caseId, appendEntry, appendAlert, refreshDetail]);

  const handleAnalyze = useCallback(async () => {
    if (analyzing) return;
    setAnalyzing(true);
    try {
      const result = await analyzeCase(caseId);
      setAnalysis(result);
      // The full Reality Check supersedes the capture-time first read.
      setInstantRead(null);
      // Feed the home screen's evidence-state line for this case.
      rememberLastMode(caseId, result.mode);
      // Hypotheses/bands may have moved — refresh Reality + Models.
      void refreshDetail();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Analyze failed");
    } finally {
      setAnalyzing(false);
    }
  }, [analyzing, caseId, refreshDetail]);

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

        {/* Instant first read from the last capture — deterministic cue
            resemblance, visually lighter than the Reality Check below.
            Cleared once the next analyze delivers the full picture. */}
        <InstantReadCard read={instantRead} />

        {/* PRIMARY view — "trigger or real?" answered in labeled rows.
            Proposal confirm/deny writes to the store, so the card asks
            for a detail refresh after each disposition. */}
        <RealityCheck
          detail={detail}
          analysis={analysis}
          onDetailChanged={() => void refreshDetail()}
        />

        {/* SECONDARY — the epistemology, collapsed by default. */}
        <SausageSection caseId={caseId} detail={detail} timeline={timeline} />

        {/* Lab: Trigger Calibration (spec v1 §8) — a sibling toggle. */}
        <CalibrationLab />
      </main>
    </div>
  );
}

/**
 * The capture-time first read: the backend's deterministic prefilter
 * result, rendered VERBATIM (hint band word, de-identified candidate
 * labels, vetted possibility/no-match note, exact evidence-effect line).
 * Deliberately lighter chrome than the Reality Check card — this is a
 * first read from cue resemblance, not the analysis, and the one chrome
 * caption says exactly that.
 */
function InstantReadCard({ read }: { read: InstantRead | null }) {
  if (!read) return null;
  return (
    <section className="rounded-2xl border border-border/60 bg-card/40 px-5 py-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
        Instant read — cue resemblance, not the analysis
      </p>
      {/* The backend hint word, verbatim (band words are the contract). */}
      <p className="mt-1 text-sm font-semibold text-foreground">
        Possible overlap: {read.overlap_hint.toUpperCase()}
      </p>
      {read.candidate_labels.length > 0 && (
        /* De-identified candidate family labels — backend copy, verbatim. */
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {read.candidate_labels.join(" · ")}
        </p>
      )}
      {/* Vetted template note (possible-overlap or no-match) — verbatim. */}
      <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
        {read.note}
      </p>
      {/* The exact evidence-effect line — verbatim, always shown. */}
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        {read.verdict_line}
      </p>
    </section>
  );
}

/**
 * The "How the sausage is made" toggle: Reality, Models, and Timeline —
 * everything the Reality Check card was computed from. Collapsed by
 * default; the open state persists per case in localStorage.
 */
function SausageSection({
  caseId,
  detail,
  timeline,
}: {
  caseId: string;
  detail: CaseDetail | null;
  timeline: TimelineEntry[];
}) {
  const [open, setOpen] = useState(false);

  // Restore in an effect, not the initial state — localStorage doesn't
  // exist during server render and the first client render must match it.
  useEffect(() => {
    try {
      setOpen(window.localStorage.getItem(SAUSAGE_OPEN_PREFIX + caseId) === "1");
    } catch {
      // Storage denied (private mode): the section simply starts closed.
    }
  }, [caseId]);

  const toggle = useCallback(() => {
    setOpen((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(
          SAUSAGE_OPEN_PREFIX + caseId,
          next ? "1" : "0"
        );
      } catch {
        // Storage denied: the toggle still works for this visit.
      }
      return next;
    });
  }, [caseId]);

  return (
    <section className="space-y-6">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-[1.75rem] border border-border/80 bg-card/70 px-5 py-4 text-sm font-semibold text-foreground transition-colors hover:bg-accent/40 active:bg-accent/40"
      >
        How the sausage is made
        <ChevronDown
          aria-hidden
          className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open && (
        <>
          {/* Reality + Models — the case's epistemic state. Both sections
              self-hide while their backend lists are empty. */}
          {detail && (
            <>
              <RealitySection
                observed={detail.observed}
                inferred={detail.inferred}
                unknown={detail.unknown}
              />
              <ModelsSection hypotheses={detail.hypotheses} />
            </>
          )}
          <TimelineSection timeline={timeline} />
        </>
      )}
    </section>
  );
}

function TimelineSection({ timeline }: { timeline: TimelineEntry[] }) {
  if (timeline.length === 0) return null;
  return (
    <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5">
      <h2 className="text-base font-semibold text-foreground">Timeline</h2>
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
  );
}
