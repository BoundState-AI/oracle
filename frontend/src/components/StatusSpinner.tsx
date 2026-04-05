"use client";

interface StatusSpinnerProps {
  messages: string[];
}

export function StatusSpinner({ messages }: StatusSpinnerProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-6 py-16">
      {/* Orbital spinner matching BoundState atomic brand */}
      <div className="relative h-16 w-16">
        <div className="absolute inset-0 rounded-full border-2 border-muted" />
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

      {/* Live log feed */}
      <div className="w-full max-w-lg space-y-1">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`text-xs font-mono transition-opacity duration-300 ${
              i === messages.length - 1
                ? "text-foreground"
                : "text-muted-foreground/60"
            }`}
          >
            <span className="text-ring/60 mr-2">{'>'}</span>
            {msg}
          </div>
        ))}
        {messages.length > 0 && (
          <div className="text-xs font-mono text-muted-foreground/40 animate-pulse">
            <span className="text-ring/60 mr-2">{'>'}</span>
            _
          </div>
        )}
      </div>
    </div>
  );
}
