/**
 * RootLayout — application shell with ClerkProvider auth and dark-mode-first theme.
 * Wraps every page with the Inter font, Sonner toast provider, and global styles.
 */

import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Inter } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Oracle | BoundState",
  description: "Document intelligence platform by BoundState Technologies",
  // PWA install surface for DUDE (Add to Home Screen on iOS): manifest +
  // apple-web-app metadata make /dude launch standalone from the home
  // screen. Harmless for the oracle/hearth pages, which share the shell.
  manifest: "/dude/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "DUDE",
  },
  icons: {
    apple: "/dude/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} h-full dark`}>
      <body className="min-h-full flex flex-col antialiased font-sans">
        <ClerkProvider>
          {children}
          <Toaster />
        </ClerkProvider>
      </body>
    </html>
  );
}
