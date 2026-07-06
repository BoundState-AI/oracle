/**
 * DUDE API helpers + response contracts.
 *
 * All REST calls target the Next.js server-side proxy (`/api/dude/...` —
 * see `app/api/dude/[...path]/route.ts`), which injects the real API key.
 * The browser never sees credentials. Voice goes through the per-utterance
 * bridge (`app/api/dude/voice/[caseId]/route.ts`) via the useDudeVoice hook.
 *
 * Contract mirror of the backend (dude/api/app.py, spec v0.2 §2/§3):
 * safety payloads carry backend copy that MUST render verbatim — nothing
 * in this module or its consumers rewrites it.
 */

export interface DudeCase {
  case_id: string;
  title: string;
  status: string;
}

export interface SafetyResource {
  name: string;
  contact: string;
  note: string;
}

/** Safety payload shape shared by REST capture and the WS "safety" frame. */
export interface SafetyPayload {
  crisis: boolean;
  message: string;
  flags: string[];
  resources: SafetyResource[];
}

export interface CaptureResponse extends SafetyPayload {
  capture_id: string;
}

export type AnalysisMode =
  | "new_evidence"
  | "new_hypothesis_reanalysis"
  | "scope_change"
  | "no_new_data";

export interface AnalyzeResponse {
  run_id: string;
  mode: AnalysisMode;
  served_prior: boolean;
  summary: string;
  crisis_active: boolean;
}

/** An observed fact — backend statement rendered verbatim. */
export interface ObservedStatement {
  statement: string;
  user_confirmed: boolean;
}

/** An open unknown — backend statement plus its importance label. */
export interface UnknownStatement {
  statement: string;
  importance: string;
}

/** One adversary attack on a hypothesis, with the links it found weak. */
export interface AdversaryAttack {
  attack: string;
  unsupported_links: string[];
}

export type HypothesisArchetype =
  | "user_favored"
  | "boring"
  | "mixed_cause"
  | "missing_variable"
  | "adversarial_cause";

/** Evidence bands are words by contract — never numbers or percentages. */
export type EvidenceBand =
  | "supported"
  | "plausible"
  | "weakly_supported"
  | "unresolved"
  | "contradicted";

export interface Hypothesis {
  title: string;
  description: string;
  archetype: HypothesisArchetype;
  band: EvidenceBand;
  harm_class: string;
  falsifiers: string[];
  not_credible_here: boolean;
  attacks: AdversaryAttack[];
}

export interface LastRun {
  mode: AnalysisMode;
  summary: string;
  crisis_active: boolean;
  refusals: string[];
}

/** Full case state from GET /cases/{id} — Reality + Models + last run. */
export interface CaseDetail {
  case_id: string;
  title: string;
  status: string;
  observed: ObservedStatement[];
  inferred: string[];
  unknown: UnknownStatement[];
  hypotheses: Hypothesis[];
  last_run: LastRun | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/dude${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body?.detail ?? body?.error)
      .catch(() => null);
    throw new Error(detail || `${path} failed (${response.status})`);
  }
  return response.json();
}

export const fetchCases = () => request<DudeCase[]>("/cases");

export const createCase = (title: string) =>
  request<{ case_id: string }>("/cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });

export const captureText = (caseId: string, text: string) =>
  request<CaptureResponse>(`/cases/${encodeURIComponent(caseId)}/capture`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

export const analyzeCase = (caseId: string) =>
  request<AnalyzeResponse>(`/cases/${encodeURIComponent(caseId)}/analyze`, {
    method: "POST",
  });

export const fetchCaseDetail = (caseId: string) =>
  request<CaseDetail>(`/cases/${encodeURIComponent(caseId)}`);
