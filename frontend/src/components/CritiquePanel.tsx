"use client";

import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { RotateCcw, ArrowRight } from "lucide-react";

interface CritiquePanelProps {
  critique: string;
  metrics?: Record<string, unknown> | null;
  onStartOver: () => void;
  onGenerate?: () => void;
  generating?: boolean;
  showGenerate?: boolean;
}

export function CritiquePanel({
  critique,
  metrics,
  onStartOver,
  onGenerate,
  generating = false,
  showGenerate = true,
}: CritiquePanelProps) {
  const metricEntries: Array<[string, string | number]> = metrics
    ? [
        ["Accepted critical", metrics.accepted_critical_count],
        ["Accepted high", metrics.accepted_high_count],
        ["Accepted defects", metrics.total_accepted_defects],
        ["Rejected claims", metrics.total_rejected_claims],
        ["Preference only", metrics.total_preference_only],
        ["Rounds to stability", metrics.rounds_to_stability],
        ["Converged", metrics.converged ? "Yes" : "No"],
      ].filter(([, value]) => value !== undefined) as Array<[string, string | number]>
    : [];

  return (
    <Card className="border-border">
      <CardHeader>
        <CardTitle className="text-lg font-semibold tracking-tight">
          Oracle Review
        </CardTitle>
      </CardHeader>
      <CardContent>
        {metricEntries.length > 0 && (
          <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {metricEntries.map(([label, value]) => (
              <div
                key={String(label)}
                className="rounded-md border border-border bg-muted/30 px-3 py-3"
              >
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                  {label}
                </div>
                <div className="mt-1 text-lg font-semibold text-foreground">
                  {String(value)}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="max-h-[28rem] overflow-y-auto rounded-md border border-border bg-muted/30 p-4">
          <div className="prose prose-sm dark:prose-invert max-w-none text-foreground prose-headings:text-foreground prose-strong:text-foreground prose-li:text-foreground">
            <ReactMarkdown>{critique}</ReactMarkdown>
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex justify-between gap-3">
        <Button variant="outline" onClick={onStartOver} disabled={generating}>
          <RotateCcw className="h-4 w-4" data-icon="inline-start" />
          Start Over
        </Button>
        {showGenerate && onGenerate ? (
          <Button onClick={onGenerate} disabled={generating}>
            {generating ? "Generating..." : "Generate Documents"}
            {!generating && <ArrowRight className="h-4 w-4" data-icon="inline-end" />}
          </Button>
        ) : null}
      </CardFooter>
    </Card>
  );
}
