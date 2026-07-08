/**
 * RealityCheck — the DUDE case screen's PRIMARY, default view. It answers
 * "am I reacting to PTSD or something real?" in the first five seconds
 * with labeled rows computed from GET /cases/{id}, not with epistemology.
 *
 * Design contract (spec v0.2 I1/I2 + founder brief):
 *   - Row LABELS are fixed, approved chrome ("REAL SIGNAL?",
 *     "PTSD OVERLAP?", "DOES PTSD OVERLAP MAKE THE SIGNAL FALSE?",
 *     "CAUSE", "IMMEDIATE DANGER", "WHAT WOULD SETTLE THIS"). Row values
 *     are computed chrome words; the only backend copy in this card —
 *     matched trigger names, the adjustment note, hypothesis titles,
 *     pursue-unknown statements, and the analysis summary — renders
 *     VERBATIM.
 *   - Confidence is WORDS, never numbers. The only numerals here are
 *     pattern counts ("N of M known patterns") — counts, not confidence.
 *   - served_prior LEADS the summary block with the exact evidence-state
 *     badge copy, above the mode badge and summary (same rule as the old
 *     Analysis panel this card absorbs).
 *   - IMMEDIATE DANGER only reflects run state. SafetyBanner (above all
 *     content, never dismissible) owns crisis copy and resources.
 */

import { type ReactNode } from "react";

import {
  type AnalyzeResponse,
  type CaseDetail,
  type Hypothesis,
  type LastRun,
} from "@/lib/dudeApi";

// Exact evidence-state copy required for served_prior (no paraphrase).
const SERVED_PRIOR_BADGE = "No new data — showing last analysis";

const ROW_LABEL =
  "text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground";

// Value tone hints at direction with color only — the words carry meaning.
const VALUE_TONES = {
  default: "text-foreground",
  good: "text-emerald-200",
  warn: "text-amber-200",
  danger: "text-red-200",
  muted: "text-muted-foreground",
} as const;

function Row({
  label,
  value,
  tone = "default",
  children,
}: {
  label: string;
  value: string;
  tone?: keyof typeof VALUE_TONES;
  children?: ReactNode;
}) {
  return (
    <div className="border-t border-border/60 py-3 first:border-t-0 first:pt-0 last:pb-0">
      <p className={ROW_LABEL}>{label}</p>
      <p className={`mt-1 text-sm font-semibold leading-6 ${VALUE_TONES[tone]}`}>
        {value}
      </p>
      {children}
    </div>
  );
}

export function RealityCheck({
  detail,
  analysis,
}: {
  detail: CaseDetail | null;
  analysis: AnalyzeResponse | null;
}) {
  if (!detail && !analysis) return null;
  const run = detail?.last_run ?? null;
  const overlap = run ? run.trigger_matches.length : 0;
  return (
    <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5 shadow-lg shadow-slate-950/10">
      <h2 className="text-base font-semibold text-foreground">Reality Check</h2>
      {detail && (
        <div className="mt-4">
          <RealSignalRow observedCount={detail.observed.length} />
          {run && <OverlapRow run={run} />}
          {run && overlap > 0 && <OverlapVerdictRow run={run} />}
          <CauseRow hypotheses={detail.hypotheses} />
          <DangerRow crisisActive={run?.crisis_active ?? false} />
          <SettleRow detail={detail} />
        </div>
      )}
      <SummaryBlock analysis={analysis} lastRun={run} />
    </section>
  );
}

function RealSignalRow({ observedCount }: { observedCount: number }) {
  // Computed from the Reality ledger: any observed statement on record
  // means the signal exists independent of interpretation.
  return observedCount > 0 ? (
    <Row
      label="Real signal?"
      value="YES — observed changes in behavior are on record"
      tone="good"
    />
  ) : (
    <Row
      label="Real signal?"
      value="NOT YET — no confirmed observations"
      tone="muted"
    />
  );
}

function OverlapRow({ run }: { run: LastRun }) {
  const matched = run.trigger_matches.length;
  const total = run.trigger_total;
  // "N of M" is a pattern COUNT, not a confidence number — allowed chrome.
  const value =
    matched >= 3
      ? `HIGH (${matched} of ${total} known patterns)`
      : matched >= 1
        ? `PRESENT (${matched} of ${total})`
        : "NONE DETECTED";
  return (
    <Row
      label="PTSD overlap?"
      value={value}
      tone={matched >= 1 ? "warn" : "muted"}
    >
      {matched > 0 && (
        /* Matched pattern names are backend copy, verbatim. */
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {run.trigger_matches.join(" · ")}
        </p>
      )}
      {/* WHY this caption exists: "overlap" was ambiguous in dogfooding.
          It states what the row measures — resemblance, not reaction,
          not evidence. Chrome copy; evidence-state language only. */}
      <p className="mt-1 text-xs leading-5 text-muted-foreground/80">
        How closely this situation resembles your known trigger patterns —
        not how you are reacting, and not evidence about what happened.
        Overlap raises the evidence bar in both directions.
      </p>
    </Row>
  );
}

