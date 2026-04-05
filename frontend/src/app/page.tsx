"use client";

import { useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import { BoundStateLogo } from "@/components/BoundStateLogo";
import { DropZone } from "@/components/DropZone";
import { ModeSelector, type ProcessingMode } from "@/components/ModeSelector";
import { StatusSpinner } from "@/components/StatusSpinner";
import { CritiquePanel } from "@/components/CritiquePanel";
import { DownloadPanel } from "@/components/DownloadPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Zap } from "lucide-react";

type Phase =
  | { step: "upload" }
  | { step: "analyzing"; logMessages: string[] }
  | {
      step: "critique";
      sessionId: string;
      critique: string;
    }
  | { step: "generating"; logMessages: string[] }
  | {
      step: "download";
      docxUrl: string | null;
      pptxUrl: string | null;
    };

async function apiPost(path: string, body: FormData | object): Promise<Response> {
  const isFormData = body instanceof FormData;
  return fetch(`/api/oracle${path}`, {
    method: "POST",
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    body: isFormData ? body : JSON.stringify(body),
  });
}

function connectSSE(
  sessionId: string,
  onLog: (msg: string) => void,
  onDone: (data: Record<string, unknown>) => void,
  onError: (err: string) => void,
): () => void {
  const url = `/api/oracle/stream/${sessionId}`;
  const eventSource = new EventSource(url);

  eventSource.addEventListener("log", (e) => {
    onLog(e.data);
  });

  eventSource.addEventListener("done", (e) => {
    try {
      const data = JSON.parse(e.data);
      onDone(data);
    } catch {
      onError("Failed to parse result");
    }
    eventSource.close();
  });

  eventSource.addEventListener("error", (e) => {
    if (e instanceof MessageEvent) {
      onError(e.data);
    } else {
      onError("Connection lost — Oracle may still be running");
    }
    eventSource.close();
  });

  return () => eventSource.close();
}

export default function OraclePage() {
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ProcessingMode>("review");
  const [phase, setPhase] = useState<Phase>({ step: "upload" });
  const cleanupRef = useRef<(() => void) | null>(null);

  const reset = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }
    setFile(null);
    setMode("review");
    setPhase({ step: "upload" });
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!file) return;

    setPhase({ step: "analyzing", logMessages: ["Starting Oracle..."] });

    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);

    try {
      const res = await apiPost("/analyze", form);
      if (!res.ok) {
        const msg =
          res.status === 401
            ? "Authentication error — contact admin"
            : "Oracle encountered an error. Try again.";
        toast.error(msg);
        setPhase({ step: "upload" });
        return;
      }

      const data = await res.json();
      const sessionId = data.session_id;

      // Connect to SSE stream for live updates
      const cleanup = connectSSE(
        sessionId,
        // onLog — append message to the live feed
        (msg) => {
          setPhase((prev) => {
            if (prev.step !== "analyzing") return prev;
            const updated = [...prev.logMessages, msg];
            // Keep last 20 messages to avoid unbounded growth
            return {
              ...prev,
              logMessages: updated.slice(-20),
            };
          });
        },
        // onDone — transition to critique or download
        (result) => {
          cleanupRef.current = null;
          if (result.status === "complete") {
            setPhase({
              step: "download",
              docxUrl: (result.docx_url as string) ?? null,
              pptxUrl: (result.pptx_url as string) ?? null,
            });
          } else if (result.status === "ready_to_generate") {
            setPhase({
              step: "critique",
              sessionId: result.session_id as string,
              critique: (result.critique as string) ?? "",
            });
          } else if (result.status === "error") {
            toast.error("Oracle review failed. Try again.");
            setPhase({ step: "upload" });
          }
        },
        // onError
        (err) => {
          cleanupRef.current = null;
          toast.error(err);
          setPhase({ step: "upload" });
        },
      );

      cleanupRef.current = cleanup;
    } catch {
      toast.error("Network error — check your connection and try again.");
      setPhase({ step: "upload" });
    }
  }, [file, mode]);

  const handleGenerate = useCallback(
    async (sessionId: string) => {
      setPhase({ step: "generating", logMessages: ["Building your documents..."] });

      try {
        const res = await apiPost("/generate", {
          session_id: sessionId,
          approved: true,
        });

        if (!res.ok) {
          toast.error("Oracle encountered an error. Try again.");
          setPhase({ step: "upload" });
          return;
        }

        const data = await res.json();
        setPhase({
          step: "download",
          docxUrl: data.docx_url ?? null,
          pptxUrl: data.pptx_url ?? null,
        });
      } catch {
        toast.error("Network error — check your connection and try again.");
        setPhase({ step: "upload" });
      }
    },
    []
  );

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-card/80 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
          <div className="flex items-center gap-3">
            <BoundStateLogo variant="full" size="sm" />
            <div className="h-5 w-px bg-border" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Oracle
            </span>
          </div>
          {/* TODO: Add Clerk UserButton when auth is configured */}
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1">
        <div className="mx-auto max-w-3xl px-4 py-8">
          <div style={{ animation: "fade-in 0.3s ease-out" }}>
            {/* Phase 1: Upload */}
            {phase.step === "upload" && (
              <div className="space-y-6">
                <div>
                  <h1 className="text-2xl font-bold tracking-tight text-foreground">
                    Document Intelligence
                  </h1>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Upload a proposal and let Oracle refine it.
                  </p>
                </div>

                <Card className="border-border">
                  <CardContent className="space-y-6 pt-6">
                    <DropZone file={file} onFileSelect={setFile} />
                    <ModeSelector value={mode} onChange={setMode} />

                    <Button
                      className="w-full"
                      size="lg"
                      disabled={!file}
                      onClick={handleAnalyze}
                    >
                      <Zap className="h-4 w-4" data-icon="inline-start" />
                      Analyze Document
                    </Button>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Phase 2a: Analyzing — live stream */}
            {phase.step === "analyzing" && (
              <StatusSpinner messages={phase.logMessages} />
            )}

            {/* Phase 2b: Critique (review mode) */}
            {phase.step === "critique" && (
              <CritiquePanel
                critique={phase.critique}
                onStartOver={reset}
                onGenerate={() => handleGenerate(phase.sessionId)}
                generating={false}
              />
            )}

            {/* Phase 2c: Generating docs */}
            {phase.step === "generating" && (
              <StatusSpinner messages={phase.logMessages} />
            )}

            {/* Phase 3: Download */}
            {phase.step === "download" && (
              <DownloadPanel
                originalName={file?.name ?? "document"}
                docxUrl={phase.docxUrl}
                pptxUrl={phase.pptxUrl}
                onStartOver={reset}
              />
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border py-4">
        <div className="mx-auto max-w-3xl px-4">
          <p className="text-xs text-muted-foreground text-center">
            BoundState Technologies &mdash; All outputs are draft artifacts pending responsible human review.
          </p>
        </div>
      </footer>
    </div>
  );
}
