/**
 * Pack Library tab UI for the Oracle workspace.
 *
 * Left column: import an existing JSON pack, or generate a new one from a PDF.
 * Right column: browse available packs, view detail, promote or delete.
 */

"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Eye,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
  WandSparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusSpinner } from "@/components/StatusSpinner";
import { apiGet, apiPost, apiDelete } from "@/lib/oracleApi";
import { connectSSE, readLogMessages, startStatusPolling } from "@/lib/oracleSSE";
import type { PackSummary } from "@/components/ReviewTab";

/* ------------------------------------------------------------------ */
/*  Internal types                                                     */
/* ------------------------------------------------------------------ */

export type PackDetail = PackSummary & {
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

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function badgeVariantForStatus(status: string | undefined) {
  if (status === "promoted") return "default";
  if (status === "draft") return "secondary";
  if (status === "error") return "destructive";
  return "outline";
}

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

export interface PackLibraryTabProps {
  availablePacks: PackSummary[];
  packsLoading: boolean;
  onRefreshPacks: () => Promise<void>;
  /** Called when a pack is deleted so the orchestrator can clean up selectedPacks. */
  onPackDeleted?: (slug: string) => void;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function PackLibraryTab({
  availablePacks,
  packsLoading,
  onRefreshPacks,
  onPackDeleted,
}: PackLibraryTabProps) {
  const [selectedPackDetail, setSelectedPackDetail] = useState<PackDetail | null>(null);
  const [packDetailLoading, setPackDetailLoading] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [generateFile, setGenerateFile] = useState<File | null>(null);
  const [generateName, setGenerateName] = useState("");
  const [generateForceType, setGenerateForceType] = useState("");
  const [packJob, setPackJob] = useState<PackJob | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const generateInputRef = useRef<HTMLInputElement | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  /* ---- internal helpers ---- */

  const clearLiveJob = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }
  }, []);

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

  const applyPackResult = useCallback(
    async (result: Record<string, unknown>) => {
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
        await onRefreshPacks();
        return;
      }

      toast.success("Pack generation completed.");
      await onRefreshPacks();
    },
    [clearLiveJob, onRefreshPacks],
  );

  /* ---- pack actions ---- */

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
        await onRefreshPacks();
        await loadPackDetail(slug);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to promote pack";
        toast.error(message);
      }
    },
    [loadPackDetail, onRefreshPacks],
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
        onPackDeleted?.(slug);
        await onRefreshPacks();
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to remove pack";
        toast.error(message);
      }
    },
    [onPackDeleted, onRefreshPacks],
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
      await onRefreshPacks();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to import pack";
      toast.error(message);
    }
  }, [importFile, onRefreshPacks]);

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
              (progressData) => {
                const logMessages = readLogMessages(progressData);
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

  /* ---- render ---- */

  return (
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
                  onClick={() => void onRefreshPacks()}
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
  );
}
