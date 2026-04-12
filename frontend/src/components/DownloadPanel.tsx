/**
 * DownloadPanel — download links for all generated documents and review artifacts.
 * Renders polished docx/pptx, findings report, metrics JSON, compliance context, and pack snapshot.
 */

"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Download, FileText, Presentation, RotateCcw } from "lucide-react";

interface DownloadPanelProps {
  originalName: string;
  docxUrl: string | null;
  pptxUrl: string | null;
  reportUrl?: string | null;
  metricsUrl?: string | null;
  complianceContextUrl?: string | null;
  packSnapshotUrl?: string | null;
  onStartOver: () => void;
}

function polishedName(original: string, ext: string): string {
  const base = original.replace(/\.[^.]+$/, "");
  return `${base}_polished${ext}`;
}

export function DownloadPanel({
  originalName,
  docxUrl,
  pptxUrl,
  reportUrl,
  metricsUrl,
  complianceContextUrl,
  packSnapshotUrl,
  onStartOver,
}: DownloadPanelProps) {
  const extras = [
    reportUrl
      ? { label: `${polishedName(originalName, "")}_findings_report.md`, href: reportUrl }
      : null,
    metricsUrl
      ? { label: `${polishedName(originalName, "")}_metrics.json`, href: metricsUrl }
      : null,
    complianceContextUrl
      ? { label: `${polishedName(originalName, "")}_compliance_context.txt`, href: complianceContextUrl }
      : null,
    packSnapshotUrl
      ? { label: `${polishedName(originalName, "")}_pack_manifest_snapshot.json`, href: packSnapshotUrl }
      : null,
  ].filter(Boolean) as { label: string; href: string }[];

  return (
    <Card className="border-border">
      <CardHeader>
        <CardTitle className="text-lg font-semibold tracking-tight">
          Your documents are ready
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {docxUrl && (
          <div className="flex items-center justify-between rounded-md border border-border px-4 py-3">
            <div className="flex items-center gap-3">
              <FileText className="h-5 w-5 text-ring" />
              <span className="text-sm font-medium text-foreground">
                {polishedName(originalName, ".docx")}
              </span>
            </div>
            <a
              href={docxUrl}
              download
              className="inline-flex h-7 items-center gap-1 rounded-[min(var(--radius-md),12px)] border border-border bg-background px-2.5 text-[0.8rem] font-medium hover:bg-muted transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              Download
            </a>
          </div>
        )}

        {pptxUrl && (
          <div className="flex items-center justify-between rounded-md border border-border px-4 py-3">
            <div className="flex items-center gap-3">
              <Presentation className="h-5 w-5 text-ring" />
              <span className="text-sm font-medium text-foreground">
                {polishedName(originalName, ".pptx")}
              </span>
            </div>
            <a
              href={pptxUrl}
              download
              className="inline-flex h-7 items-center gap-1 rounded-[min(var(--radius-md),12px)] border border-border bg-background px-2.5 text-[0.8rem] font-medium hover:bg-muted transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              Download
            </a>
          </div>
        )}

        {extras.map((extra) => (
          <div
            key={extra.label}
            className="flex items-center justify-between rounded-md border border-border px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <FileText className="h-5 w-5 text-ring" />
              <span className="text-sm font-medium text-foreground">
                {extra.label}
              </span>
            </div>
            <a
              href={extra.href}
              download
              className="inline-flex h-7 items-center gap-1 rounded-[min(var(--radius-md),12px)] border border-border bg-background px-2.5 text-[0.8rem] font-medium hover:bg-muted transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              Download
            </a>
          </div>
        ))}
      </CardContent>
      <CardFooter>
        <Button variant="outline" onClick={onStartOver}>
          <RotateCcw className="h-4 w-4" data-icon="inline-start" />
          Process Another Document
        </Button>
      </CardFooter>
    </Card>
  );
}
