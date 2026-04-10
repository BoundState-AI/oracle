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
  warning?: string;
  isDefault?: boolean;
}

const ROUNDS_OPTIONS: RoundsOption[] = [
  {
    value: 1,
    label: "Single Pass",
    description:
      "One round of review. Fast, cheap, cannot converge by definition.",
    isDefault: true,
  },
  {
    value: 2,
    label: "Two Rounds",
    description:
      "Enables true convergence: round 2 confirms no new critical/high findings emerged from revisions.",
  },
  {
    value: 3,
    label: "Three Rounds",
    description:
      "For dense specs or contested findings where round 2 rarely stabilizes.",
  },
  {
    value: 4,
    label: "Four Rounds",
    description: "Maximum. Use only when you expect heavy iteration.",
    warning: "Very expensive",
  },
];

const PER_ROUND_COST_LABEL = "~$2–8 per round";

export function RoundsSelector({ value, onChange }: RoundsSelectorProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium text-foreground">Review Rounds</h3>
        <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          {PER_ROUND_COST_LABEL}
        </span>
      </div>
      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200/90">
        <strong className="font-semibold">Heads up:</strong> each round runs 4
        reviewer LLMs (Beth, Fran, Codex, Grok) over the full document. Cost
        and latency scale roughly linearly with round count. A 100-page spec at
        4 rounds can exceed $30.
      </div>
      <RadioGroup
        value={String(value)}
        onValueChange={(v) => {
          const parsed = Number(v);
          if (Number.isFinite(parsed)) {
            onChange(Math.max(MIN_ROUNDS, Math.min(MAX_ROUNDS, parsed)));
          }
        }}
        className="space-y-2"
      >
        {ROUNDS_OPTIONS.map((option) => (
          <label
            key={option.value}
            className={`
              flex items-start gap-3 rounded-lg border px-4 py-3 cursor-pointer transition-colors
              ${
                value === option.value
                  ? "border-ring bg-accent"
                  : "border-border hover:bg-accent/50"
              }
            `}
          >
            <RadioGroupItem value={String(option.value)} className="mt-0.5" />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-foreground">
                  {option.label}
                </span>
                {option.isDefault && (
                  <span className="rounded-full bg-ring/10 px-2 py-0.5 text-[10px] font-medium text-ring">
                    default
                  </span>
                )}
                {option.warning && (
                  <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                    {option.warning}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {option.description}
              </p>
            </div>
          </label>
        ))}
      </RadioGroup>
    </div>
  );
}
