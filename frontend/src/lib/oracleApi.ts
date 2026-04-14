/**
 * Oracle API helpers.
 *
 * All fetch calls in this module target the Next.js server-side proxy
 * (`/api/oracle/...` — see `app/api/oracle/[...path]/route.ts`).
 * The proxy injects the real API key before forwarding to the Oracle
 * backend, so the browser never sees or transmits credentials.
 *
 * TRUST BOUNDARY: Client  -->  Next.js route handler (adds API key)  -->  Oracle backend.
 * No secrets cross the browser boundary.
 */

/* ------------------------------------------------------------------ */
/*  API primitives                                                     */
/* ------------------------------------------------------------------ */

/** POST to the Oracle proxy. Accepts FormData (file uploads) or plain objects. */
export async function apiPost(
  path: string,
  body: FormData | object,
): Promise<Response> {
  const isFormData = body instanceof FormData;
  return fetch(`/api/oracle${path}`, {
    method: "POST",
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    body: isFormData ? body : JSON.stringify(body),
  });
}

/** GET from the Oracle proxy. Always bypasses the browser cache. */
export async function apiGet(path: string): Promise<Response> {
  return fetch(`/api/oracle${path}`, {
    method: "GET",
    cache: "no-store",
  });
}

/** DELETE via the Oracle proxy. */
export async function apiDelete(path: string): Promise<Response> {
  return fetch(`/api/oracle${path}`, {
    method: "DELETE",
  });
}

/* ------------------------------------------------------------------ */
/*  URL helpers                                                        */
/* ------------------------------------------------------------------ */

/**
 * Normalise a download URL returned by the backend so it always points
 * through the Next.js proxy (`/api/oracle/...`).
 */
export function normalizeDownloadUrl(
  url: string | null | undefined,
): string | null {
  if (!url) return null;
  if (url.startsWith("/api/oracle/")) return url;
  if (url.startsWith("/oracle/")) return `/api${url}`;
  return url;
}
