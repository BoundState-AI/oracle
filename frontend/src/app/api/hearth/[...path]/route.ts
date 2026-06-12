/**
 * HEARTH API Proxy Route
 *
 * WHY this exists: same trust boundary as the Oracle proxy — the backend's
 * /hearth/* endpoints sit behind the X-API-Key gate, and this route keeps
 * ORACLE_API_KEY server-side so browser clients never see it.  All HEARTH
 * frontend calls go through /api/hearth/* which this route rewrites to the
 * backend.
 *
 * Trust boundary: Browser → this proxy (adds API key) → backend /hearth/*.
 * NOTE (HEARTH spec §1.1): no BuyerPack material exists on this surface —
 * the scrubber consumes buyer-SUPPLIED documents only.  If a future organ
 * ever needs BuyerPack data, it must NOT be routed through a server proxy.
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

// Matches the backend scrub limit (MAX_DOCUMENT_BYTES = 16 MiB) plus a small
// allowance for multipart framing — the backend remains the authority.
const MAX_BODY_BYTES = 17 * 1024 * 1024;

// Scrubs are deterministic and fast; a hung backend should fail in seconds,
// not hold the serverless function open.
const FETCH_TIMEOUT_MS = 60_000;

async function proxy(req: NextRequest) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/api\/hearth/, "");
  const target = `${API_BASE}/hearth${path}${url.search}`;

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
        { error: "Request body exceeds the 16 MB scrub limit" },
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
