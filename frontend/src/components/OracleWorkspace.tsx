"use client";

/**
 * OracleWorkspace — thin orchestrator.
 *
 * Manages top-level tab state (Review | Pack Library | Chat) and the
 * shared state that crosses tab boundaries (selected packs, available
 * packs, the review phase lifecycle).  All heavy UI lives in the
 * extracted tab components; all API/SSE logic lives in `lib/`.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
// import { BoundStateLogo } from "@/components/BoundStateLogo";
import { OracleChatPanel } from "@/components/OracleChatPanel";
import { ReviewTab } from "@/components/ReviewTab";
import { PackLibraryTab } from "@/components/PackLibraryTab";
import { apiGet, apiPost, normalizeDownloadUrl } from "@/lib/oracleApi";
import { connectSSE, readLogMessages, startStatusPolling } from "@/lib/oracleSSE";
import type { Phase, PackSummary } from "@/components/ReviewTab";
import type { ProcessingMode } from "@/components/ModeSelector";
import { MIN_ROUNDS, MAX_ROUNDS } from "@/components/RoundsSelector";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function parsePackParts(parts: string): number[] {
  return parts
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((part) => Number.isInteger(part) && part > 0);
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function OracleWorkspace() {
  /* ---- tab state ---- */
  const [activeTab, setActiveTab] = useState<"review" | "packs" | "chat">("review");

  /* ---- review state ---- */
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ProcessingMode>("review");
  const [maxRounds, setMaxRounds] = useState<number>(1);
  const [phase, setPhase] = useState<Phase>({ step: "upload" });

  /* ---- shared pack state ---- */
  const [availablePacks, setAvailablePacks] = useState<PackSummary[]>([]);
  const [packsLoading, setPacksLoading] = useState(false);
  const [selectedPacks, setSelectedPacks] = useState<string[]>([]);
  const [packParts, setPackParts] = useState<Record<string, string>>({});

  /* ---- SSE / polling cleanup ---- */
  const cleanupRef = useRef<(() => void) | null>(null);

  const clearLiveJob = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }
  }, []);

  /* ---- pack loading (shared across tabs) ---- */

  const loadPacks = useCallback(async () => {
    setPacksLoading(true);
    try {
      const res = await apiGet("/packs");
      if (!res.ok) {
        throw new Error(`Failed to load packs (${res.status})`);
      }
      const data = (await res.json()) as { packs?: PackSummary[] };
      setAvailablePacks(data.packs ?? []);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load packs";
      toast.error(message);
    } finally {
      setPacksLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPacks();
  }, [loadPacks]);

  /* ---- review result handler ---- */

  const applyReviewResult = useCallback(
    (result: Record<string, unknown>) => {
      clearLiveJob();
      if (result.status === "error") {
        toast.error((result.error as string) ?? "Oracle review failed. Try again.");
        setPhase({ step: "upload" });
        return;
      }

      setPhase({
        step: "result",
        sessionId: (result.session_id as string) ?? "",
        critique:
          (result.findings_report as string) ??
          (result.critique as string) ??
          "No findings report was produced.",
        metrics: (result.metrics as Record<string, unknown>) ?? null,
        docxUrl: normalizeDownloadUrl((result.docx_url as string) ?? null),
        pptxUrl: normalizeDownloadUrl((result.pptx_url as string) ?? null),
        reportUrl: normalizeDownloadUrl((result.report_url as string) ?? null),
        metricsUrl: normalizeDownloadUrl((result.metrics_url as string) ?? null),
        complianceContextUrl: normalizeDownloadUrl(
          (result.compliance_context_url as string) ?? null,
        ),
        packSnapshotUrl: normalizeDownloadUrl(
          (result.pack_snapshot_url as string) ?? null,
        ),
      });
    },
    [clearLiveJob],
  );

  /* ---- reset ---- */

  const reset = useCallback(() => {
    clearLiveJob();
    setFile(null);
    setMode("review");
    setMaxRounds(1);
    setPhase({ step: "upload" });
    setSelectedPacks([]);
    setPackParts({});
  }, [clearLiveJob]);

  /* ---- computed pack-part map ---- */

  const selectedPackPartMap = selectedPacks.reduce<Record<string, number[]>>(
    (acc, slug) => {
      const parsed = parsePackParts(packParts[slug] ?? "");
      if (parsed.length > 0) {
        acc[slug] = parsed;
      }
      return acc;
    },
    {},
  );

  /* ---- analyze handler ---- */

  const handleAnalyze = useCallback(async () => {
    if (!file) return;

    setPhase({ step: "analyzing", logMessages: ["Starting Oracle..."] });

    const clampedRounds = Math.max(
      MIN_ROUNDS,
      Math.min(MAX_ROUNDS, maxRounds),
    );

    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    form.append("packs", JSON.stringify(selectedPacks));
    form.append("pack_parts", JSON.stringify(selectedPackPartMap));
    form.append("max_rounds", String(clampedRounds));

    try {
      const res = await apiPost("/analyze", form);
      if (!res.ok) {
        const message =
          res.status === 401
            ? "Authentication error — contact admin"
            : `Oracle encountered an error (${res.status}).`;
        toast.error(message);
        setPhase({ step: "upload" });
        return;
      }

      const data = (await res.json()) as { session_id: string };
      const sessionId = data.session_id;

      const cleanup = connectSSE(
        sessionId,
        (msg) => {
          setPhase((prev) => {
            if (prev.step !== "analyzing") return prev;
            return { ...prev, logMessages: [...prev.logMessages, msg].slice(-20) };
          });
        },
        applyReviewResult,
        (err, recoverable) => {
          if (recoverable) {
            setPhase((prev) => {
              if (prev.step !== "analyzing") return prev;
              return {
                ...prev,
                logMessages: [
                  ...prev.logMessages,
                  `${err} Oracle is still running — continuing via polling.`,
                ].slice(-20),
              };
            });

            cleanupRef.current = startStatusPolling(
              sessionId,
              applyReviewResult,
              (pollErr) => {
                setPhase((prev) => {
                  if (prev.step !== "analyzing") return prev;
                  return {
                    ...prev,
                    logMessages: [...prev.logMessages, `Polling: ${pollErr}`].slice(-20),
                  };
                });
              },
              (progressData) => {
                const logMessages = readLogMessages(progressData);
                if (logMessages.length === 0) return;
                setPhase((prev) => {
                  if (prev.step !== "analyzing") return prev;
                  return {
                    ...prev,
                    logMessages,
                  };
                });
              },
            );
            return;
          }

          clearLiveJob();
          toast.error(err);
          setPhase({ step: "upload" });
        },
      );

      cleanupRef.current = cleanup;
    } catch {
      toast.error("Network error — check your connection and try again.");
      setPhase({ step: "upload" });
    }
  }, [
    applyReviewResult,
    clearLiveJob,
    file,
    mode,
    maxRounds,
    selectedPacks,
    selectedPackPartMap,
  ]);

  /* ---- pack toggle ---- */

  const handleTogglePack = useCallback((slug: string) => {
    setSelectedPacks((prev) =>
      prev.includes(slug) ? prev.filter((item) => item !== slug) : [...prev, slug],
    );
  }, []);

  const handlePackPartsChange = useCallback((slug: string, value: string) => {
    setPackParts((prev) => ({ ...prev, [slug]: value }));
  }, []);

  const handlePackDeleted = useCallback((slug: string) => {
    setSelectedPacks((prev) => prev.filter((item) => item !== slug));
  }, []);

  /* ---- render ---- */

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-50 border-b border-border bg-card/80 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <div className="flex items-center gap-3">
            {/* <BoundStateLogo variant="full" size="sm" /> */}
            <div className="h-5 w-px bg-border" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Oracle
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("review")}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "review"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              Review
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("packs")}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "packs"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              Pack Library
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("chat")}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "chat"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              Chat
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="mx-auto max-w-6xl px-4 py-8">
          <div className="animate-fade-in">
            {activeTab === "review" && (
              <ReviewTab
                file={file}
                onFileSelect={setFile}
                mode={mode}
                onModeChange={setMode}
                maxRounds={maxRounds}
                onMaxRoundsChange={setMaxRounds}
                phase={phase}
                availablePacks={availablePacks}
                packsLoading={packsLoading}
                selectedPacks={selectedPacks}
                packParts={packParts}
                onTogglePack={handleTogglePack}
                onPackPartsChange={handlePackPartsChange}
                onRefreshPacks={() => void loadPacks()}
                onAnalyze={handleAnalyze}
                onStartOver={reset}
              />
            )}

            {activeTab === "packs" && (
              <PackLibraryTab
                availablePacks={availablePacks}
                packsLoading={packsLoading}
                onRefreshPacks={loadPacks}
                onPackDeleted={handlePackDeleted}
              />
            )}

            {activeTab === "chat" && (
              <OracleChatPanel
                availablePacks={availablePacks}
                selectedPacks={selectedPacks}
                onSelectPacks={setSelectedPacks}
                onRefreshPacks={loadPacks}
                packsLoading={packsLoading}
              />
            )}
          </div>
        </div>
      </main>

      <footer className="border-t border-border py-4">
        <div className="mx-auto max-w-6xl px-4">
          <p className="text-center text-xs text-muted-foreground">
            BoundState Technologies - All outputs are draft artifacts pending
            responsible human review.
          </p>
        </div>
      </footer>
    </div>
  );
}
