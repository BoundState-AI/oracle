"use client";

import { useEffect, useState } from "react";

interface StatusSpinnerProps {
  messages?: string[];
}

const DEFAULT_MESSAGES = [
  "Extracting document content...",
  "Running Oracle analysis...",
  "Generating polished outputs...",
];

export function StatusSpinner({
  messages = DEFAULT_MESSAGES,
}: StatusSpinnerProps) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setIndex((i) => (i + 1) % messages.length);
    }, 3000);
    return () => clearInterval(interval);
  }, [messages.length]);

  return (
    <div className="flex flex-col items-center justify-center gap-6 py-16">
      {/* Orbital spinner matching BoundState atomic brand */}
      <div className="relative h-16 w-16">
        <div
          className="absolute inset-0 rounded-full border-2 border-muted"
        />
        <div
          className="absolute inset-0 rounded-full border-2 border-transparent border-t-ring"
          style={{ animation: "spin-slow 1.2s linear infinite" }}
        />
        <div
          className="absolute inset-2 rounded-full border-2 border-transparent border-t-ring/60"
          style={{ animation: "spin-slow 1.8s linear infinite reverse" }}
        />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-2 w-2 rounded-full bg-ring" />
        </div>
      </div>

      <p className="text-sm text-muted-foreground animate-pulse">
        {messages[index]}
      </p>
    </div>
  );
}
