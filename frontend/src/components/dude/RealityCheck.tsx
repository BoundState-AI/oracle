/**
 * RealityCheck — the DUDE case screen's PRIMARY, default view. It answers
 * "am I reacting to a trigger or something real?" in the first five
 * seconds with labeled rows computed from GET /cases/{id}, not with
 * epistemology.
 *
 * Design contract (spec v0.2 I1/I2 + trigger spec v1.1 R3/R5/R6/R8 +
 * founder brief):
 *   - Row LABELS are fixed, approved chrome ("REAL SIGNAL?",
 *     "TRIGGER OVERLAP?", "DOES TRIGGER OVERLAP MAKE THE SIGNAL FALSE?",
 *     "CAUSE", "IMMEDIATE DANGER", "WHAT WOULD SETTLE THIS"). Row values
 *     are computed chrome words; the only backend copy in this card —
 *     matched family labels, the vetted distortion/no-match/possible-
 *     overlap copy, the adjustment note, hypothesis titles,
 *     pursue-unknown statements, and the analysis summary — renders
 *     VERBATIM.
 *   - TRIGGER OVERLAP is the run's single confirmed-family statistic
 *     (R8): a band WORD (none/low/moderate/high), never a count, never a
 *     number. De-identified family labels list beneath — never scores.
 *   - Unconfirmed proposals render separately as possibility with a
 *     Confirm / Not this pair (R5: the matcher proposes, the user
 *     disposes); the vetted possible-overlap note renders verbatim.
 *   - The distortion block (R3) is backend template copy rendered
 *     verbatim, only at overlap >= moderate and NEVER while a crisis is
 *     active — enforced by the backend (it serves "") and re-guarded
 *     here.
 *   - The no-match state renders the backend's exact no-match copy (R3
 *     mirrored invariant) — never a blank row.
 *   - Confidence is WORDS, never numbers.
 *   - served_prior LEADS the summary block with the exact evidence-state
 *     badge copy, above the mode badge and summary (same rule as the old
 *     Analysis panel this card absorbs).
 *   - IMMEDIATE DANGER only reflects run state. SafetyBanner (above all
 *     content, never dismissible) owns crisis copy and resources.
 */

"use client";

import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import {
  confirmAssessment,
  denyAssessment,
  type AnalyzeResponse,
  type CaseDetail,
  type Hypothesis,
  type LastRun,
  type OverlapLevel,
  type TriggerProposal,
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

// Band words for the overlap row (v1.1 R8) — never counts, never numbers.
const OVERLAP_VALUES: Record<OverlapLevel, string> = {
  none: "NONE",
  low: "LOW",
  moderate: "MODERATE",
  high: "HIGH",
};

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
  onDetailChanged,
}: {
  detail: CaseDetail | null;
  analysis: AnalyzeResponse | null;
  /** Called after a proposal disposition so the parent can refetch. */
  onDetailChanged?: () => void;
}) {
  if (!detail && !analysis) return null;
  const run = detail?.last_run ?? null;
  const proposals = detail?.trigger_proposals ?? [];
  return (
    <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5 shadow-lg shadow-slate-950/10">
      <h2 className="text-base font-semibold text-foreground">Reality Check</h2>
      {detail && (
        <div className="mt-4">
          <RealSignalRow observedCount={detail.observed.length} />
          {run && <OverlapRow run={run} hasProposals={proposals.length > 0} />}
          {run && run.trigger_matches.length > 0 && (
            <OverlapVerdictRow run={run} />
          )}
          {run && <DistortionBlock run={run} />}
          {proposals.length > 0 && (
            <ProposalsBlock
              caseId={detail.case_id}
              proposals={proposals}
              note={detail.possible_overlap_note}
              onDetailChanged={onDetailChanged}
            />
          )}
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

function OverlapRow({
  run,
  hasProposals,
}: {
  run: LastRun;
  hasProposals: boolean;
}) {
  // The value is the run's confirmed-family statistic as a band WORD
  // (v1.1 R8) — never the legacy match count, never a number.
  const level = run.trigger_overlap;
  const noMatch =
    level === "none" && run.trigger_matches.length === 0 && !hasProposals;
  return (
    <Row
      label="Trigger overlap?"
      value={OVERLAP_VALUES[level]}
      tone={level === "none" ? "muted" : "warn"}
    >
      {run.overlap_labels.length > 0 && (
        /* De-identified family labels — backend copy, verbatim (R6). */
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {run.overlap_labels.join(" · ")}
        </p>
      )}
      {noMatch && (
        /* R3 mirrored invariant: the exact vetted no-match copy — the
           row never goes blank, and never editorializes the absence. */
        <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
          {run.no_match_copy}
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
    <Row label="Does trigger overlap make the signal false?" value="NO">
      {run.adjustment_note && (
        <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
          {run.adjustment_note}
        </p>
      )}
    </Row>
  );
}

function DistortionBlock({ run }: { run: LastRun }) {
  // R3/R2 render rules: the backend serves the block empty below
  // moderate overlap and always empty in crisis; this guard re-enforces
  // both so a contract slip can never paint distortion copy over a
  // crisis banner or a low-overlap run.
  const eligible =
    run.trigger_overlap === "moderate" || run.trigger_overlap === "high";
  if (!eligible || run.crisis_active || !run.distortion_block) return null;
  return (
    <div className="border-t border-border/60 py-3 last:pb-0">
      {/* Vetted template copy — amplification AND suppression candidates,
          rendered verbatim (the header line is part of the copy). */}
      <p className="whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
        {run.distortion_block}
      </p>
    </div>
  );
}

function ProposalsBlock({
  caseId,
  proposals,
  note,
  onDetailChanged,
}: {
  caseId: string;
  proposals: TriggerProposal[];
  note: string;
  onDetailChanged?: () => void;
}) {
  // Tracks the assessment currently being disposed so both buttons of
  // that proposal disable together while the POST is in flight.
  const [busyId, setBusyId] = useState<string | null>(null);

  const dispose = async (assessmentId: string, confirm: boolean) => {
    if (busyId) return;
    setBusyId(assessmentId);
    try {
      await (confirm
        ? confirmAssessment(caseId, assessmentId)
        : denyAssessment(caseId, assessmentId));
      onDetailChanged?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Disposition failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="border-t border-border/60 py-3 last:pb-0">
      {/* R5 chrome: the required possibility framing, then the vetted
          template note verbatim. */}
      <p className={ROW_LABEL}>Possible overlap (model-assessed, unconfirmed)</p>
      {note && (
        <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
          {note}
        </p>
      )}
      <ul className="mt-2 space-y-2">
        {proposals.map((proposal) => (
          <li
            key={proposal.assessment_id}
            className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-violet-400/40 bg-violet-500/[0.07] px-4 py-3"
          >
            {/* De-identified family label — backend copy, verbatim. */}
            <p className="min-w-0 flex-1 text-sm leading-6 text-violet-100/90">
              {proposal.label}
            </p>
            <span className="flex shrink-0 gap-2">
              <button
                type="button"
                disabled={busyId !== null}
                onClick={() => void dispose(proposal.assessment_id, true)}
                className="rounded-full border border-violet-400/50 bg-violet-500/15 px-3 py-1 text-xs font-semibold text-violet-100 transition-colors hover:bg-violet-500/25 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Confirm
              </button>
              <button
                type="button"
                disabled={busyId !== null}
                onClick={() => void dispose(proposal.assessment_id, false)}
                className="rounded-full border border-border px-3 py-1 text-xs font-semibold text-muted-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                Not this
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
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
