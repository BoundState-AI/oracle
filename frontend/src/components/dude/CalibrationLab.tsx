/**
 * CalibrationLab — the Lab's "Calibration" section (trigger spec v1 §8,
 * amended by v1.1 R6): a sibling toggle next to "How the sausage is
 * made" listing trigger families and running the rate-a-scenario flow.
 *
 * Design contract:
 *   - Section copy is chrome drawn from the spec's own vocabulary
 *     ("What shifts your state?", "Which of these hits harder?"). No
 *     clinical checklist framing, no psychology-verdict language
 *     anywhere in static strings.
 *   - Families render label + status word + calibration tag; the
 *     fire-rate caveat is the backend's vetted template copy, verbatim
 *     (R8). NEVER raw scores, NEVER raw response text (R6) — the API
 *     does not serve them and nothing here would render them.
 *   - "Why DUDE thinks this" shows feature DESCRIPTIONS and evidence
 *     SOURCE TYPES with counts (e.g. "2 calibration responses,
 *     1 matched-pair contrast") — provenance, never content.
 *   - Rating: a 0-5 tap scale per scenario. A matched pair renders as
 *     two scenarios under the "Which of these hits harder?" chrome with
 *     two scales. The backend stamps state_at_capture and the declared
 *     scale on every answer.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  fetchPendingCalibration,
  fetchTriggerFamilies,
  submitCalibration,
  type CalibrationUnit,
  type EvidenceSourceCount,
  type TriggerFamilyView,
} from "@/lib/dudeApi";

const GROUP_LABEL =
  "text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground";

const CHIP =
  "rounded-full border px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.15em]";

// The tap scale the backend declares for Lab answers (0-5).
const SCALE_STEPS = [0, 1, 2, 3, 4, 5] as const;

// Evidence source types → chrome nouns [singular, plural]. Provenance
// words only; an unknown type falls back to the backend word verbatim.
const SOURCE_TYPE_CHROME: Record<string, [string, string]> = {
  calibration_response: ["calibration response", "calibration responses"],
  matched_pair_contrast: ["matched-pair contrast", "matched-pair contrasts"],
  direct_user_report: ["direct report", "direct reports"],
  repeated_case_pattern: ["repeated case pattern", "repeated case patterns"],
  assistant_hypothesis: ["assistant hypothesis", "assistant hypotheses"],
  clinician_input: ["clinician input", "clinician inputs"],
  case_resolution: ["case resolution", "case resolutions"],
  in_vivo_confirmation: ["in-vivo confirmation", "in-vivo confirmations"],
  legacy_manual_trigger: ["legacy manual trigger", "legacy manual triggers"],
};

function evidenceSummary(sources: EvidenceSourceCount[]): string {
  return sources
    .map(({ source_type, count }) => {
      const chrome = SOURCE_TYPE_CHROME[source_type];
      const noun = chrome ? chrome[count === 1 ? 0 : 1] : source_type;
      return `${count} ${noun}`;
    })
    .join(", ");
}

export function CalibrationLab() {
  // Starts closed on every visit — calibration is a deliberate detour,
  // not something to resume by surprise mid-case.
  const [open, setOpen] = useState(false);
  const [families, setFamilies] = useState<TriggerFamilyView[] | null>(null);
  const [units, setUnits] = useState<CalibrationUnit[] | null>(null);
  const [failed, setFailed] = useState(false);

  const toggle = useCallback(() => setOpen((current) => !current), []);

  // Fetch on first open only; a reopened section keeps its data.
  useEffect(() => {
    if (!open || families !== null || failed) return;
    Promise.all([fetchTriggerFamilies(), fetchPendingCalibration()])
      .then(([familyList, unitList]) => {
        setFamilies(familyList);
        setUnits(unitList);
      })
      .catch(() => setFailed(true));
  }, [open, families, failed]);

  return (
    <section className="space-y-6">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-[1.75rem] border border-border/80 bg-card/70 px-5 py-4 text-sm font-semibold text-foreground transition-colors hover:bg-accent/40 active:bg-accent/40"
      >
        Calibration
        <ChevronDown
          aria-hidden
          className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open && (
        <div className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5">
          {/* Spec §8 vocabulary — the section asks, it never diagnoses. */}
          <h2 className="text-base font-semibold text-foreground">
            What shifts your state?
          </h2>
          {failed && (
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Calibration data could not be loaded.
            </p>
          )}
          {units !== null && (
            <RateScenario
              units={units}
              onAnswered={(promptIds) =>
                setUnits((current) =>
                  (current ?? []).filter((unit) =>
                    unit.prompts.every((p) => !promptIds.includes(p.prompt_id))
                  )
                )
              }
            />
          )}
          {families !== null && <FamilyList families={families} />}
        </div>
      )}
    </section>
  );
}

/**
 * The rate-a-scenario flow: one pending unit at a time. A single
 * scenario submits on tap; a matched pair asks "Which of these hits
 * harder?" and submits both scales together.
 */
