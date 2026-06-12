/**
 * PropertyWorkspace — the §14 P3-C property-intelligence surface.
 *
 * Everything the CLI can do, app-reachable: ingest county exports, compute
 * well proximity, stamp the verified EPA radon zone, record buyer-supplied
 * evidence, and run landmine scans whose alerts cite their evidence rows.
 * Refusals render as results, never silence — same contract as the API.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Database,
  Droplets,
  Flame,
  Landmark,
  Loader2,
  MapPin,
  Radar,
  ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

import {
  addEvidence,
  computeWells,
  fetchProperties,
  fetchPullPlan,
  ingestExport,
  scanProperty,
  stampRadon,
  type HearthProperty,
  type PropertyAlert,
  type PullSource,
  type ScanResponse,
} from "@/lib/hearthApi";

const STATUS_STYLES: Record<PropertyAlert["status"], string> = {
  alert: "bg-destructive/15 text-red-300 border border-destructive/40",
  clear: "bg-success/10 text-success border border-success/30",
  insufficient_evidence:
    "bg-amber-500/10 text-amber-300 border border-amber-500/30",
};

export function PropertyWorkspace() {
  const [properties, setProperties] = useState<HearthProperty[]>([]);
  const [plan, setPlan] = useState<PullSource[]>([]);
  const [scan, setScan] = useState<ScanResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const ingestInput = useRef<HTMLInputElement>(null);
  const wellsInput = useRef<HTMLInputElement>(null);
  const [adapter, setAdapter] = useState("larimer-assessor");
  const [evidenceForm, setEvidenceForm] = useState({
    property: "",
    field: "fema_flood_zone",
    value: "",
    note: "msc.fema.gov lookup",
  });

  const refresh = useCallback(() => {
    fetchProperties()
      .then((body) => setProperties(body.properties))
      .catch(() => toast.error("Could not load properties"));
  }, []);

  useEffect(() => {
    refresh();
    fetchPullPlan()
      .then((body) => setPlan(body.sources))
      .catch(() => toast.error("Could not load the pull plan"));
  }, [refresh]);

  const run = useCallback(
    async (label: string, action: () => Promise<{ refused: boolean; reason?: string }>) => {
      setBusy(label);
      try {
        const result = await action();
        if (result.refused) {
          toast.error(`${label} refused: ${result.reason}`);
        } else {
          toast.success(`${label} done`);
          refresh();
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : `${label} failed`);
      } finally {
        setBusy(null);
      }
    },
    [refresh]
  );

  const handleScan = useCallback(
    async (uid: string) => {
      setBusy(`scan:${uid}`);
      setScan(null);
      try {
        const result = await scanProperty(uid);
        setScan(result);
        if (result.refused) toast.error("Scan refused — failing closed");
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Scan failed");
      } finally {
        setBusy(null);
      }
    },
    []
  );

  return (
    <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6 shadow-lg shadow-slate-950/10">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Landmark className="h-5 w-5 text-amber-400" />
          Property intelligence
        </h2>
        <span className="text-xs text-muted-foreground">
          mills · radon · wells · flood · wildfire — every row cited
        </span>
      </div>

      {/* Data actions */}
      <div className="mb-6 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-border/80 bg-background/40 p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            <Database className="h-3.5 w-3.5" /> Ingest county export
          </p>
          <select
            value={adapter}
            onChange={(e) => setAdapter(e.target.value)}
            className="mb-2 h-8 w-full rounded-lg border border-border bg-background px-2 text-xs text-foreground"
          >
            <option value="larimer-assessor">larimer-assessor</option>
            <option value="larimer-permits">larimer-permits</option>
          </select>
          <input
            ref={ingestInput}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) run("Ingest", () => ingestExport(f, adapter));
              e.target.value = "";
            }}
          />
          <ActionButton
            label="Upload CSV"
            busy={busy === "Ingest"}
            onClick={() => ingestInput.current?.click()}
          />
        </div>

        <div className="rounded-xl border border-border/80 bg-background/40 p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            <Radar className="h-3.5 w-3.5" /> Well proximity (ECMC)
          </p>
          <p className="mb-2 text-xs text-muted-foreground">
            2,000 ft radius · plugged wells excluded
          </p>
          <input
            ref={wellsInput}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) run("Wells", () => computeWells(f));
              e.target.value = "";
            }}
          />
          <ActionButton
            label="Upload wells CSV"
            busy={busy === "Wells"}
            onClick={() => wellsInput.current?.click()}
          />
        </div>

        <div className="rounded-xl border border-border/80 bg-background/40 p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            <Droplets className="h-3.5 w-3.5" /> EPA radon zone
          </p>
          <p className="mb-2 text-xs text-muted-foreground">
            Larimer = Zone 1 (verified EPA data)
          </p>
          <ActionButton
            label="Stamp all properties"
            busy={busy === "Radon"}
            onClick={() => run("Radon", () => stampRadon("Larimer"))}
          />
        </div>

        <div className="rounded-xl border border-border/80 bg-background/40 p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            <MapPin className="h-3.5 w-3.5" /> Buyer-supplied evidence
          </p>
          <input
            placeholder="address fragment"
            value={evidenceForm.property}
            onChange={(e) => setEvidenceForm({ ...evidenceForm, property: e.target.value })}
            className="mb-1.5 h-8 w-full rounded-lg border border-border bg-background px-2 text-xs"
          />
          <div className="mb-1.5 flex gap-1.5">
            <select
              value={evidenceForm.field}
              onChange={(e) => setEvidenceForm({ ...evidenceForm, field: e.target.value })}
              className="h-8 w-1/2 rounded-lg border border-border bg-background px-1 text-xs"
            >
              <option value="fema_flood_zone">flood zone</option>
              <option value="csfs_wildfire_risk_rating">wildfire rating</option>
              <option value="wells_within_radius">wells (manual)</option>
            </select>
            <input
              placeholder="value"
              value={evidenceForm.value}
              onChange={(e) => setEvidenceForm({ ...evidenceForm, value: e.target.value })}
              className="h-8 w-1/2 rounded-lg border border-border bg-background px-2 text-xs"
            />
          </div>
          <ActionButton
            label="Record (tier 0.80)"
            busy={busy === "Evidence"}
            onClick={() =>
              run("Evidence", () =>
                addEvidence(
                  evidenceForm.property,
                  evidenceForm.field,
                  evidenceForm.value,
                  evidenceForm.note
                )
              )
            }
          />
        </div>
      </div>

      {/* Properties */}
      {properties.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No properties ingested yet — upload an assessor export above, or run
          the pull plan below on your machine.
        </p>
      ) : (
        <div className="space-y-2">
          {properties.map((property) => (
            <div
              key={property.property_uid}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-border/80 bg-background/40 px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {property.address}
                </p>
                <p className="text-xs text-muted-foreground">
                  {property.parcels.join(", ")} · confidence{" "}
                  {property.match_confidence.toFixed(2)} ·{" "}
                  {property.evidence_fields.length} evidence fields
                </p>
              </div>
              {property.joins_blocked && (
                <span className="rounded-full border border-destructive/40 bg-destructive/10 px-2.5 py-0.5 text-[11px] font-semibold text-red-300">
                  joins blocked — resolve identity
                </span>
              )}
              <button
                type="button"
                disabled={busy === `scan:${property.property_uid}` || property.joins_blocked}
                onClick={() => handleScan(property.property_uid)}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-amber-500 px-3 text-xs font-semibold text-slate-950 transition-colors hover:bg-amber-400 disabled:opacity-40"
              >
                {busy === `scan:${property.property_uid}` ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Flame className="h-3.5 w-3.5" />
                )}
                Scan landmines
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Scan result */}
      {scan && (
        <div className="mt-5 space-y-3">
          {scan.refused ? (
            <div className="flex items-start gap-3 rounded-xl border border-destructive/50 bg-destructive/10 p-4">
              <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-red-300" />
              <div>
                <p className="text-sm font-semibold text-red-200">
                  Scan refused — failing closed
                </p>
                <p className="text-xs text-red-100/90">{scan.refusal_reason}</p>
              </div>
            </div>
          ) : (
            scan.alerts.map((alert) => (
              <div
                key={alert.rule_id}
                className="rounded-xl border border-border/80 bg-background/40 p-4"
              >
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${STATUS_STYLES[alert.status]}`}
                  >
                    {alert.status === "alert" ? alert.severity : alert.status.replaceAll("_", " ")}
                  </span>
                  <span className="text-sm font-medium text-foreground">
                    {alert.summary}
                  </span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {alert.rule_id}
                  </span>
                </div>
                <p className="text-xs leading-5 text-muted-foreground">
                  {alert.analysis}
                </p>
                {alert.evidence.map((row) => (
                  <p
                    key={`${row.field}-${row.retrieved}`}
                    className="mt-2 font-mono text-[11px] text-amber-200/90"
                  >
                    {row.field} = {String(row.value)} — {row.source} (
                    {row.retrieved}, conf {row.confidence.toFixed(2)})
                  </p>
                ))}
              </div>
            ))
          )}
        </div>
      )}

      {/* Pull plan runbook */}
      <details className="mt-6 rounded-xl border border-border/80 bg-background/30 p-4">
        <summary className="cursor-pointer text-sm font-medium text-foreground">
          Data pull plan — where every stream comes from
        </summary>
        <div className="mt-3 space-y-3">
          {plan.map((source) => (
            <div key={source.source_id} className="text-xs leading-5 text-muted-foreground">
              <p className="font-semibold text-foreground">
                [{source.source_id}] {source.description}
              </p>
              {source.urls.map((url) => (
                <p key={url}>url: {url}</p>
              ))}
              {source.manual_steps.map((step) => (
                <p key={step}>manual: {step}</p>
              ))}
              <p className="text-amber-200/80">then: {source.then}</p>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}

function ActionButton({
  label,
  busy,
  onClick,
}: {
  label: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onClick}
      className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 text-xs font-medium text-amber-200 transition-colors hover:bg-amber-400/20 disabled:opacity-40"
    >
      {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {label}
    </button>
  );
}
