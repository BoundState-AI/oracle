/**
 * Clerk Authentication Middleware
 *
 * WHY this exists: The sign-in page and ClerkProvider were present but no
 * middleware enforced authentication on protected routes.  Without this,
 * /workspace and /api/oracle/* were accessible to unauthenticated users.
 *
 * Routes:
 *   - /workspace/* — requires sign-in, redirects to /sign-in if not
 *   - /api/oracle/* — requires sign-in (browser-facing proxy)
 *   - /hearth/* and /api/hearth/* — requires sign-in (founder-mode HEARTH)
 *   - / (landing), /sign-in, /health, _next/* — public
 */

import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher([
  "/workspace(.*)",
  "/api/oracle(.*)",
  "/hearth(.*)",
  "/api/hearth(.*)",
]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
