/**
 * ScrubWorkspace — the HEARTH DocScrubber surface (findings-only, Phase 1).
 *
 * Design contract (HEARTH spec v0.3 §8): banners are law, not decoration.
 * The not-legal-advice banner is always visible; findings backed by
 * provisional rules render under the PROVISIONAL banner; refusals render
 * unmissably. A refusal is a RESULT (refused=true), never a silent state.
 *
 * Visual language: the shared BoundState dark shell with a warm ember
 * accent (amber) to distinguish the HEARTH organ from Oracle's sky-blue.
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Flame,
  Loader2,
  Scale,
  ScrollText,
  ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

import { HearthDropZone } from "@/components/hearth/HearthDropZone";
import { PropertyWorkspace } from "@/components/hearth/PropertyWorkspace";
import {
  fetchHearthPacks,
  scrubDocument,
  type HearthPackInfo,
  type ScrubFinding,
  type ScrubResponse,
} from "@/lib/hearthApi";

const SEVERITY_STYLES: Record<ScrubFinding["severity"], string> = {
  info: "bg-secondary text-secondary-foreground",
  warn: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  flag: "bg-destructive/15 text-red-300 border border-destructive/40",
  refuse: "bg-destructive text-destructive-foreground",
};

const CATEGORY_LABELS: Record<ScrubFinding["category"], string> = {
  fee: "Fee",
  scope: "Scope",
  backstop: "Backstop",
  default_trap: "Default trap",
  deadline: "Deadline",
  waiver: "Waiver",
  integrity: "Integrity",
};

function formatUsd(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function ScrubWorkspace() {
  const [packs, setPacks] = useState<HearthPackInfo[]>([]);
  const [selectedPack, setSelectedPack] = useState("CO-Larimer");
  const [file, setFile] = useState<File | null>(null);
  const [targetPrice, setTargetPrice] = useState("");
  const [scrubbing, setScrubbing] = useState(false);
  const [result, setResult] = useState<ScrubResponse | null>(null);
  const [showReport, setShowReport] = useState(false);

  useEffect(() => {
    fetchHearthPacks()
      .then((response) => {
        setPacks(response.packs);
        if (response.packs.length > 0) setSelectedPack(response.packs[0].name);
      })
      .catch(() => toast.error("Could not load jurisdiction packs"));
  }, []);

  const activePack = useMemo(
    () => packs.find((pack) => pack.name === selectedPack) ?? null,
    [packs, selectedPack]
  );

  const handleScrub = useCallback(async () => {
    if (!file) return;
    const price = targetPrice.trim() === "" ? null : Number(targetPrice);
    if (price !== null && (!Number.isInteger(price) || price <= 0)) {
      toast.error("Target price must be a positive whole number of dollars");
      return;
    }
    setScrubbing(true);
    setResult(null);
    setShowReport(false);
    try {
      const response = await scrubDocument(file, selectedPack, price);
      setResult(response);
      if (response.refused) {
        toast.error("Scrub REFUSED — failing closed");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Scrub failed");
    } finally {
      setScrubbing(false);
    }
  }, [file, selectedPack, targetPrice]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-10%] top-[-8rem] h-80 w-80 rounded-full bg-amber-500/10 blur-3xl" />
        <div className="absolute right-[-8%] top-24 h-96 w-96 rounded-full bg-orange-400/8 blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-72 bg-[radial-gradient(circle_at_top,rgba(251,191,36,0.12),transparent_55%)]" />
      </div>

      <header className="border-b border-border/80 bg-background/70 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <Flame className="h-5 w-5 text-amber-400" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Hearth · DocScrubber
            </span>
            <span className="rounded-full border border-amber-400/25 bg-amber-400/10 px-3 py-0.5 text-[10px] font-medium uppercase tracking-[0.2em] text-amber-200">
              Findings-only · Phase 1
            </span>
          </div>
          <Link
            href="/"
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-4 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            <ArrowLeft className="h-4 w-4" />
            Oracle
          </Link>
        </div>
      </header>

      {/* §8: the legal banner is structural — it renders before any result. */}
      <div className="border-b border-amber-500/20 bg-amber-500/5">
        <div className="mx-auto flex max-w-6xl items-start gap-3 px-6 py-3">
          <Scale className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          <p className="text-xs leading-5 text-amber-100/90">
            <span className="font-semibold">
              Not legal advice. Not a licensed brokerage.
            </span>{" "}
            HEARTH is an analytics and document-intelligence tool used by the
            buyer on their own behalf (C.R.S. 12-10-201). Every finding
            requires review by your own licensee or attorney before any
            action.
          </p>
        </div>
      </div>

      <main className="mx-auto max-w-6xl space-y-8 px-6 py-10">
        <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6 shadow-lg shadow-slate-950/10">
          <div className="mb-5 flex items-center justify-between">
            <h1 className="text-lg font-semibold text-foreground">
              Scrub a document for unexplained defaults
            </h1>
            <span className="text-xs text-muted-foreground">
              Unparseable input refuses — never a silent pass
            </span>
          </div>

          <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
            <HearthDropZone file={file} onFileSelect={setFile} />

            <div className="space-y-4">
              <div className="space-y-1.5">
                <label
                  htmlFor="hearth-pack"
                  className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground"
                >
                  Jurisdiction pack
                </label>
                <select
                  id="hearth-pack"
                  value={selectedPack}
                  onChange={(event) => setSelectedPack(event.target.value)}
                  className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                >
                  {packs.length === 0 ? (
                    <option value={selectedPack}>{selectedPack}</option>
                  ) : (
                    packs.map((pack) => (
                      <option key={pack.name} value={pack.name}>
                        {pack.pack_id} · {pack.rules} rules
                      </option>
                    ))
                  )}
                </select>
                {activePack && activePack.provisional_rules > 0 && (
                  <p className="text-xs text-amber-300/90">
                    {activePack.provisional_rules} of {activePack.rules} rules
                    are provisional (pending licensee/attorney review)
                  </p>
                )}
              </div>

              <div className="space-y-1.5">
                <label
                  htmlFor="hearth-price"
                  className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground"
                >
                  Target price (USD, optional)
                </label>
                <input
                  id="hearth-price"
                  type="number"
                  min={1}
                  step={1000}
                  placeholder="700000"
                  value={targetPrice}
                  onChange={(event) => setTargetPrice(event.target.value)}
                  className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                />
                <p className="text-xs text-muted-foreground">
                  Enables dollar exposure math (e.g. backstop = fee% × price).
                  Without it, exposure shows as not computed — never invented.
                </p>
              </div>

              <button
                type="button"
                onClick={handleScrub}
                disabled={!file || scrubbing}
                className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-amber-500 px-5 text-sm font-semibold text-slate-950 transition-colors hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {scrubbing ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Scrubbing…
                  </>
                ) : (
                  <>
                    <ScrollText className="h-4 w-4" />
                    Scrub document
                  </>
                )}
              </button>
            </div>
          </div>
        </section>

        {result && <ScrubResult result={result} showReport={showReport} onToggleReport={() => setShowReport((value) => !value)} />}

        <PropertyWorkspace />
      </main>
    </div>
  );
}

