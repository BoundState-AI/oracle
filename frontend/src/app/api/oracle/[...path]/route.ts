import { NextRequest, NextResponse } from "next/server";

export const maxDuration = 300;

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.ORACLE_API_KEY ?? "";

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

  const body =
    req.method !== "GET" && req.method !== "HEAD"
      ? await req.arrayBuffer()
      : undefined;

  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body,
  });

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
