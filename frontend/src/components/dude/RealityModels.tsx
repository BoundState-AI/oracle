/**
 * RealityModels — the DUDE case screen's "Reality" and "Models" sections,
 * rendering the epistemic state from GET /cases/{id} below the Analysis
 * panel.
 *
 * Design contract (spec v0.2 + mobile vision v0.1):
 *   - Every statement, description, falsifier, and adversary attack is
 *     backend copy and renders VERBATIM. This module owns UI chrome labels
 *     only ("Reality", "Observed", "Inferred", "interpretation, not fact",
 *     "Unknown", "Models", "Would change this:", "Adversary",
 *     "Unsupported links", "no credible instance", "confirmed").
 *     Nothing here says anything about the user's psychology.
 *   - Inferred renders VISIBLY distinct from Observed (dashed violet,
 *     italic, labeled "interpretation, not fact") — this distinction IS
 *     the product, not decoration.
 *   - Evidence bands render as words (supported/plausible/...), NEVER as
 *     numbers or percentages.
 *   - not_credible_here hypotheses render dimmed with a "no credible
 *     instance" note; harm_class catastrophic_to_user gets a subtle red
 *     edge on the card.
 */

import {
  type AdversaryAttack,
  type Hypothesis,
  type ObservedStatement,
  type UnknownStatement,
} from "@/lib/dudeApi";

// Shared chip chrome, matching the analysis panel's mode badge.
const CHIP =
  "rounded-full border px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.15em]";

const GROUP_LABEL =
  "text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground";

// Band chips are words only — tone hints at direction, no numbers anywhere.
const BAND_STYLES: Record<string, string> = {
  supported: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
  plausible: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  weakly_supported: "border-border bg-secondary text-secondary-foreground",
  unresolved: "border-border bg-secondary text-muted-foreground",
  contradicted: "border-red-400/40 bg-red-400/10 text-red-200",
};

const DEFAULT_BAND_STYLE = "border-border bg-secondary text-secondary-foreground";

export function RealitySection({
  observed,
  inferred,
  unknown,
}: {
  observed: ObservedStatement[];
  inferred: string[];
  unknown: UnknownStatement[];
}) {
  if (!observed.length && !inferred.length && !unknown.length) return null;
  return (
    <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5">
      <h2 className="text-base font-semibold text-foreground">Reality</h2>
      {observed.length > 0 && <ObservedGroup observed={observed} />}
      {inferred.length > 0 && <InferredGroup inferred={inferred} />}
      {unknown.length > 0 && <UnknownGroup unknown={unknown} />}
    </section>
  );
}

