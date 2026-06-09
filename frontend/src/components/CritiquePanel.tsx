/**
 * CritiquePanel — scientific dashboard for Oracle review findings.
 * Renders metrics, consensus status, verdict consistency, and detailed critique.
 */

"use client";

import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { ConsensusVisualizer } from "@/components/ConsensusVisualizer";
import { VerdictIndicator } from "@/components/VerdictIndicator";
import { RotateCcw, ArrowRight } from "lucide-react";

interface CritiquePanelProps {
  critique: string;
  metrics?: Record<string, unknown> | null;
  consensusType?: string;
  converged?: boolean;
  onStartOver: () => void;
  onGenerate?: () => void;
  generating?: boolean;
  showGenerate?: boolean;
}

export function CritiquePanel({
  critique,
  metrics,
  consensusType = "full_agreement",
  converged = true,
  onStartOver,
  onGenerate,
  generating = false,
  showGenerate = true,
}: CritiquePanelProps) {
  // Build metrics grid with semantic grouping
  const metricGroups = {
    "Consensus": [
      ["Status", converged ? "Converged" : "Not Converged"],
      ["Type", consensusType.replace(/_/g, " ").split(" ").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")],
    ],
    "Findings": [
      ["Accepted Critical", String(metrics?.accepted_critical_count ?? "—")],
      ["Accepted High", String(metrics?.accepted_high_count ?? "—")],
      ["Total Accepted", String(metrics?.total_accepted_defects ?? "—")],
      ["Rejected Claims", String(metrics?.total_rejected_claims ?? "—")],
    ],
    "Resolution": [
      ["Rounds to Stability", String(metrics?.rounds_to_stability ?? "—")],
      ["Preference Only", String(metrics?.total_preference_only ?? "—")],
    ],
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <h2 className="text-3xl font-serif font-bold tracking-tight">
          Review Analysis
        </h2>
        <p className="text-sm text-muted-foreground">
          Multi-oracle consensus analysis · {String(metrics?.rounds_to_stability ?? "∞")} rounds
        </p>
      </div>

      {/* Consensus section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-mono uppercase tracking-wider">
                Consensus Status
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ConsensusVisualizer
                consensusType={consensusType}
                oracleCount={4}
              />
            </CardContent>
          </Card>
        </div>

        {/* Verdict consistency */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-mono uppercase tracking-wider">
                Reviewer Alignment
              </CardTitle>
            </CardHeader>
            <CardContent>
              <VerdictIndicator
                hasUnanimousMajorRevision={false}
                vetoApplied={false}
              />
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Metrics dashboard */}
      {metrics && (
        <div className="space-y-4">
          {Object.entries(metricGroups).map(([groupName, items]) => (
            items.length > 0 && (
              <div key={groupName}>
                <h3 className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-3 pl-1">
                  {groupName}
                </h3>
                <div className="metrics-grid">
                  {items.map(([label, value]) => (
                    <div key={label} className="metric-item">
                      <div className="metric-label">{label}</div>
                      <div className="metric-value text-foreground">
                        {String(value)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          ))}
        </div>
      )}

      {/* Findings report */}
      <div className="findings-section space-y-3">
        <h3 className="text-lg font-serif font-semibold">Detailed Findings</h3>
        <Card>
          <CardContent className="pt-6">
            <div className="max-h-[32rem] overflow-y-auto">
              <div className="prose prose-sm dark:prose-invert max-w-none text-foreground prose-headings:font-serif prose-headings:text-foreground prose-strong:text-foreground prose-li:text-foreground">
                <ReactMarkdown>{critique}</ReactMarkdown>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between gap-4 pt-4">
        <Button
          variant="outline"
          onClick={onStartOver}
          disabled={generating}
          className="font-mono font-semibold"
        >
          <RotateCcw className="h-4 w-4 mr-2" />
          Start Over
        </Button>
        {showGenerate && onGenerate && (
          <Button
            onClick={onGenerate}
            disabled={generating}
            className="font-mono font-semibold"
          >
            {generating ? "Generating Documents..." : "Generate Deliverables"}
            {!generating && <ArrowRight className="h-4 w-4 ml-2" />}
          </Button>
        )}
      </div>
    </div>
  );
}
