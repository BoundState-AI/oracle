"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Eye,
  Library,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
  WandSparkles,
  Zap,
} from "lucide-react";
import { BoundStateLogo } from "@/components/BoundStateLogo";
import { DropZone } from "@/components/DropZone";
import { ModeSelector, type ProcessingMode } from "@/components/ModeSelector";
import { StatusSpinner } from "@/components/StatusSpinner";
import { CritiquePanel } from "@/components/CritiquePanel";
import { DownloadPanel } from "@/components/DownloadPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Phase =
  | { step: "upload" }
  | { step: "analyzing"; logMessages: string[] }
  | {
      step: "result";
      sessionId: string;
      critique: string;
      metrics: Record<string, unknown> | null;
      docxUrl: string | null;
      pptxUrl: string | null;
      reportUrl: string | null;
      metricsUrl: string | null;
      complianceContextUrl: string | null;
      packSnapshotUrl: string | null;
    };

type PackSummary = {
  name: string;
  slug: string;
  schema: string;
  status: string;
  standard_id: string;
  description?: string;
  rule_count: number;
  version?: string;
  extraction_status?: string;
  promoted_by?: string | null;
  promoted_at?: string | null;
};

type PackDetail = PackSummary & {
  schema_version?: string;
  standard_title?: string;
  rendered?: string | null;
  chunk_failures?: Array<Record<string, unknown>>;
  oracle_metadata?: Record<string, unknown>;
};

type PackJob = {
  sessionId: string;
  logMessages: string[];
};

async function apiPost(path: string, body: FormData | object): Promise<Response> {
  const isFormData = body instanceof FormData;
  return fetch(`/api/oracle${path}`, {
    method: "POST",
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    body: isFormData ? body : JSON.stringify(body),
  });
}

async function apiGet(path: string): Promise<Response> {
  return fetch(`/api/oracle${path}`, {
    method: "GET",
    cache: "no-store",
  });
}

async function apiDelete(path: string): Promise<Response> {
  return fetch(`/api/oracle${path}`, {
    method: "DELETE",
  });
}

function normalizeDownloadUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("/api/oracle/")) return url;
  if (url.startsWith("/oracle/")) return `/api${url}`;
  return url;
}

function connectSSE(
  sessionId: string,
  onLog: (msg: string) => void,
  onDone: (data: Record<string, unknown>) => void,
  onError: (err: string, recoverable: boolean) => void,
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
      onError("Failed to parse result", false);
    }
    eventSource.close();
  });

  eventSource.addEventListener("error", (e) => {
    if (e instanceof MessageEvent) {
      onError(e.data, false);
    } else {
      onError("Live connection dropped — checking Oracle status...", true);
    }
    eventSource.close();
  });

  return () => eventSource.close();
}

