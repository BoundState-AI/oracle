/**
 * HEARTH API helpers + response contracts.
 *
 * All calls target the Next.js server-side proxy (`/api/hearth/...` — see
 * `app/api/hearth/[...path]/route.ts`), which injects the real API key.
 * The browser never sees credentials.
 *
 * Contract mirror of the backend (HEARTH spec v0.3 §2.5, §11): a refusal is
 * a RESULT (HTTP 200, refused=true), never a transport error — the
 * scrubber's exit-2 semantics expressed over HTTP.
 */

export interface ScrubFinding {
  document: string;
  clause_ref: string;
  category:
    | "fee"
    | "scope"
    | "backstop"
    | "default_trap"
    | "deadline"
    | "waiver"
    | "integrity";
  severity: "info" | "warn" | "flag" | "refuse";
  found: string;
  default_analysis: string;
  exposure_usd: number | null;
  suggested_template: string | null;
  requires_human_review: true;
  jurisdiction_basis: string;
}

export interface ScrubResponse {
  document: string;
  document_sha256: string | null;
  pack: string | null;
  run_date: string;
  target_price_usd: number | null;
  refused: boolean;
  refusal_reason: string | null;
  findings: ScrubFinding[];
  provisional_findings: number;
  rendered_report: string;
  audit_artifact: string;
  legal_banner: string;
}

export interface HearthPackInfo {
  name: string;
  pack_id: string;
  status: "provisional" | "reviewed" | "deprecated";
  owner: string;
  rules: number;
  provisional_rules: number;
}

export interface HearthPacksResponse {
  packs: HearthPackInfo[];
  legal_banner: string;
}

export async function fetchHearthPacks(): Promise<HearthPacksResponse> {
  const response = await fetch("/api/hearth/packs", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load jurisdiction packs (${response.status})`);
  }
  return response.json();
}

export async function scrubDocument(
  file: File,
  pack: string,
  targetPrice: number | null
): Promise<ScrubResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("pack", pack);
  if (targetPrice !== null) {
    form.append("target_price", String(targetPrice));
  }
  const response = await fetch("/api/hearth/scrub", {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body?.detail ?? body?.error)
      .catch(() => null);
    throw new Error(detail || `Scrub request failed (${response.status})`);
  }
  return response.json();
}

/* ------------------------------------------------------------------ */
/*  Phase-3 property-intelligence surface (§14 P3-C)                   */
/* ------------------------------------------------------------------ */

export interface HearthProperty {
  property_uid: string;
  address: string;
  parcels: string[];
  match_confidence: number;
  manual_override: boolean;
  joins_blocked: boolean;
  evidence_fields: string[];
}

export interface PropertyAlert {
  property_uid: string;
  rule_id: string;
  category: "landmine";
  status: "alert" | "clear" | "insufficient_evidence";
  severity: "info" | "warn" | "flag" | null;
  summary: string;
  analysis: string;
  evidence: {
    field: string;
    value: number | string;
    source: string;
    retrieved: string;
    confidence: number;
  }[];
  requires_human_review: true;
}

export interface ScanResponse {
  property_uid: string;
  pack: string | null;
  run_date: string;
  refused: boolean;
  refusal_reason: string | null;
  alerts: PropertyAlert[];
  rendered_report: string;
  audit_artifact: string;
  legal_banner: string;
}

export interface PullSource {
  source_id: string;
  description: string;
  format: string;
  urls: string[];
  manual_steps: string[];
  then: string;
  notes: string;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api/hearth${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} failed (${response.status})`);
  return response.json();
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(`/api/hearth${path}`, { method: "POST", body: form });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((b) => b?.detail ?? b?.error)
      .catch(() => null);
    throw new Error(detail || `${path} failed (${response.status})`);
  }
  return response.json();
}

export const fetchProperties = () =>
  getJson<{ store: string; properties: HearthProperty[] }>("/properties");

export const fetchPullPlan = () =>
  getJson<{ sources: PullSource[] }>("/pull-plan");

export function scanProperty(property: string, pack = "CO-Larimer") {
  const form = new FormData();
  form.append("property", property);
  form.append("pack", pack);
  return postForm<ScanResponse>("/scan", form);
}

export function ingestExport(file: File, adapter: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("adapter", adapter);
  return postForm<{ refused: boolean; reason?: string; outcomes?: Record<string, number>; conflicts?: string[]; evidence_rows?: number }>("/ingest", form);
}

export function computeWells(file: File, radiusFt = 2000) {
  const form = new FormData();
  form.append("file", file);
  form.append("radius_ft", String(radiusFt));
  return postForm<{ refused: boolean; reason?: string; identities_annotated?: number; wells_parsed?: number }>("/wells", form);
}

export function stampRadon(county = "Larimer") {
  const form = new FormData();
  form.append("county", county);
  return postForm<{ refused: boolean; reason?: string; zone?: number; identities_stamped?: number }>("/radon", form);
}

export function addEvidence(property: string, field: string, value: string, note: string) {
  const form = new FormData();
  form.append("property", property);
  form.append("field", field);
  form.append("value", value);
  form.append("source_note", note);
  return postForm<{ refused: boolean; reason?: string; field?: string }>("/evidence", form);
}