function ScrubResult({
  result,
  showReport,
  onToggleReport,
}: {
  result: ScrubResponse;
  showReport: boolean;
  onToggleReport: () => void;
}) {
  return (
    <section className="space-y-5">
      {result.refused && (
        <div className="rounded-[1.5rem] border border-destructive/50 bg-destructive/10 p-6">
          <div className="flex items-start gap-4">
            <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0 text-red-300" />
            <div className="space-y-2">
              <h2 className="text-lg font-semibold text-red-200">
                Scrub refused — failing closed
              </h2>
              <p className="text-sm leading-6 text-red-100/90">
                {result.refusal_reason}
              </p>
              <p className="text-xs text-red-200/70">
                No clause-level analysis was performed. This document has NOT
                been reviewed — fix the input or the pack and re-run.
              </p>
            </div>
          </div>
        </div>
      )}

      {!result.refused && result.provisional_findings > 0 && (
        <div className="flex items-start gap-3 rounded-[1.25rem] border border-amber-500/30 bg-amber-500/8 px-5 py-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          <p className="text-xs leading-5 text-amber-100/90">
            <span className="font-semibold uppercase tracking-wide">
              Provisional basis:
            </span>{" "}
            {result.provisional_findings} of {result.findings.length} findings
            cite rules that have not yet had licensee/attorney review. Treat
            them as leads to verify with your licensed human, not as
            conclusions.
          </p>
        </div>
      )}

      <div className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-foreground">
              {result.findings.length}{" "}
              {result.findings.length === 1 ? "finding" : "findings"} ·{" "}
              {result.document}
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Pack {result.pack ?? "(unavailable)"} · run {result.run_date}
              {result.target_price_usd
                ? ` · target ${formatUsd(result.target_price_usd)}`
                : " · no target price"}
            </p>
          </div>
          <button
            type="button"
            onClick={onToggleReport}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
          >
            {showReport ? "Hide full report" : "View full report"}
          </button>
        </div>

        {showReport && (
          <pre className="mb-6 max-h-96 overflow-auto rounded-xl border border-border bg-black/30 p-4 text-[11px] leading-5 text-slate-200">
            {result.rendered_report}
          </pre>
        )}

        {result.findings.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No findings. This is NOT a clean bill of health: only the
            pack&apos;s known defaults were checked.
          </p>
        ) : (
          <div className="space-y-4">
            {result.findings.map((finding, index) => (
              <FindingCard key={`${finding.jurisdiction_basis}-${finding.clause_ref}-${index}`} finding={finding} index={index} />
            ))}
          </div>
        )}

        <p className="mt-6 break-all text-[11px] text-muted-foreground/80">
          Audit artifact: {result.audit_artifact}
          {result.document_sha256 && <> · doc sha256 {result.document_sha256.slice(0, 16)}…</>}
        </p>
      </div>
    </section>
  );
}

function FindingCard({
  finding,
  index,
}: {
  finding: ScrubFinding;
  index: number;
}) {
  return (
    <article className="rounded-2xl border border-border/80 bg-background/40 p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground">
          [{index + 1}]
        </span>
        <span
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${SEVERITY_STYLES[finding.severity]}`}
        >
          {finding.severity}
        </span>
        <span className="text-sm font-medium text-foreground">
          {CATEGORY_LABELS[finding.category]}
        </span>
        <span className="text-xs text-muted-foreground">
          @ {finding.clause_ref} · rule {finding.jurisdiction_basis}
        </span>
        {finding.exposure_usd !== null && (
          <span className="ml-auto rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-1 font-mono text-sm font-semibold text-amber-200">
            {formatUsd(finding.exposure_usd)} exposure
          </span>
        )}
      </div>

      <blockquote className="mb-3 border-l-2 border-border pl-3 text-sm italic leading-6 text-slate-300">
        &ldquo;{finding.found}&rdquo;
      </blockquote>

      <p className="text-sm leading-6 text-muted-foreground">
        {finding.default_analysis}
      </p>

      <p className="mt-3 text-[11px] font-medium uppercase tracking-[0.16em] text-amber-300/80">
        Requires human review
      </p>
    </article>
  );
}
