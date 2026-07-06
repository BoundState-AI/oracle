/**
 * DudeLayout — DUDE route shell owning the standalone-PWA viewport.
 *
 * WHY a nested layout: viewport-fit=cover lets the installed DUDE surface
 * draw edge-to-edge behind the iPhone notch/home indicator — the screens
 * pad themselves with env(safe-area-inset-*) — and the dark theme-color
 * keeps the status bar calm. Scoped here so Oracle/HEARTH keep the
 * default viewport.
 */

import type { Viewport } from "next";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // Matches --background in globals.css so the notch area blends in.
  themeColor: "#0f1419",
};

export default function DudeLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
