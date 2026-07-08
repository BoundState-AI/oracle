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

/**
 * Backend triage word for an unknown: worth chasing, parked, or real but
 * not legitimately accessible ("do not chase" — named and left).
 */
export type UnknownPursuit = "pursue" | "hold" | "do not chase";

/** An open unknown — backend statement plus importance + pursuit labels. */
export interface UnknownStatement {
  statement: string;
  importance: string;
  pursuit: UnknownPursuit;
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

/** How trigger overlap adjusted the run: not at all, widened, or flagged. */
export type AdjustmentEffect = "none" | "widen" | "attend";

/**
 * The single confirmed-family overlap statistic (trigger spec v1.1 R8):
 * a LEVEL WORD, never a count and never a score.
 */
export type OverlapLevel = "none" | "low" | "moderate" | "high";

export interface LastRun {
  mode: AnalysisMode;
  summary: string;
  crisis_active: boolean;
  refusals: string[];
  /** Matched pattern names that fed the adjustment (backend copy, verbatim). */
  trigger_matches: string[];
  /** How many legacy patterns were checked (kept for contract mirroring). */
  trigger_total: number;
  /** Backend note on what the overlap did to the analysis — verbatim. */
  adjustment_note: string;
  adjustment_effect: AdjustmentEffect;
  /** The run's confirmed-family overlap level (v1.1 R8) — a band word. */
  trigger_overlap: OverlapLevel;
  /** De-identified labels of the confirmed families behind the level. */
  overlap_labels: string[];
  /**
   * Vetted distortion copy (v1.1 R3), rendered VERBATIM. The backend
   * serves it empty below moderate overlap and always empty in crisis.
   */
  distortion_block: string;
  /** Exact vetted no-match copy (R3 mirrored invariant) — verbatim. */
  no_match_copy: string;
}

/** A model-assessed trigger proposal awaiting the user's confirm/deny (R5). */
export interface TriggerProposal {
  assessment_id: string;
  /** De-identified family label — backend copy, verbatim. Never a score. */
  label: string;
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
  /** Proposals still awaiting user disposition — live store state. */
  trigger_proposals: TriggerProposal[];
  /** Vetted "possible overlap" template copy — verbatim, "" when none. */
  possible_overlap_note: string;
}

/** One trigger-family feature shape for the Lab's "why" (descriptions only). */
export interface TriggerFeatureView {
  slug: string;
  description: string;
  feature_type: string;
}

/** Evidence provenance for the Lab's "why": SOURCE TYPES with counts —
 * never response text, never scores (v1.1 R6). */
export interface EvidenceSourceCount {
  source_type: string;
  count: number;
}

export interface TriggerFamilyView {
  slug: string;
  label: string;
  description: string;
  /** Profile status word (candidate / self_report_supported / ...). */
  status: string;
  /** WIDEN/ATTEND calibration tag word. */
  calibration: string;
  /** Vetted low-diagnostic caveat (R8) — verbatim, "" when none. */
  fire_rate_caveat: string;
  features: TriggerFeatureView[];
  evidence_sources: EvidenceSourceCount[];
}

export interface CalibrationPromptView {
  prompt_id: string;
  text: string;
}

/** One rating unit: a single scenario, or a matched pair (two scenarios). */
export interface CalibrationUnit {
  kind: "single" | "pair";
  pair_id: string | null;
  prompts: CalibrationPromptView[];
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

/** R5 disposition — confirmation supersedes the proposal record with
 * user_confirmed=true on the backend; never a flag flip. */
const disposeAssessment = (caseId: string, assessmentId: string, verb: string) =>
  request<{ assessment_id: string }>(
    `/cases/${encodeURIComponent(caseId)}/assessments/${encodeURIComponent(
      assessmentId
    )}/${verb}`,
    { method: "POST" }
  );

export const confirmAssessment = (caseId: string, assessmentId: string) =>
  disposeAssessment(caseId, assessmentId, "confirm");

export const denyAssessment = (caseId: string, assessmentId: string) =>
  disposeAssessment(caseId, assessmentId, "deny");

export const fetchTriggerFamilies = () =>
  request<TriggerFamilyView[]>("/triggers/families");

export const fetchPendingCalibration = () =>
  request<CalibrationUnit[]>("/triggers/calibration/pending");

/** POST one Lab rating. The backend stamps the declared scale, session,
 * and state_at_capture — the client sends only the prompt and the score. */
export const submitCalibration = (promptId: string, rawScore: number) =>
  request<{ response_id: string }>("/triggers/calibration", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt_id: promptId, raw_score: rawScore }),
  });