function RateScenario({
  units,
  onAnswered,
}: {
  units: CalibrationUnit[];
  onAnswered: (promptIds: string[]) => void;
}) {
  const [scores, setScores] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const unit = units[0] ?? null;

  const submit = useCallback(
    async (answers: Array<{ promptId: string; score: number }>) => {
      if (submitting) return;
      setSubmitting(true);
      try {
        for (const answer of answers) {
          // Sequential on purpose: both arms of a pair land in the same
          // Lab session, and a failure leaves the unit visibly pending.
          await submitCalibration(answer.promptId, answer.score);
        }
        setScores({});
        onAnswered(answers.map((a) => a.promptId));
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Rating failed");
      } finally {
        setSubmitting(false);
      }
    },
    [submitting, onAnswered]
  );

  return (
    <div className="mt-4 border-t border-border/60 pt-4">
      <p className={GROUP_LABEL}>Rate a scenario</p>
      {unit === null ? (
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Nothing waiting to rate right now.
        </p>
      ) : (
        <div className="mt-2 space-y-3">
          {unit.kind === "pair" && (
            /* Spec §8 chrome for matched pairs. */
            <p className="text-sm font-semibold leading-6 text-foreground">
              Which of these hits harder?
            </p>
          )}
          {unit.prompts.map((prompt) => (
            <div
              key={prompt.prompt_id}
              className="rounded-xl border border-border/60 bg-background/40 px-4 py-3"
            >
              {/* Scenario text is backend copy, verbatim. */}
              <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">
                {prompt.text}
              </p>
              <TapScale
                value={scores[prompt.prompt_id]}
                disabled={submitting}
                onSelect={(score) => {
                  if (unit.kind === "single") {
                    void submit([{ promptId: prompt.prompt_id, score }]);
                  } else {
                    setScores((s) => ({ ...s, [prompt.prompt_id]: score }));
                  }
                }}
              />
            </div>
          ))}
          <p className="text-xs leading-5 text-muted-foreground/80">
            0 = no shift · 5 = maximum shift
          </p>
          {unit.kind === "pair" && (
            <button
              type="button"
              disabled={
                submitting ||
                unit.prompts.some((p) => scores[p.prompt_id] === undefined)
              }
              onClick={() =>
                void submit(
                  unit.prompts.map((p) => ({
                    promptId: p.prompt_id,
                    score: scores[p.prompt_id],
                  }))
                )
              }
              className="flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-violet-400/50 bg-violet-500/15 text-sm font-semibold text-violet-100 transition-colors hover:bg-violet-500/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Submit both
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function TapScale({
  value,
  disabled,
  onSelect,
}: {
  value: number | undefined;
  disabled: boolean;
  onSelect: (score: number) => void;
}) {
  return (
    <div className="mt-3 flex gap-2" role="group" aria-label="0 to 5 scale">
      {SCALE_STEPS.map((step) => (
        <button
          key={step}
          type="button"
          disabled={disabled}
          aria-pressed={value === step}
          onClick={() => onSelect(step)}
          className={`h-10 w-10 rounded-full border text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
            value === step
              ? "border-violet-400/70 bg-violet-500/30 text-violet-100"
              : "border-border bg-background/60 text-foreground hover:bg-accent"
          }`}
        >
          {step}
        </button>
      ))}
    </div>
  );
}

function FamilyList({ families }: { families: TriggerFamilyView[] }) {
  if (families.length === 0) return null;
  return (
    <div className="mt-5 border-t border-border/60 pt-4">
      <p className={GROUP_LABEL}>Trigger families</p>
      <div className="mt-2 space-y-3">
        {families.map((family) => (
          <FamilyCard key={family.slug} family={family} />
        ))}
      </div>
    </div>
  );
}

function FamilyCard({ family }: { family: TriggerFamilyView }) {
  const [showWhy, setShowWhy] = useState(false);
  const sources = evidenceSummary(family.evidence_sources);
  return (
    <article className="rounded-2xl border border-border/60 bg-background/40 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {/* De-identified family label — backend copy, verbatim (R6a). */}
        <h3 className="min-w-0 text-sm font-semibold leading-6 text-foreground">
          {family.label}
        </h3>
        {/* Status word and calibration tag are backend vocabulary words,
            rendered verbatim — never numbers, never scores. */}
        <span className={`${CHIP} border-border/80 bg-background/60 text-muted-foreground`}>
          {family.status}
        </span>
        <span className={`${CHIP} border-violet-400/30 bg-violet-400/10 text-violet-200`}>
          {family.calibration}
        </span>
      </div>
      {family.fire_rate_caveat && (
        /* R8: the vetted low-diagnostic caveat, verbatim — a caveat
           string, never a rate. */
        <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-amber-200/90">
          {family.fire_rate_caveat}
        </p>
      )}
      <button
        type="button"
        onClick={() => setShowWhy((current) => !current)}
        aria-expanded={showWhy}
        className="mt-2 text-xs font-medium text-violet-200 underline-offset-4 hover:underline"
      >
        {showWhy ? "Hide why DUDE thinks this" : "Why DUDE thinks this"}
      </button>
      {showWhy && (
        <div className="mt-2 space-y-2">
          {/* Backend description, verbatim. */}
          <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/90">
            {family.description}
          </p>
          {family.features.length > 0 && (
            <ul className="space-y-1">
              {family.features.map((feature) => (
                <li key={feature.slug} className="flex items-start gap-2">
                  <span
                    aria-hidden
                    className="mt-[0.6rem] h-1 w-1 shrink-0 rounded-full bg-violet-300/70"
                  />
                  {/* Feature description — backend copy, verbatim. */}
                  <p className="text-sm leading-6 text-foreground/90">
                    {feature.description}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {sources && (
            /* Evidence SOURCE TYPES with counts — provenance only,
               never response text, never scores (R6). */
            <p className="text-xs leading-5 text-muted-foreground">
              Evidence on record: {sources}.
            </p>
          )}
        </div>
      )}
    </article>
  );
}
