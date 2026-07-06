/**
 * Authentication Middleware — Clerk when configured, password gate otherwise.
 *
 * WHY two modes: the DUDE deployment must be self-sufficient without a
 * Clerk dashboard. When NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is present,
 * Clerk protects the routes exactly as before. When it is absent, a
 * Basic-Auth gate (username "dude", password = DUDE_WEB_PASSWORD env)
 * protects the same routes — the browser caches the credential and
 * attaches it to same-origin fetches, so the API proxies stay covered.
 * If DUDE_WEB_PASSWORD is also unset, everything protected returns 503:
 * fail closed, never open.
 *
 * Routes:
 *   - /workspace/*, /api/oracle/*, /hearth/*, /api/hearth/*,
 *     /dude/*, /api/dude/* — protected
 *   - / (landing), /sign-in, /health, _next/* — public
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher([
  "/workspace(.*)",
  "/api/oracle(.*)",
  "/hearth(.*)",
  "/api/hearth(.*)",
  "/dude(.*)",
  "/api/dude(.*)",
]);

const clerkConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

function passwordGate(req: NextRequest): NextResponse {
  if (!isProtectedRoute(req)) {
    return NextResponse.next();
  }
  const expected = process.env.DUDE_WEB_PASSWORD ?? "";
  if (!expected) {
    // Fail closed: no auth configured means no access, never open access.
    return new NextResponse("Auth not configured", { status: 503 });
  }
  const header = req.headers.get("authorization") ?? "";
  if (header.startsWith("Basic ")) {
    const [user, ...rest] = atob(header.slice(6)).split(":");
    if (user === "dude" && rest.join(":") === expected) {
      return NextResponse.next();
    }
  }
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="DUDE"' },
  });
}

const handler = clerkConfigured
  ? clerkMiddleware(async (auth, req) => {
      if (isProtectedRoute(req)) {
        await auth.protect();
      }
    })
  : passwordGate;

export default handler;

export const config = {
  matcher: [
    // Skip Next.js internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
