/**
 * VerdictIndicator — shows oracle verdicts and veto status.
 * Displays whether a reviewer verdict blocked or constrained the coordinator decision.
 */

"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";

interface VerdictIndicatorProps {
  hasUnanimousMajorRevision?: boolean;
  overriddenVerdicts?: string[];
  vetoApplied?: boolean;
}

export function VerdictIndicator({
  hasUnanimousMajorRevision = false,
  overriddenVerdicts = [],
  vetoApplied = false,
}: VerdictIndicatorProps) {
  if (!hasUnanimousMajorRevision && overriddenVerdicts.length === 0) {
    return null;
  }

  if (vetoApplied) {
    return (
      <div className="space-y-2 p-3 bg-red-500/10 border border-red-500/30 rounded-md">
        <div className="flex items-start gap-2">
          <AlertTriangle className="h-5 w-5 text-consensus-blocked flex-shrink-0 mt-0.5" />
          <div>
            <div className="font-mono text-sm font-semibold text-consensus-blocked">
              Veto Applied
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Unanimous reviewer dissent blocked coordinator recommendation. Escalated to human review.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (overriddenVerdicts.length > 0) {
    return (
      <div className="space-y-2 p-3 bg-amber-500/10 border border-amber-500/30 rounded-md">
        <div className="flex items-start gap-2">
          <AlertTriangle className="h-5 w-5 text-consensus-stable flex-shrink-0 mt-0.5" />
          <div>
            <div className="font-mono text-sm font-semibold text-consensus-stable">
              Override Disclosed
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Coordinator overrode reviewer verdicts:
            </p>
            <div className="mt-2 text-xs space-y-1">
              {overriddenVerdicts.map((verdict, i) => (
                <div key={i} className="font-mono text-muted-foreground">
                  → {verdict}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs text-consensus-full">
      <CheckCircle2 className="h-4 w-4" />
      <span className="font-mono">All reviewer verdicts aligned</span>
    </div>
  );
}
