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
