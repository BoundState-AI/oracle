"use client";

/**
 * PipelineTab — web UI for the Oracle Build Pipeline.
 *
 * - Paste a polished spec
 * - Pick target repo (absolute path on the *server* machine)
 * - Prompted output dir with "Use this directory" that defaults to:
 *     <repo>/oracle_builds/<YYYYMMDD_HHMMSS>
 *   This satisfies: "be sure that we are prompted to where to save it locally, ie, use this directory"
 * - Options for fix rounds + skip/allow-dirty
 * - Live SSE logs while running (Ben → Atlas → Beth stages)
 * - On completion: shows gate verdict excerpt + download links for PIPELINE_REPORT.md + logs
 *
 * The backend (`/oracle/pipeline/start`) writes to the chosen local dir on the server host.
 * No commits/pushes ever performed.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiPost, apiGet, normalizeDownloadUrl } from "@/lib/oracleApi";
import { connectSSE, startStatusPolling, readLogMessages } from "@/lib/oracleSSE";

type PipelinePhase =
  | { step: "idle" }
  | { step: "running"; logMessages: string[] }
  | {
      step: "done";
      sessionId: string;
      repo: string;
      outputDir: string;
      report: string | null;
      reportUrl: string | null;
      buildLogUrl: string | null;
      artifacts: string[];
      gateVerdict?: string | null;
    }
  | { step: "error"; message: string };

function formatTsForDir(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    d.getFullYear().toString() +
    pad(d.getMonth() + 1) +
    pad(d.getDate()) +
    "_" +
    pad(d.getHours()) +
    pad(d.getMinutes()) +
    pad(d.getSeconds())
  );
}

function defaultOutputForRepo(repo: string): string {
  if (!repo.trim()) return "";
  // Normalize to forward slashes for display; server Path() will handle OS
  const clean = repo.replace(/\\/g, "/").replace(/\/$/, "");
  return `${clean}/oracle_builds/${formatTsForDir()}`;
}

export interface PipelineTabProps {
  // no shared state needed yet
}

export function PipelineTab(_props: PipelineTabProps) {
  const [spec, setSpec] = useState("");
  const [repo, setRepo] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [fixRounds, setFixRounds] = useState(1);
  const [skipBuild, setSkipBuild] = useState(false);
  const [allowDirty, setAllowDirty] = useState(false);

  const [phase, setPhase] = useState<PipelinePhase>({ step: "idle" });

  const cleanupRef = useRef<(() => void) | null>(null);

  const clearLive = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }
  }, []);

  const useThisDirectory = useCallback(() => {
    if (!repo.trim()) {
      toast.error("Enter the target repo path first (e.g. D:\\BoundState\\boundstate_oracle)");
      return;
    }
    const suggested = defaultOutputForRepo(repo);
    setOutputDir(suggested);
    toast.success("Using this directory for artifacts", { description: suggested });
  }, [repo]);

  const reset = useCallback(() => {
    clearLive();
    setPhase({ step: "idle" });
  }, [clearLive]);

  // Close the SSE/polling connection when the tab unmounts — without this,
  // switching tabs mid-run leaks an EventSource per visit.
  useEffect(() => clearLive, [clearLive]);

  const startPipeline = useCallback(async () => {
    const trimmedSpec = spec.trim();
    const trimmedRepo = repo.trim();

    if (!trimmedSpec || trimmedSpec.length < 30) {
      toast.error("Paste a real polished spec first (at least a few paragraphs).");
      return;
    }
    if (!trimmedRepo) {
      toast.error("Repo path is required (absolute path on the server machine).");
      return;
    }

    // If user left output blank, we let server default — but UI strongly encourages prompting
    let effectiveOut = outputDir.trim();
    if (!effectiveOut) {
      effectiveOut = defaultOutputForRepo(trimmedRepo);
      setOutputDir(effectiveOut);
    }

    setPhase({ step: "running", logMessages: ["Contacting server to start pipeline..."] });

    try {
      const res = await apiPost("/pipeline/start", {
        spec: trimmedSpec,
        repo: trimmedRepo,
        output_dir: effectiveOut || null,
        fix_rounds: fixRounds,
        skip_build: skipBuild,
        allow_dirty: allowDirty,
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`Start failed (${res.status}) ${text}`);
      }

      const data = (await res.json()) as { session_id: string; output_dir?: string; repo?: string };
      const sid = data.session_id;

      const onLog = (msg: string) => {
        setPhase((prev) => {
          if (prev.step !== "running") return prev;
          return { ...prev, logMessages: [...prev.logMessages, msg].slice(-30) };
        });
      };

      const onDone = (result: Record<string, unknown>) => {
        clearLive();
        if (result.status === "error") {
          setPhase({ step: "error", message: String(result.error ?? "Pipeline failed") });
          return;
        }
        const outDir = (result.output_dir as string) ?? effectiveOut;
        const rpt = (result.pipeline_report as string) ?? null;
        const rUrl = normalizeDownloadUrl((result.pipeline_report_url as string) ?? null);
        const bUrl = normalizeDownloadUrl((result.build_log_url as string) ?? null);
        const arts = Array.isArray(result.pipeline_artifacts)
          ? (result.pipeline_artifacts as string[])
          : [];
        const gv = (result.gate_verdict as string) ?? (result.status === "approved" ? "APPROVED" : null);

        setPhase({
          step: "done",
          sessionId: sid,
          repo: (result.repo as string) ?? trimmedRepo,
          outputDir: outDir,
          report: rpt,
          reportUrl: rUrl,
          buildLogUrl: bUrl,
          artifacts: arts,
          gateVerdict: gv,
        });
        toast.success("Pipeline complete", { description: "See PIPELINE_REPORT.md for the final gate." });
      };

      const onErr = (err: string, recoverable: boolean) => {
        if (recoverable) {
          setPhase((prev) => {
            if (prev.step !== "running") return prev;
            return { ...prev, logMessages: [...prev.logMessages, `Live stream dropped — polling: ${err}`].slice(-30) };
          });
          cleanupRef.current = startStatusPolling(sid, onDone, (e) => {
            setPhase((p) => (p.step === "running" ? { ...p, logMessages: [...p.logMessages, `Poll: ${e}`] } : p));
          }, (prog) => {
            const logs = readLogMessages(prog);
            if (logs.length) {
              setPhase((p) => (p.step === "running" ? { ...p, logMessages: logs } : p));
            }
          });
          return;
        }
        clearLive();
        setPhase({ step: "error", message: err });
      };

      const cleanup = connectSSE(sid, onLog, onDone, onErr);
      cleanupRef.current = cleanup;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to start pipeline";
      toast.error(msg);
      setPhase({ step: "error", message: msg });
    }
  }, [spec, repo, outputDir, fixRounds, skipBuild, allowDirty, clearLive]);

  const loadReport = useCallback(async () => {
    if (phase.step !== "done" || !phase.sessionId) return;
    try {
      const res = await apiGet(`/session/${phase.sessionId}`);
      if (!res.ok) throw new Error("status poll failed");
      const data = (await res.json()) as Record<string, unknown>;
      const freshReport = (data.pipeline_report as string) ?? phase.report;
      const freshVerdict = (data.gate_verdict as string) ?? phase.gateVerdict;
      setPhase((p) =>
        p.step === "done"
          ? { ...p, report: freshReport, gateVerdict: freshVerdict }
          : p
      );
    } catch {
      /* non-fatal */
    }
  }, [phase]);

  /* render */
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Oracle Build Pipeline</h2>
        <p className="text-sm text-muted-foreground">
          Paste a polished spec → pick a repo → choose where to save artifacts locally → watch Ben/Atlas/Beth.
          Never commits or pushes.
        </p>
      </div>

      {phase.step === "idle" && (
        <Card>
          <CardHeader>
            <CardTitle>Start a build</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium">Polished spec (paste here)</label>
              <textarea
                value={spec}
                onChange={(e) => setSpec(e.target.value)}
                placeholder="Paste the FINAL_SPEC.md or polished output from oracle polish step..."
                className="h-48 w-full rounded-md border bg-background p-3 font-mono text-sm"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm font-medium">Target repo (absolute path on server)</label>
                <input
                  value={repo}
                  onChange={(e) => {
                    const v = e.target.value;
                    setRepo(v);
                    // If output dir is still the previous default, auto-refresh suggestion
                    if (outputDir.includes("/oracle_builds/") || outputDir.includes("\\oracle_builds\\")) {
                      setOutputDir(defaultOutputForRepo(v));
                    }
                  }}
                  placeholder="D:\\BoundState\\boundstate_mira"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
                <p className="mt-1 text-xs text-muted-foreground">Must be a git checkout visible to the server process.</p>
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium">Save artifacts to (local dir)</label>
                <div className="flex gap-2">
                  <input
                    value={outputDir}
                    onChange={(e) => setOutputDir(e.target.value)}
                    placeholder="Leave blank or click button for default"
                    className="flex-1 rounded-md border bg-background px-3 py-2 text-sm"
                  />
                  <Button type="button" variant="secondary" onClick={useThisDirectory}>
                    Use this directory
                  </Button>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Strongly recommended: click <span className="font-medium">“Use this directory”</span> after entering repo.
                  Defaults to <code>&lt;repo&gt;/oracle_builds/&lt;timestamp&gt;</code>
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-end gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium">Fix rounds (after non-SHIP review)</label>
                <select
                  value={fixRounds}
                  onChange={(e) => setFixRounds(parseInt(e.target.value, 10))}
                  className="rounded-md border bg-background px-3 py-2 text-sm"
                >
                  {[0, 1, 2, 3].map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>

              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={skipBuild} onChange={(e) => setSkipBuild(e.target.checked)} />
                Skip build (review + gate existing changes)
              </label>

              <label className="flex items-center gap-2 text-sm text-amber-600">
                <input type="checkbox" checked={allowDirty} onChange={(e) => setAllowDirty(e.target.checked)} />
                Allow dirty tree (dangerous — mixes diffs)
              </label>
            </div>

            <div className="pt-2">
              <Button onClick={startPipeline} size="lg" className="w-full md:w-auto">
                Start Pipeline
              </Button>
              <p className="mt-2 text-xs text-muted-foreground">
                The server will stream live stage updates (BUILD → REVIEW → FIX → GATE). Final verdict lives in PIPELINE_REPORT.md inside the directory you chose.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {phase.step === "running" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">Running pipeline…</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-3 text-xs uppercase tracking-widest text-muted-foreground">
              Live output from stages (Ben, Atlas, Beth)
            </div>
            <pre className="max-h-[420px] overflow-auto rounded bg-black/90 p-4 font-mono text-xs text-emerald-300">
{phase.logMessages.length ? phase.logMessages.join("\n") : "Waiting for first log..."}
            </pre>
            <div className="mt-3 flex items-center gap-3">
              {/* Honest label: this only stops watching — the server-side run
                  (and its API spend) continues to completion. */}
              <Button variant="ghost" onClick={reset}>Hide output / Reset view</Button>
              <span className="text-xs text-muted-foreground">
                The pipeline keeps running on the server; artifacts still land in the output directory.
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {phase.step === "done" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                Pipeline finished — {phase.sessionId}
                {phase.gateVerdict && (
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-semibold tracking-wider ${
                      phase.gateVerdict === "APPROVED"
                        ? "bg-emerald-600 text-white"
                        : phase.gateVerdict === "REJECTED"
                        ? "bg-red-600 text-white"
                        : "bg-amber-500 text-black"
                    }`}
                  >
                    {phase.gateVerdict}
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div><span className="font-medium">Repo:</span> <code>{phase.repo}</code></div>
              <div><span className="font-medium">Artifacts saved to:</span> <code className="break-all">{phase.outputDir}</code></div>

              <div className="flex flex-wrap gap-2 pt-2">
                {phase.reportUrl && (
                  <a href={phase.reportUrl} target="_blank" className="underline">Download PIPELINE_REPORT.md</a>
                )}
                {phase.buildLogUrl && (
                  <a href={phase.buildLogUrl} target="_blank" className="underline">Download build_log.md</a>
                )}
                {phase.artifacts.length > 0 && (
                  <span className="text-muted-foreground">+ {phase.artifacts.length} other logs/reviews in the dir</span>
                )}
              </div>

              <div className="pt-2">
                <Button variant="secondary" onClick={loadReport}>Refresh report from server</Button>{" "}
                <Button variant="ghost" onClick={reset}>Start another</Button>
              </div>
            </CardContent>
          </Card>

          {phase.report && (
            <Card>
              <CardHeader>
                <CardTitle>Beth’s Final Gate (excerpt)</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-4 text-sm font-mono">
{phase.report}
                </pre>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {phase.step === "error" && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Pipeline error</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap text-sm">{phase.message}</pre>
            <div className="pt-3">
              <Button onClick={reset}>Try again</Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