function OverlapVerdictRow({ run }: { run: LastRun }) {
  // Overlap never falsifies the signal — it adjusts how the engine reads
  // it. The value is always "NO"; the backend's adjustment note explains
  // what the overlap actually did, verbatim.
  return (
    <Row label="Does PTSD overlap make the signal false?" value="NO">
      {run.adjustment_note && (
        <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
          {run.adjustment_note}
        </p>
      )}
    </Row>
  );
}

function CauseRow({ hypotheses }: { hypotheses: Hypothesis[] }) {
  // Derived from evidence bands of LIVE hypotheses only — dead models
  // (not_credible_here) don't get to claim or rule out a cause.
  const live = hypotheses.filter((h) => !h.not_credible_here);
  if (live.length === 0) return null;
  const supported = live.filter((h) => h.band === "supported");
  const contradicted = live.filter((h) => h.band === "contradicted");
  const titles = (list: Hypothesis[]) =>
    /* Hypothesis titles are backend copy, verbatim. */
    list.map((h) => h.title).join(", ");
  return (
    <Row
      label="Cause"
      value={
        supported.length > 0
          ? `SUPPORTED: ${titles(supported)}`
          : "UNRESOLVED — competing explanations remain open"
      }
      tone={supported.length > 0 ? "good" : "default"}
    >
      {contradicted.length > 0 && (
        <p className="mt-1 text-xs leading-5 text-red-200/80">
          RULED OUT: {titles(contradicted)}
        </p>
      )}
    </Row>
  );
}

function DangerRow({ crisisActive }: { crisisActive: boolean }) {
  // This row only REFLECTS state — SafetyBanner above everything owns the
  // crisis copy and resources and is never dismissible.
  return crisisActive ? (
    <Row
      label="Immediate danger"
      value="CRISIS ACTIVE — safety resources are shown above"
      tone="danger"
    />
  ) : (
    <Row label="Immediate danger" value="None apparent" tone="muted" />
  );
}

function SettleRow({ detail }: { detail: CaseDetail }) {
  // Only unknowns the backend marked worth chasing; top 3, verbatim.
  const pursue = detail.unknown
    .filter((item) => item.pursuit === "pursue")
    .slice(0, 3);
  if (pursue.length === 0) return null;
  return (
    <div className="border-t border-border/60 py-3 last:pb-0">
      <p className={ROW_LABEL}>What would settle this</p>
      <ul className="mt-1 space-y-1">
        {pursue.map((item, index) => (
          <li key={index} className="flex items-start gap-2">
            <span
              aria-hidden
              className="mt-[0.6rem] h-1 w-1 shrink-0 rounded-full bg-violet-300/70"
            />
            {/* Backend statement, verbatim. */}
            <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/90">
              {item.statement}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SummaryBlock({
  analysis,
  lastRun,
}: {
  analysis: AnalyzeResponse | null;
  lastRun: LastRun | null;
}) {
  // A fresh Analyze response wins (it knows served_prior + run id); with
  // none this session, the stored last run keeps the card self-sufficient.
  if (!analysis && !lastRun) return null;
  const mode = analysis ? analysis.mode : lastRun!.mode;
  const summary = analysis ? analysis.summary : lastRun!.summary;
  return (
    <div className="mt-4 border-t border-border/60 pt-4">
      {/* served_prior LEADS — the evidence-state badge sits above the
          stored run's own mode badge and summary, so a gated tap reads
          "no new data" before the old run's chrome. */}
      {analysis?.served_prior && (
        <div className="mb-3">
          <span className="inline-block rounded-full border border-border bg-secondary px-3 py-1 text-[11px] font-medium text-secondary-foreground">
            {SERVED_PRIOR_BADGE}
          </span>
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-violet-400/25 bg-violet-400/10 px-3 py-0.5 text-[10px] font-medium uppercase tracking-[0.2em] text-violet-200">
          {mode}
        </span>
        {analysis && (
          <span className="ml-auto text-xs text-muted-foreground">
            run {analysis.run_id}
          </span>
        )}
      </div>
      {/* The summary is backend copy and renders verbatim. */}
      <p className="whitespace-pre-wrap text-sm leading-7 text-foreground">
        {summary}
      </p>
    </div>
  );
}
