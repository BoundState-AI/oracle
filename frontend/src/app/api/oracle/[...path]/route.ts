/**
 * Oracle API Proxy Route
 *
 * WHY this exists: The Oracle backend requires an API key (X-API-Key header)
 * for all /oracle/* endpoints.  This proxy keeps ORACLE_API_KEY server-side
 * so browser clients never see it.  All frontend API calls go through
 * /api/oracle/* which this route rewrites to the backend.
 *
 * Trust boundary: Browser → this proxy (adds API key) → Oracle backend.
 * The proxy MUST validate that the API key is configured at startup and
 * enforce request size limits to prevent abuse.
 */

import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 800;

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.ORACLE_API_KEY ?? "";

// Fail loudly if the API key is not configured.  Without it, all proxied
// requests go through unauthenticated, which is a security gap.
if (!API_KEY && process.env.NODE_ENV === "production") {
  throw new Error(
    "ORACLE_API_KEY is not set.  The API proxy cannot function without it."
  );
}

// 50 MB — matches the backend's upload limit.  Prevents a malicious client
// from proxying arbitrarily large payloads through the serverless function.
const MAX_BODY_BYTES = 50 * 1024 * 1024;

// 60 seconds for non-streaming requests.  SSE streams use the full
// maxDuration (800s) because reviews can take minutes.
const FETCH_TIMEOUT_MS = 60_000;

async function proxy(req: NextRequest) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/api\/oracle/, "");
  const target = `${API_BASE}/oracle${path}${url.search}`;

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
        { error: `Request body exceeds ${MAX_BODY_BYTES / (1024 * 1024)} MB limit` },
        { status: 413 }
      );
    }
  }

  // For non-streaming requests, apply a timeout so we don't hold the
  // serverless function for the full maxDuration on a hung backend.
  // SSE streams are detected after the initial response and bypass this.
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
    return NextResponse.json(
      { error: "Backend unavailable" },
      { status: 502 }
    );
  }
  clearTimeout(timeout);

  const upstreamContentType =
    upstream.headers.get("content-type") ?? "application/json";

  // Stream SSE responses through without buffering
  if (upstreamContentType.includes("text/event-stream")) {
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
        "x-accel-buffering": "no",
      },
    });
  }

  // Buffer non-streaming responses normally
  const responseBody = await upstream.arrayBuffer();

  return new NextResponse(responseBody, {
    status: upstream.status,
    headers: {
      "content-type": upstreamContentType,
    },
  });
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
