/**
 * Review tab UI for the Oracle workspace.
 *
 * Renders three mutually-exclusive phases:
 *   1. **upload** — file picker, mode/rounds selectors, compliance-pack checklist, analyze button.
 *   2. **analyzing** — live log spinner while the Oracle processes.
 *   3. **result** — critique panel + download panel.
 */

"use client";

import {
  RefreshCw,
  Zap,
} from "lucide-react";
import type { ProcessingMode } from "@/components/ModeSelector";
import { DropZone } from "@/components/DropZone";
import { ModeSelector } from "@/components/ModeSelector";
import { RoundsSelector } from "@/components/RoundsSelector";
import { StatusSpinner } from "@/components/StatusSpinner";
import { CritiquePanel } from "@/components/CritiquePanel";
import { DownloadPanel } from "@/components/DownloadPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/* ------------------------------------------------------------------ */
/*  Shared types                                                       */
/* ------------------------------------------------------------------ */

export type Phase =
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

export type PackSummary = {
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

export interface ReviewTabProps {
  /* Upload state */
  file: File | null;
  onFileSelect: (file: File | null) => void;
  mode: ProcessingMode;
  onModeChange: (mode: ProcessingMode) => void;
  maxRounds: number;
  onMaxRoundsChange: (rounds: number) => void;

  /* Phase state */
  phase: Phase;

  /* Compliance packs */
  availablePacks: PackSummary[];
  packsLoading: boolean;
  selectedPacks: string[];
  packParts: Record<string, string>;
  onTogglePack: (slug: string) => void;
  onPackPartsChange: (slug: string, value: string) => void;
  onRefreshPacks: () => void;

  /* Actions */
  onAnalyze: () => void;
  onStartOver: () => void;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function ReviewTab({
  file,
  onFileSelect,
  mode,
  onModeChange,
  maxRounds,
  onMaxRoundsChange,
  phase,
  availablePacks,
  packsLoading,
  selectedPacks,
  packParts,
  onTogglePack,
  onPackPartsChange,
  onRefreshPacks,
  onAnalyze,
  onStartOver,
}: ReviewTabProps) {
  return (
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
                <DropZone file={file} onFileSelect={onFileSelect} />
                <ModeSelector value={mode} onChange={onModeChange} />
                <RoundsSelector
                  value={maxRounds}
                  onChange={onMaxRoundsChange}
                />

                <Button
                  className="w-full"
                  size="lg"
                  disabled={!file}
                  onClick={onAnalyze}
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
                    onClick={onRefreshPacks}
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
                            onChange={() => onTogglePack(pack.slug)}
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
                                    onPackPartsChange(pack.slug, event.target.value)
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
            onStartOver={onStartOver}
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
            onStartOver={onStartOver}
          />
        </div>
      )}
    </div>
  );
}