function startStatusPolling(
  sessionId: string,
  onDone: (data: Record<string, unknown>) => void,
  onError: (err: string) => void,
  onProgress?: (data: Record<string, unknown>) => void,
): () => void {
  let active = true;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const tick = async () => {
    if (!active) return;
    try {
      const res = await apiGet(`/session/${sessionId}`);
      if (res.status === 404) {
        onDone({
          status: "error",
          error:
            "Oracle session was interrupted by a server restart or redeploy. Please start the review again.",
        });
        return;
      }
      if (!res.ok) {
        throw new Error(`Polling failed (${res.status})`);
      }
      const data = (await res.json()) as Record<string, unknown>;
      const status = data.status as string | undefined;
      if (status === "processing") {
        onProgress?.(data);
        timer = setTimeout(tick, 5000);
        return;
      }
      onDone(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Polling failed";
      if (!active) return;
      onError(message);
      timer = setTimeout(tick, 5000);
    }
  };

  void tick();

  return () => {
    active = false;
    if (timer) clearTimeout(timer);
  };
}

function badgeVariantForStatus(status: string | undefined) {
  if (status === "promoted") return "default";
  if (status === "draft") return "secondary";
  if (status === "error") return "destructive";
  return "outline";
}

function parsePackParts(parts: string): number[] {
  return parts
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((part) => Number.isInteger(part) && part > 0);
}

function readLogMessages(data: Record<string, unknown>): string[] {
  const value = data.log_messages;
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string").slice(-20);
}

export function OracleWorkspace() {
  const [activeTab, setActiveTab] = useState<"review" | "packs">("review");
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ProcessingMode>("review");
  const [phase, setPhase] = useState<Phase>({ step: "upload" });
  const [availablePacks, setAvailablePacks] = useState<PackSummary[]>([]);
  const [packsLoading, setPacksLoading] = useState(false);
  const [selectedPacks, setSelectedPacks] = useState<string[]>([]);
  const [packParts, setPackParts] = useState<Record<string, string>>({});
  const [selectedPackDetail, setSelectedPackDetail] = useState<PackDetail | null>(null);
  const [packDetailLoading, setPackDetailLoading] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [generateFile, setGenerateFile] = useState<File | null>(null);
  const [generateName, setGenerateName] = useState("");
  const [generateForceType, setGenerateForceType] = useState("");
  const [packJob, setPackJob] = useState<PackJob | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const generateInputRef = useRef<HTMLInputElement | null>(null);

  const clearLiveJob = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }
  }, []);

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

  const loadPackDetail = useCallback(async (slug: string) => {
    setPackDetailLoading(true);
    try {
      const res = await apiGet(`/packs/${slug}?verbose=true`);
      if (!res.ok) {
        throw new Error(`Failed to load pack detail (${res.status})`);
      }
      const data = (await res.json()) as PackDetail;
      setSelectedPackDetail(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load pack detail";
      toast.error(message);
    } finally {
      setPackDetailLoading(false);
    }
  }, []);

  const applyReviewResult = useCallback((result: Record<string, unknown>) => {
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
  }, [clearLiveJob]);

  const applyPackResult = useCallback(async (result: Record<string, unknown>) => {
    clearLiveJob();
    if (result.status === "error") {
      toast.error((result.error as string) ?? "Pack generation failed.");
      setPackJob(null);
      return;
    }

    setPackJob(null);
    const pack = result.pack as PackDetail | undefined;
    if (pack?.slug) {
      toast.success(`Pack ready: ${pack.slug}`);
      setSelectedPackDetail(pack);
      await loadPacks();
      return;
    }

    toast.success("Pack generation completed.");
    await loadPacks();
  }, [clearLiveJob, loadPacks]);

  const reset = useCallback(() => {
    clearLiveJob();
    setFile(null);
    setMode("review");
    setPhase({ step: "upload" });
    setSelectedPacks([]);
    setPackParts({});
  }, [clearLiveJob]);

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

  const handleAnalyze = useCallback(async () => {
    if (!file) return;

    setPhase({ step: "analyzing", logMessages: ["Starting Oracle..."] });

    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    form.append("packs", JSON.stringify(selectedPacks));
    form.append("pack_parts", JSON.stringify(selectedPackPartMap));

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
              (data) => {
                const logMessages = readLogMessages(data);
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
    selectedPacks,
    selectedPackPartMap,
  ]);

  const handleTogglePack = useCallback((slug: string) => {
    setSelectedPacks((prev) =>
      prev.includes(slug) ? prev.filter((item) => item !== slug) : [...prev, slug],
    );
  }, []);

  const handlePromotePack = useCallback(
    async (slug: string) => {
      const reviewer = window.prompt("Reviewer name for promotion:");
      if (!reviewer) return;

      try {
        const res = await apiPost(`/packs/${slug}/promote`, {
          reviewer,
          notes: null,
          allow_partial_promotion: false,
          override_hash_mismatch: false,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error((data.detail as string) ?? "Failed to promote pack");
        }
        toast.success(`Promoted pack: ${slug}`);
        await loadPacks();
        await loadPackDetail(slug);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to promote pack";
        toast.error(message);
      }
    },
    [loadPackDetail, loadPacks],
  );

  const handleDeletePack = useCallback(
    async (slug: string) => {
      if (!window.confirm(`Remove pack '${slug}' from the library?`)) return;
      try {
        const res = await apiDelete(`/packs/${slug}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error((data.detail as string) ?? "Failed to remove pack");
        }
        toast.success(`Removed pack: ${slug}`);
        setSelectedPackDetail((prev) => (prev?.slug === slug ? null : prev));
        setSelectedPacks((prev) => prev.filter((item) => item !== slug));
        await loadPacks();
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to remove pack";
        toast.error(message);
      }
    },
    [loadPacks],
  );

  const handleImportPack = useCallback(async () => {
    if (!importFile) return;

    const form = new FormData();
    form.append("file", importFile);

    try {
      const res = await apiPost("/packs/import", form);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((data.detail as string) ?? "Failed to import pack");
      }
      toast.success(`Imported pack: ${(data.pack?.slug as string) ?? importFile.name}`);
      setImportFile(null);
      await loadPacks();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to import pack";
      toast.error(message);
    }
  }, [importFile, loadPacks]);

  const clearImportFile = useCallback(() => {
    setImportFile(null);
    if (importInputRef.current) {
      importInputRef.current.value = "";
    }
  }, []);

  const clearGenerateFile = useCallback(() => {
    setGenerateFile(null);
    if (generateInputRef.current) {
      generateInputRef.current.value = "";
    }
  }, []);

  const handleGeneratePack = useCallback(async () => {
    if (!generateFile) return;

    setPackJob({ sessionId: "", logMessages: ["Starting pack generation..."] });
    const form = new FormData();
    form.append("file", generateFile);
    if (generateName.trim()) form.append("name", generateName.trim());
    if (generateForceType) form.append("force_type", generateForceType);

    try {
      const res = await apiPost("/packs/generate", form);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data.detail as string) ?? "Failed to start pack generation");
      }

      const data = (await res.json()) as { session_id: string };
      const sessionId = data.session_id;
      setPackJob({ sessionId, logMessages: ["Starting pack generation..."] });

      const cleanup = connectSSE(
        sessionId,
        (msg) => {
          setPackJob((prev) =>
            prev
              ? { ...prev, logMessages: [...prev.logMessages, msg].slice(-20) }
              : prev,
          );
        },
        (result) => {
          void applyPackResult(result);
        },
        (err, recoverable) => {
          if (recoverable) {
            setPackJob((prev) =>
              prev
                ? {
                    ...prev,
                    logMessages: [
                      ...prev.logMessages,
                      `${err} Oracle is still running — continuing via polling.`,
                    ].slice(-20),
                  }
                : prev,
            );
            cleanupRef.current = startStatusPolling(
              sessionId,
              (result) => {
                void applyPackResult(result);
              },
              (pollErr) => {
                setPackJob((prev) =>
                  prev
                    ? {
                        ...prev,
                        logMessages: [...prev.logMessages, `Polling: ${pollErr}`].slice(-20),
                      }
                    : prev,
                );
              },
              (data) => {
                const logMessages = readLogMessages(data);
                if (logMessages.length === 0) return;
                setPackJob((prev) =>
                  prev
                    ? {
                        ...prev,
                        logMessages,
                      }
                    : prev,
                );
              },
            );
            return;
          }

          clearLiveJob();
          setPackJob(null);
          toast.error(err);
        },
      );

      cleanupRef.current = cleanup;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to start pack generation";
      toast.error(message);
      setPackJob(null);
    }
  }, [applyPackResult, clearLiveJob, generateFile, generateForceType, generateName]);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-50 border-b border-border bg-card/80 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <div className="flex items-center gap-3">
            <BoundStateLogo variant="full" size="sm" />
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
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="mx-auto max-w-6xl px-4 py-8">
          <div style={{ animation: "fade-in 0.3s ease-out" }}>
            {activeTab === "review" && (
              <div className="space-y-6">
                {phase.step === "upload" && (
                  <>
                    <div>
                      <h1 className="text-2xl font-bold tracking-tight text-foreground">
                        Document Intelligence
                      </h1>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Review against selected authority packs, inspect findings, and
                        return polished deliverables.
                      </p>
                    </div>

                    <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
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

                      <Card className="border-border">
                        <CardHeader>
                          <div className="flex items-center justify-between gap-3">
                            <CardTitle className="text-lg font-semibold tracking-tight">
                              Compliance Packs
                            </CardTitle>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => void loadPacks()}
                            >
                              <RefreshCw className="h-3.5 w-3.5" data-icon="inline-start" />
                              Refresh
                            </Button>
                          </div>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          <div className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                            Oracle reviews only against the packs you select here. It does not silently blend the entire library.
                          </div>
                          {packsLoading ? (
                            <p className="text-sm text-muted-foreground">Loading pack library...</p>
                          ) : availablePacks.length === 0 ? (
                            <p className="text-sm text-muted-foreground">
                              No packs yet. Open the Pack Library tab to import or generate one.
                            </p>
                          ) : (
                            availablePacks.map((pack) => {
                              const selected = selectedPacks.includes(pack.slug);
                              return (
                                <div
                                  key={pack.slug}
                                  className={`rounded-xl border px-4 py-4 ${
                                    selected ? "border-ring bg-accent/40" : "border-border"
                                  }`}
                                >
                                  <label className="flex items-start gap-3">
                                    <input
                                      type="checkbox"
                                      className="mt-1"
                                      checked={selected}
                                      onChange={() => handleTogglePack(pack.slug)}
                                    />
                                    <div className="min-w-0 flex-1">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="text-sm font-medium text-foreground">
                                          {pack.name}
                                        </span>
                                        <Badge variant={badgeVariantForStatus(pack.status)}>
                                          {pack.status}
                                        </Badge>
                                        <Badge variant="outline">{pack.schema}</Badge>
                                      </div>
                                      <p className="mt-1 text-xs text-muted-foreground">
                                        {pack.standard_id || "Custom pack"} • {pack.rule_count} rules
                                      </p>
                                      {selected && pack.schema === "far" && (
                                        <div className="mt-3">
                                          <label className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                            Pack Parts
                                          </label>
                                          <input
                                            value={packParts[pack.slug] ?? ""}
                                            onChange={(event) =>
                                              setPackParts((prev) => ({
                                                ...prev,
                                                [pack.slug]: event.target.value,
                                              }))
                                            }
                                            placeholder="15,19,52"
                                            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none ring-0"
                                          />
                                        </div>
                                      )}
                                    </div>
                                  </label>
                                </div>
                              );
                            })
                          )}
                        </CardContent>
                      </Card>
                    </div>
                  </>
                )}

                {phase.step === "analyzing" && <StatusSpinner messages={phase.logMessages} />}

                {phase.step === "result" && (
                  <div className="space-y-6">
                    <CritiquePanel
                      critique={phase.critique}
                      metrics={phase.metrics}
                      onStartOver={reset}
                      showGenerate={false}
                    />
                    <DownloadPanel
                      originalName={file?.name ?? "document"}
                      docxUrl={phase.docxUrl}
                      pptxUrl={phase.pptxUrl}
                      reportUrl={phase.reportUrl}
                      metricsUrl={phase.metricsUrl}
                      complianceContextUrl={phase.complianceContextUrl}
                      packSnapshotUrl={phase.packSnapshotUrl}
                      onStartOver={reset}
                    />
                  </div>
                )}
              </div>
            )}

            {activeTab === "packs" && (
              <div className="space-y-6">
                <div>
                  <h1 className="text-2xl font-bold tracking-tight text-foreground">
                    Pack Library
                  </h1>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Manage compliance packs, generate new ones from source PDFs, and
                    promote reviewed packs into active use.
                  </p>
                </div>

                <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
                  <div className="space-y-6">
                    <Card className="border-border">
                      <CardHeader>
                        <CardTitle className="text-lg font-semibold tracking-tight">
                          Import Existing Pack
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <input
                          ref={importInputRef}
                          type="file"
                          accept=".json,application/json"
                          onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
                          className="hidden"
                        />
                        <div className="rounded-xl border border-dashed border-border bg-muted/20 p-4">
                          <div className="flex flex-wrap items-center gap-3">
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => importInputRef.current?.click()}
                            >
                              <Upload className="h-4 w-4" data-icon="inline-start" />
                              Choose Pack JSON
                            </Button>
                            {importFile ? (
                              <>
                                <span className="text-sm text-foreground">{importFile.name}</span>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  onClick={clearImportFile}
                                >
                                  Clear
                                </Button>
                              </>
                            ) : (
                              <span className="text-sm text-muted-foreground">
                                Upload an existing Oracle rule pack in JSON format.
                              </span>
                            )}
                          </div>
                        </div>
                        <input
                          value={importFile?.name ?? ""}
                          readOnly
                          placeholder="No JSON pack selected"
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-muted-foreground outline-none ring-0"
                        />
                        <Button className="w-full" onClick={handleImportPack} disabled={!importFile}>
                          <Upload className="h-4 w-4" data-icon="inline-start" />
                          Import Pack
                        </Button>
                      </CardContent>
                    </Card>

                    <Card className="border-border">
                      <CardHeader>
                        <CardTitle className="text-lg font-semibold tracking-tight">
                          Generate Pack from PDF
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <input
                          ref={generateInputRef}
                          type="file"
                          accept=".pdf,application/pdf"
                          onChange={(event) => setGenerateFile(event.target.files?.[0] ?? null)}
                          className="hidden"
                        />
                        <div className="rounded-xl border border-dashed border-border bg-muted/20 p-4">
                          <div className="flex flex-wrap items-center gap-3">
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => generateInputRef.current?.click()}
                            >
                              <Upload className="h-4 w-4" data-icon="inline-start" />
                              Choose Source PDF
                            </Button>
                            {generateFile ? (
                              <>
                                <span className="text-sm text-foreground">
                                  {generateFile.name}
                                </span>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  onClick={clearGenerateFile}
                                >
                                  Clear
                                </Button>
                              </>
                            ) : (
                              <span className="text-sm text-muted-foreground">
                                Upload a regulatory PDF and Oracle will build a draft pack.
                              </span>
                            )}
                          </div>
                        </div>
                        <input
                          value={generateFile?.name ?? ""}
                          readOnly
                          placeholder="No source PDF selected"
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-muted-foreground outline-none ring-0"
                        />
                        <input
                          value={generateName}
                          onChange={(event) => setGenerateName(event.target.value)}
                          placeholder="Optional pack name"
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none ring-0"
                        />
                        <select
                          value={generateForceType}
                          onChange={(event) => setGenerateForceType(event.target.value)}
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none ring-0"
                        >
                          <option value="">Auto-detect type</option>
                          <option value="tagged_standard">Tagged Standard</option>
                          <option value="far_style">FAR-style Regulation</option>
                          <option value="cfr_style">CFR-style Regulation</option>
                          <option value="generic">Generic</option>
                        </select>
                        <Button
                          className="w-full"
                          onClick={handleGeneratePack}
                          disabled={!generateFile}
                        >
                          <WandSparkles className="h-4 w-4" data-icon="inline-start" />
                          Generate Pack
                        </Button>
                      </CardContent>
                    </Card>

                    {packJob && <StatusSpinner messages={packJob.logMessages} />}
                  </div>

                  <div className="space-y-6">
                    <Card className="border-border">
                      <CardHeader>
                        <div className="flex items-center justify-between gap-3">
                          <CardTitle className="text-lg font-semibold tracking-tight">
                            Available Packs
                          </CardTitle>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => void loadPacks()}
                          >
                            <RefreshCw className="h-3.5 w-3.5" data-icon="inline-start" />
                            Refresh
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {packsLoading ? (
                          <p className="text-sm text-muted-foreground">Loading pack library...</p>
                        ) : availablePacks.length === 0 ? (
                          <p className="text-sm text-muted-foreground">
                            No packs in library yet.
                          </p>
                        ) : (
                          availablePacks.map((pack) => (
                            <div
                              key={pack.slug}
                              className="rounded-xl border border-border px-4 py-4"
                            >
                              <div className="flex flex-wrap items-start justify-between gap-3">
                                <div>
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-sm font-medium text-foreground">
                                      {pack.name}
                                    </span>
                                    <Badge variant={badgeVariantForStatus(pack.status)}>
                                      {pack.status}
                                    </Badge>
                                    <Badge variant="outline">{pack.schema}</Badge>
                                  </div>
                                  <p className="mt-1 text-xs text-muted-foreground">
                                    {pack.standard_id || "Custom pack"} • {pack.rule_count} rules
                                  </p>
                                </div>

                                <div className="flex flex-wrap gap-2">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => void loadPackDetail(pack.slug)}
                                  >
                                    <Eye className="h-3.5 w-3.5" data-icon="inline-start" />
                                    View
                                  </Button>
                                  {pack.status !== "promoted" && (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={() => void handlePromotePack(pack.slug)}
                                    >
                                      <ShieldCheck
                                        className="h-3.5 w-3.5"
                                        data-icon="inline-start"
                                      />
                                      Promote
                                    </Button>
                                  )}
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => void handleDeletePack(pack.slug)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" data-icon="inline-start" />
                                    Remove
                                  </Button>
                                </div>
                              </div>
                            </div>
                          ))
                        )}
                      </CardContent>
                    </Card>

                    <Card className="border-border">
                      <CardHeader>
                        <CardTitle className="text-lg font-semibold tracking-tight">
                          Pack Detail
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        {packDetailLoading ? (
                          <p className="text-sm text-muted-foreground">Loading pack detail...</p>
                        ) : !selectedPackDetail ? (
                          <p className="text-sm text-muted-foreground">
                            Select a pack to inspect its schema, status, and rendered contents.
                          </p>
                        ) : (
                          <div className="space-y-4">
                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className="rounded-md border border-border bg-muted/30 px-3 py-3">
                                <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                                  Standard
                                </div>
                                <div className="mt-1 text-sm font-medium text-foreground">
                                  {selectedPackDetail.standard_title ||
                                    selectedPackDetail.standard_id ||
                                    selectedPackDetail.slug}
                                </div>
                              </div>
                              <div className="rounded-md border border-border bg-muted/30 px-3 py-3">
                                <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                                  Rule Count
                                </div>
                                <div className="mt-1 text-sm font-medium text-foreground">
                                  {selectedPackDetail.rule_count}
                                </div>
                              </div>
                            </div>

                            <div className="flex flex-wrap gap-2">
                              <Badge variant={badgeVariantForStatus(selectedPackDetail.status)}>
                                {selectedPackDetail.status}
                              </Badge>
                              <Badge variant="outline">{selectedPackDetail.schema}</Badge>
                              <Badge variant="outline">
                                {selectedPackDetail.schema_version || "schema n/a"}
                              </Badge>
                              {selectedPackDetail.promoted_by && (
                                <Badge variant="outline">
                                  promoted by {selectedPackDetail.promoted_by}
                                </Badge>
                              )}
                            </div>

                            {selectedPackDetail.rendered && (
                              <div className="max-h-[24rem] overflow-y-auto rounded-md border border-border bg-muted/30 p-4">
                                <pre className="whitespace-pre-wrap text-xs leading-6 text-foreground">
                                  {selectedPackDetail.rendered}
                                </pre>
                              </div>
                            )}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                </div>
              </div>
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
