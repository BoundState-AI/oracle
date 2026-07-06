/**
 * Evidence-state lines for the DUDE home screen (mobile vision v0.1).
 *
 * Recent cases speak decision state, never psychology: "Waiting for new
 * data" / "New information received" / "No active decision". The backend
 * case listing carries no last-run mode, so the last analysis mode seen
 * by THIS client is remembered in localStorage when Analyze completes on
 * the case screen and read back on the home screen. A case with no
 * remembered analysis reads "No active decision".
 */

"use client";

import type { AnalysisMode } from "@/lib/dudeApi";

const KEY_PREFIX = "dude:last-mode:";

export const NO_DECISION_LINE = "No active decision";

// WHY every non-gate mode maps to "New information received": any mode
// other than no_new_data means the engine ran fresh because something new
// (evidence, hypothesis, scope) entered the case. The home screen speaks
// only the vision's three evidence-state lines — never engine jargon.
const MODE_LINES: Record<AnalysisMode, string> = {
  no_new_data: "Waiting for new data",
  new_evidence: "New information received",
  new_hypothesis_reanalysis: "New information received",
  scope_change: "New information received",
};

/** Persist the mode of the analysis that just ran for `caseId`. */
export function rememberLastMode(caseId: string, mode: AnalysisMode): void {
  try {
    window.localStorage.setItem(KEY_PREFIX + caseId, mode);
  } catch {
    // Storage denied (private mode, quota): the home line simply stays
    // "No active decision" — never worth failing an analysis render.
  }
}

/** The one-line evidence-state status for a case on the home screen. */
export function evidenceStateLine(caseId: string): string {
  try {
    const stored = window.localStorage.getItem(KEY_PREFIX + caseId);
    if (stored && stored in MODE_LINES) {
      return MODE_LINES[stored as AnalysisMode];
    }
  } catch {
    // Unreadable storage reads as no remembered analysis.
  }
  return NO_DECISION_LINE;
}
