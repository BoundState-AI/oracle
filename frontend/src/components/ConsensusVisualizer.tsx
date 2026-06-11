/**
 * ConsensusVisualizer — visual representation of consensus type and oracle positions.
 * Shows convergence status with icon-based oracle representation.
 */

"use client";

import { Check, AlertCircle, X } from "lucide-react";

interface ConsensusVisualizerProps {
  consensusType: "full_agreement" | "stable_with_notes" | "blocked" | string;
  oracleCount?: number;
  verdictSummary?: string;
}

export function ConsensusVisualizer({
  consensusType,
  oracleCount = 4,
  verdictSummary,
}: ConsensusVisualizerProps) {
  const getConsensusInfo = (type: string) => {
    switch (type) {
      case "full_agreement":
        return {
          icon: Check,
          label: "Full Agreement",
          color: "consensus-full",
          description: "All oracles converged.",
        };
      case "stable_with_notes":
        return {
          icon: AlertCircle,
          label: "Stable with Notes",
          color: "consensus-stable",
          description: "Convergence with unresolved findings.",
        };
      case "blocked":
        return {
          icon: X,
          label: "Blocked on Tradeoff",
          color: "consensus-blocked",
          description: "System halted on unresolved disagreement.",
        };
      default:
        return {
          icon: AlertCircle,
          label: "Unknown",
          color: "consensus-stable",
          description: "Consensus status unclear.",
        };
    }
  };

  const info = getConsensusInfo(consensusType);
  const IconComponent = info.icon;

  return (
    <div className="space-y-3">
      {/* Main consensus badge */}
      <div className={`consensus-badge ${info.color}`}>
        <IconComponent className="h-5 w-5" />
        <span>{info.label}</span>
      </div>

      {/* Description */}
      <p className="text-sm text-muted-foreground">{info.description}</p>

      {/* Oracle positions visualization */}
      {verdictSummary && (
        <div className="mt-4 p-3 bg-card border border-border rounded-md">
          <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-2">
            Reviewer Verdicts
          </div>
          <div className="text-sm text-foreground whitespace-pre-wrap font-mono">
            {verdictSummary}
          </div>
        </div>
      )}

      {/* Oracle count indicator */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-mono">{oracleCount} oracles</span>
        <div className="flex gap-1">
          {Array.from({ length: oracleCount }).map((_, i) => (
            <div
              key={i}
              className="w-2 h-2 rounded-full bg-primary/60"
              title={`Oracle ${i + 1}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
