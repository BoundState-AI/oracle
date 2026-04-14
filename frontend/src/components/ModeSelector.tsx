/**
 * ModeSelector — radio group for choosing the review processing mode.
 * Options: polish-only, review+polish, or full rewrite. Defaults to review+polish.
 */

"use client";

import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

export type ProcessingMode = "polish" | "review" | "rewrite";

interface ModeSelectorProps {
  value: ProcessingMode;
  onChange: (mode: ProcessingMode) => void;
}

const MODES: {
  value: ProcessingMode;
  label: string;
  description: string;
  isDefault?: boolean;
}[] = [
  {
    value: "polish",
    label: "Polish Only",
    description:
      "Fix language, flow, and structure. Returns polished docs immediately.",
  },
  {
    value: "review",
    label: "Review + Polish",
    description:
      "Oracle reviews first, then returns the critique and polished docs together.",
    isDefault: true,
  },
  {
    value: "rewrite",
    label: "Full Rewrite",
    description:
      "Oracle takes the wheel. Returns completely rewritten docs.",
  },
];

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-foreground">Processing Mode</h3>
      <RadioGroup
        value={value}
        onValueChange={(v) => onChange(v as ProcessingMode)}
        className="space-y-2"
      >
        {MODES.map((mode) => (
          <label
            key={mode.value}
            className={`
              flex items-start gap-3 rounded-lg border px-4 py-3 cursor-pointer transition-colors
              ${
                value === mode.value
                  ? "border-ring bg-accent"
                  : "border-border hover:bg-accent/50"
              }
            `}
          >
            <RadioGroupItem value={mode.value} className="mt-0.5" />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-foreground">
                  {mode.label}
                </span>
                {mode.isDefault && (
                  <span className="rounded-full bg-ring/10 px-2 py-0.5 text-[10px] font-medium text-ring">
                    default
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {mode.description}
              </p>
            </div>
          </label>
        ))}
      </RadioGroup>
    </div>
  );
}
