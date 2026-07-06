/**
 * DUDE API Proxy Route
 *
 * WHY this exists: same trust boundary as the Oracle and HEARTH proxies —
 * the backend's /dude/* endpoints sit behind the X-API-Key gate, and this
 * route keeps ORACLE_API_KEY server-side so browser clients never see it.
 * All DUDE REST calls go through /api/dude/* which this route rewrites to
 * the backend.
 *
 * Trust boundary: Browser → this proxy (adds API key) → backend /dude/*.
 * The voice websocket does NOT go through here — route handlers cannot hold
 * a WebSocket open (see app/api/dude/voice/[caseId]/route.ts for the
 * per-utterance bridge).
 */

import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.ORACLE_API_KEY ?? "";

// Fail loudly if the API key is not configured (mirrors the Oracle proxy).
if (!API_KEY && process.env.NODE_ENV === "production") {
  throw new Error(
    "ORACLE_API_KEY is not set.  The API proxy cannot function without it."
  );
}

// DUDE REST bodies are small JSON (case titles, capture text). 1 MiB is
// generous; audio goes through the voice bridge, not here.
const MAX_BODY_BYTES = 1024 * 1024;

// Analyze runs the full pipeline (extraction → adversary → synthesis) and
// may call live model passes, so it needs more headroom than a scrub.
const FETCH_TIMEOUT_MS = 120_000;

async function proxy(req: NextRequest) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/api\/dude/, "");
  const target = `${API_BASE}/dude${path}${url.search}`;

  const headers = new Headers();
  headers.set("X-API-Key", API_KEY);

  const contentType = req.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }

  let body: ArrayBuffer | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return NextResponse.json(
        { error: "Request body exceeds the 1 MB limit" },
        { status: 413 }
      );
    }
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeout);
    if (err instanceof DOMException && err.name === "AbortError") {
      return NextResponse.json(
        { error: "Backend request timed out" },
        { status: 504 }
      );
    }
    return NextResponse.json({ error: "Backend unavailable" }, { status: 502 });
  }
  clearTimeout(timeout);

  const responseBody = await upstream.arrayBuffer();
  return new NextResponse(responseBody, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}

export const GET = proxy;
export const POST = proxy;
