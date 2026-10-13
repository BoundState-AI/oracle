/**
 * RoundsSelector — review round configuration with cost transparency.
 * Surfaces oracle resource costs in scientific specification format.
 */

"use client";

import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

export const MIN_ROUNDS = 1;
export const MAX_ROUNDS = 4;

interface RoundsSelectorProps {
  value: number;
  onChange: (rounds: number) => void;
}

interface RoundsOption {
  value: number;
  label: string;
  description: string;
  specification: string;
  warning?: string;
}

const ROUNDS_OPTIONS: RoundsOption[] = [
  {
    value: 1,
    label: "Single Pass",
    description:
      "One round of oracle review. Baseline for exploratory or low-risk documents.",
    specification: "3 oracles × 1 round = 3 reviewer calls",
    warning: "Cannot converge",
  },
  {
    value: 2,
    label: "Two Rounds",
    description:
      "Enables convergence validation: round 2 confirms no new critical findings emerged from revisions.",
    specification: "3 oracles × 2 rounds = 6 reviewer calls",
  },
  {
    value: 3,
    label: "Three Rounds",
    description:
      "For dense specifications or contested findings where round 2 yields new defects.",
    specification: "3 oracles × 3 rounds = 9 reviewer calls",
  },
  {
    value: 4,
    label: "Four Rounds",
    description:
      "Maximum iteration depth. Use only when round 3 yields new unresolved disagreements.",
    specification: "3 oracles × 4 rounds = 12 reviewer calls",
    warning: "Peak cost",
  },
];

const COST_ESTIMATE = "~$8–$32 depending on document length";

export function RoundsSelector({ value, onChange }: RoundsSelectorProps) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-serif font-semibold mb-2">Review Configuration</h3>
        <p className="text-xs text-muted-foreground">
          Select oracle depth. Each round runs 4 independent reviewers.
        </p>
      </div>

      {/* Cost note */}
      <div className="p-3 bg-accent/10 border border-accent/30 rounded-md space-y-1">
        <div className="text-xs font-mono font-semibold text-accent uppercase tracking-wider">
          Resource estimate
        </div>
        <div className="text-sm text-foreground">
          {COST_ESTIMATE}
        </div>
      </div>

      {/* Round options */}
      <RadioGroup
        value={String(value)}
        onValueChange={(v) => {
          const parsed = Number(v);
          if (Number.isFinite(parsed)) {
            onChange(Math.max(MIN_ROUNDS, Math.min(MAX_ROUNDS, parsed)));
          }
        }}
        className="space-y-3"
      >
        {ROUNDS_OPTIONS.map((option) => (
          <label
            key={option.value}
            className={`
              group cursor-pointer block p-4 rounded-md border transition-all
              ${
                value === option.value
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50 bg-card/50"
              }
            `}
          >
            <div className="flex items-start gap-3">
              <RadioGroupItem
                value={String(option.value)}
                id={`rounds-${option.value}`}
                className="mt-1 flex-shrink-0"
              />
              <div className="flex-1 space-y-2">
                <div className="flex items-center gap-2">
                  <label
                    htmlFor={`rounds-${option.value}`}
                    className="text-sm font-serif font-semibold text-foreground cursor-pointer"
                  >
                    {option.label}
                  </label>
                  {option.warning && (
                    <span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-accent px-2 py-1 bg-accent/15 rounded">
                      {option.warning}
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {option.description}
                </p>
                <div className="text-xs font-mono text-muted-foreground bg-card/50 px-2 py-1 rounded inline-block">
                  {option.specification}
                </div>
              </div>
            </div>
          </label>
        ))}
      </RadioGroup>

      {/* Convergence note */}
      <div className="p-3 bg-muted/10 border border-border rounded-md text-xs text-muted-foreground space-y-1">
        <div className="font-mono font-semibold uppercase tracking-wider">Convergence</div>
        <p>
          Baseline convergence requires round 2+. Systems that disagree persistently are reported as blocked, never as false consensus.
        </p>
      </div>
    </div>
  );
}