function ObservedGroup({ observed }: { observed: ObservedStatement[] }) {
  return (
    <div className="mt-4">
      <h3 className={GROUP_LABEL}>Observed</h3>
      <ul className="mt-2 space-y-2">
        {observed.map((item, index) => (
          <li
            key={index}
            className="flex items-start gap-2.5 rounded-xl border border-border/60 bg-background/40 px-4 py-3"
          >
            <span aria-hidden className="mt-0.5 shrink-0 text-emerald-300">
              ✓
            </span>
            {/* Backend statement, verbatim. */}
            <p className="min-w-0 flex-1 whitespace-pre-wrap text-sm leading-6 text-foreground">
              {item.statement}
            </p>
            {item.user_confirmed && (
              <span
                className={`${CHIP} shrink-0 border-emerald-400/30 bg-emerald-400/10 text-emerald-200`}
              >
                confirmed
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function InferredGroup({ inferred }: { inferred: string[] }) {
  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className={`${GROUP_LABEL} text-violet-300/90`}>Inferred</h3>
        <span className="rounded-full border border-violet-400/30 bg-violet-400/10 px-2.5 py-0.5 text-[10px] font-medium italic text-violet-200">
          interpretation, not fact
        </span>
      </div>
      <ul className="mt-2 space-y-2">
        {inferred.map((statement, index) => (
          <li
            key={index}
            className="rounded-xl border border-dashed border-violet-400/40 bg-violet-500/[0.07] px-4 py-3"
          >
            {/* Backend statement, verbatim — italic marks it as reading. */}
            <p className="whitespace-pre-wrap text-sm italic leading-6 text-violet-100/90">
              {statement}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function UnknownGroup({ unknown }: { unknown: UnknownStatement[] }) {
  return (
    <div className="mt-5">
      <h3 className={GROUP_LABEL}>Unknown</h3>
      <ul className="mt-2 space-y-2">
        {unknown.map((item, index) => (
          <li
            key={index}
            className="flex items-start gap-2.5 rounded-xl border border-border/60 bg-background/40 px-4 py-3"
          >
            {/* Backend statement, verbatim. */}
            <p className="min-w-0 flex-1 whitespace-pre-wrap text-sm leading-6 text-foreground">
              {item.statement}
            </p>
            {/* Importance is a backend word, rendered verbatim in a chip. */}
            <span
              className={`${CHIP} shrink-0 border-amber-400/30 bg-amber-400/10 text-amber-200`}
            >
              {item.importance}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ModelsSection({ hypotheses }: { hypotheses: Hypothesis[] }) {
  if (!hypotheses.length) return null;
  return (
    <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-5">
      <h2 className="text-base font-semibold text-foreground">Models</h2>
      <div className="mt-4 space-y-3">
        {hypotheses.map((hypothesis, index) => (
          <HypothesisCard key={index} hypothesis={hypothesis} />
        ))}
      </div>
    </section>
  );
}

function HypothesisCard({ hypothesis }: { hypothesis: Hypothesis }) {
  // catastrophic_to_user gets a subtle red edge; not_credible_here dims the
  // whole card but nothing is hidden — dead models stay inspectable.
  const edge =
    hypothesis.harm_class === "catastrophic_to_user"
      ? "border-red-500/40"
      : "border-border/60";
  return (
    <article
      className={`rounded-2xl border ${edge} bg-background/40 p-4 ${
        hypothesis.not_credible_here ? "opacity-50" : ""
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {/* Backend title, verbatim. */}
        <h3 className="min-w-0 text-sm font-semibold leading-6 text-foreground">
          {hypothesis.title}
        </h3>
        <span
          className={`${CHIP} border-border/80 bg-background/60 text-muted-foreground`}
        >
          {hypothesis.archetype}
        </span>
        <span
          className={`${CHIP} ${BAND_STYLES[hypothesis.band] ?? DEFAULT_BAND_STYLE}`}
        >
          {hypothesis.band}
        </span>
        {hypothesis.not_credible_here && (
          <span className={`${CHIP} border-border bg-secondary text-muted-foreground`}>
            no credible instance
          </span>
        )}
      </div>
      {/* Backend description, verbatim. */}
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/90">
        {hypothesis.description}
      </p>
      {hypothesis.falsifiers.length > 0 && (
        <FalsifierList falsifiers={hypothesis.falsifiers} />
      )}
      {hypothesis.attacks.length > 0 && (
        <AdversarySubsection attacks={hypothesis.attacks} />
      )}
    </article>
  );
}

function FalsifierList({ falsifiers }: { falsifiers: string[] }) {
  return (
    <div className="mt-3">
      <p className={GROUP_LABEL}>Would change this:</p>
      <ul className="mt-1.5 space-y-1">
        {falsifiers.map((falsifier, index) => (
          <li key={index} className="flex items-start gap-2">
            <span aria-hidden className="mt-[0.6rem] h-1 w-1 shrink-0 rounded-full bg-violet-300/70" />
            {/* Backend falsifier, verbatim. */}
            <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/90">
              {falsifier}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AdversarySubsection({ attacks }: { attacks: AdversaryAttack[] }) {
  return (
    <div className="mt-3 border-t border-border/60 pt-3">
      <p className={`${GROUP_LABEL} text-red-300/90`}>Adversary</p>
      <ul className="mt-1.5 space-y-2">
        {attacks.map((attack, index) => (
          <li
            key={index}
            className="rounded-xl border border-red-400/20 bg-red-500/[0.06] px-3.5 py-2.5"
          >
            {/* Backend attack, verbatim. */}
            <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/90">
              {attack.attack}
            </p>
            {attack.unsupported_links.length > 0 && (
              <div className="mt-1.5">
                <p className={GROUP_LABEL}>Unsupported links</p>
                <ul className="mt-1 space-y-0.5">
                  {attack.unsupported_links.map((link, linkIndex) => (
                    /* Backend link text, verbatim. */
                    <li
                      key={linkIndex}
                      className="whitespace-pre-wrap text-[13px] leading-6 text-muted-foreground"
                    >
                      {link}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
