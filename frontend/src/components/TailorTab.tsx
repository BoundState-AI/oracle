/**
 * Tailor tab — work a standard one requirement at a time.
 *
 * Left: progress and the requirement index. Right: the requirement, the
 * advisor's proposal, and the decision controls.
 *
 * The advisor proposes; the user disposes. Nothing here records a disposition
 * without an explicit click AND a rationale — the backend rejects a decision
 * with a blank rationale, and this UI mirrors that rather than working around
 * it.
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ArrowLeft,
  ArrowRight,
  Download,
  Play,
  Loader2,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiGet, apiPost, apiDelete } from "@/lib/oracleApi";
import type { PackSummary } from "@/components/ReviewTab";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type Code = "CW" | "MI" | "EX" | "NA" | "OPEN";

const CODES: Array<{ code: Code; label: string; hint: string }> = [
  { code: "CW", label: "Meets", hint: "Complies as written" },
  { code: "MI", label: "Meets intent", hint: "Intent met by alternative means" },
  { code: "EX", label: "Doesn't meet", hint: "Exception — say what would close it" },
  { code: "NA", label: "N/A", hint: "Not applicable — cite the scope declaration" },
  { code: "OPEN", label: "Unknown", hint: "Not yet determined" },
];

const SUB_REASONS = [
  "evidence_absent",
  "scope_decision_not_made",
  "authority_unidentified",
  "approval_not_exercised",
  "referenced_artifact_missing",
  "referenced_standard_unavailable",
  "reference_semantics_unresolved",
  "dependency_eliminated",
] as const;

type Decision = {
  code: Code;
  rationale: string;
  open_sub_reason: string | null;
  evidence: string;
  decided_by: string;
  decided_at: string;
};

type Requirement = {
  index: number;
  id: string;
  tag: string;
  section: string;
  page: number | null;
  text: string;
  decision: Decision | null;
};

type IndexEntry = {
  index: number;
  id: string;
  tag: string;
  section: string;
  code: Code | null;
};

type SessionState = {
  session_id: string;
  standard_id: string;
  operator: string;
  total: number;
  decided: number;
  cursor: number;
  tally: Record<string, number>;
  index: IndexEntry[];
  requirement?: Requirement;
};

type Brief = {
  unit_id: string;
  requires: string;
  purpose: string;
  satisfied_by: string[];
  question: string;
  watch_for: string;
};

type Proposal = {
  unit_id: string;
  code: Code;
  band: "HIGH" | "MEDIUM" | "LOW";
  basis: string;
  reasoning: string;
  draft_rationale: string;
  open_sub_reason: string | null;
  questions: string[];
  evidence_needed: string[];
  is_question: boolean;
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function codeVariant(code: Code | null) {
  if (code === "CW") return "default";
  if (code === "OPEN" || code === "EX") return "destructive";
  if (code === "MI" || code === "NA") return "secondary";
  return "outline";
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    return typeof body?.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

/** Inline spinner. StatusSpinner is a full-page orbital + log feed — wrong
 *  scale for a button or a one-line status. */
function Spinner({ className = "" }: { className?: string }) {
  return <Loader2 className={`h-4 w-4 animate-spin ${className}`} />;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function TailorTab({ packs }: { packs: PackSummary[] }) {
  const [session, setSession] = useState<SessionState | null>(null);
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefing, setBriefing] = useState(false);
  const [answer, setAnswer] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);

  const [pack, setPack] = useState("");
  const [operator, setOperator] = useState("");
  const [scope, setScope] = useState("");

  const [rationale, setRationale] = useState("");
  const [subReason, setSubReason] = useState<string>("");
  const [starting, setStarting] = useState(false);
  const [advising, setAdvising] = useState(false);
  const [saving, setSaving] = useState(false);

  const applyState = useCallback((state: SessionState) => {
    setSession(state);
    if (state.requirement) {
      setRequirement(state.requirement);
      setRationale(state.requirement.decision?.rationale ?? "");
      setSubReason(state.requirement.decision?.open_sub_reason ?? "");
    }
    setBrief(null);
    setAnswer("");
    setProposal(null);
  }, []);

  /* -------- start ------------------------------------------------- */

  const start = useCallback(async () => {
    if (!pack) return toast.error("Choose a pack");
    if (!operator.trim()) return toast.error("Your name is recorded on every decision");
    setStarting(true);
    try {
      const res = await apiPost("/tailor/start", {
        pack,
        operator: operator.trim(),
        scope_notes: scope,
      });
      if (!res.ok) throw new Error(await readError(res, "Could not start session"));
      applyState(await res.json());
      toast.success("Session started");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not start session");
    } finally {
      setStarting(false);
    }
  }, [pack, operator, scope, applyState]);

  /* -------- navigate ---------------------------------------------- */

  const goTo = useCallback(
    async (index: number) => {
      if (!session || index < 0 || index >= session.total) return;
      try {
        const res = await apiGet(`/tailor/${session.session_id}/requirement/${index}`);
        if (!res.ok) throw new Error(await readError(res, "Could not load requirement"));
        const req: Requirement = await res.json();
        setRequirement(req);
        setRationale(req.decision?.rationale ?? "");
        setSubReason(req.decision?.open_sub_reason ?? "");
        setBrief(null);
        setAnswer("");
        setProposal(null);
        setSession({ ...session, cursor: index });
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Could not load requirement");
      }
    },
    [session],
  );

  /* -------- brief: explain it, then ask ---------------------------- */

  const fetchBrief = useCallback(
    async (req: Requirement, sid: string) => {
      setBriefing(true);
      try {
        const res = await apiPost(`/tailor/${sid}/brief`, { unit_id: req.id });
        if (!res.ok) throw new Error(await readError(res, "Could not load the brief"));
        const b: Brief = await res.json();
        // Guard against a slow response landing after the user moved on.
        setBrief((prev) => (b.unit_id === req.id ? b : prev));
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Could not load the brief");
      } finally {
        setBriefing(false);
      }
    },
    [],
  );

  // Explain each requirement as it comes up — the point of the tool is that you
  // should not have to open the standard to answer. Already-decided rows skip
  // it: you are reviewing your own decision, not being oriented again.
  useEffect(() => {
    if (!session || !requirement) return;
    if (requirement.decision) return;
    if (brief?.unit_id === requirement.id) return;
    void fetchBrief(requirement, session.session_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.session_id, requirement?.id]);

  /* -------- advise ------------------------------------------------- */

  const advise = useCallback(async () => {
    if (!session || !requirement) return;
    setAdvising(true);
    try {
      const res = await apiPost(`/tailor/${session.session_id}/advise`, {
        unit_id: requirement.id,
        user_answer: answer,
      });
      // A failed advisor call surfaces as an error, never as an empty
      // proposal — "no opinion" and "the call failed" must not look alike.
      if (!res.ok) throw new Error(await readError(res, "Advisor unavailable"));
      const pr: Proposal = await res.json();
      setProposal(pr);
      if (!pr.is_question && pr.draft_rationale && !rationale.trim()) {
        setRationale(pr.draft_rationale);
      }
      if (pr.open_sub_reason && !subReason) setSubReason(pr.open_sub_reason);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Advisor unavailable");
    } finally {
      setAdvising(false);
    }
  }, [session, requirement, rationale, subReason, answer]);

  /* -------- decide ------------------------------------------------- */

  const decide = useCallback(
    async (code: Code) => {
      if (!session || !requirement) return;
      if (!rationale.trim()) {
        toast.error("A rationale is required — the reasoning is the deliverable");
        return;
      }
      if (code === "OPEN" && !subReason) {
        toast.error("OPEN requires a sub-reason");
        return;
      }
      setSaving(true);
      try {
        const res = await apiPost(`/tailor/${session.session_id}/decide`, {
          unit_id: requirement.id,
          code,
          rationale: rationale.trim(),
          open_sub_reason: code === "OPEN" ? subReason : null,
        });
        if (!res.ok) throw new Error(await readError(res, "Could not record decision"));
        applyState(await res.json());
        toast.success(`Recorded ${code}`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Could not record decision");
      } finally {
        setSaving(false);
      }
    },
    [session, requirement, rationale, subReason, applyState],
  );

  const undo = useCallback(async () => {
    if (!session || !requirement) return;
    const res = await apiDelete(`/tailor/${session.session_id}/decide/${requirement.id}`);
    if (!res.ok) {
      toast.error(await readError(res, "Nothing to undo"));
      return;
    }
    setSession(await res.json());
    setRationale("");
    setSubReason("");
    setRequirement({ ...requirement, decision: null });
    toast.success("Decision cleared");
  }, [session, requirement]);

  const exportMatrix = useCallback(async () => {
    if (!session) return;
    const res = await apiGet(`/tailor/${session.session_id}/export`);
    if (!res.ok) {
      toast.error(await readError(res, "Export failed"));
      return;
    }
    const blob = new Blob([JSON.stringify(await res.json(), null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${session.standard_id}-tailoring.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [session]);

  /* -------- keyboard ---------------------------------------------- */

  useEffect(() => {
    if (!session) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight") goTo(session.cursor + 1);
      if (e.key === "ArrowLeft") goTo(session.cursor - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [session, goTo]);

  const progress = useMemo(
    () => (session && session.total ? Math.round((session.decided / session.total) * 100) : 0),
    [session],
  );

  /* -------- setup view -------------------------------------------- */

  if (!session) {
    return (
      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Tailor a standard</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Serves each requirement in order. You assign the disposition; the
            advisor proposes and explains, but never records.
          </p>

          <div className="space-y-2">
            <label className="text-sm font-medium">Pack</label>
            <select
              value={pack}
              onChange={(e) => setPack(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              <option value="">Choose a standard…</option>
              {packs.map((p) => (
                <option key={p.slug ?? p.name} value={p.slug ?? p.name ?? ""}>
                  {p.standard_id ?? p.name}
                  {p.rule_count ? ` — ${p.rule_count} requirements` : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Your name</label>
            <input
              value={operator}
              onChange={(e) => setOperator(e.target.value)}
              placeholder="Recorded on every decision"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">
              Declared scope{" "}
              <span className="font-normal text-muted-foreground">
                — strongly recommended
              </span>
            </label>
            <textarea
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              rows={5}
              placeholder={
                "What has your organization committed to? e.g.\n" +
                "Freestanding parts only; no repair.\n" +
                "Classes A, B, C phased.\n" +
                "Feedstock is single-pass; overspray scrapped."
              }
              className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">
              Without this, anything scope-dependent comes back OPEN rather than
              guessed — which is correct, but far less useful.
            </p>
          </div>

          <Button onClick={start} disabled={starting}>
            {starting ? <Spinner className="mr-2" /> : <Play className="mr-2 h-4 w-4" />}
            Start
          </Button>
        </CardContent>
      </Card>
    );
  }

  /* -------- working view ------------------------------------------ */

  const decided = requirement?.decision ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      {/* index */}
      <div className="space-y-3">
        <Card>
          <CardContent className="space-y-3 pt-6">
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-medium">{session.standard_id}</span>
              <span className="text-xs text-muted-foreground">
                {session.decided}/{session.total}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="flex flex-wrap gap-1">
              {Object.entries(session.tally)
                .filter(([, n]) => n > 0)
                .map(([code, n]) => (
                  <Badge key={code} variant={codeVariant(code as Code)}>
                    {code} {n}
                  </Badge>
                ))}
            </div>
            <Button variant="outline" size="sm" onClick={exportMatrix} className="w-full">
              <Download className="mr-2 h-4 w-4" />
              Export matrix
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="max-h-[60vh] overflow-y-auto p-2">
            {session.index.map((e) => (
              <button
                key={e.id}
                onClick={() => goTo(e.index)}
                className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs hover:bg-muted ${
                  e.index === session.cursor ? "bg-muted font-medium" : ""
                }`}
              >
                <span className="truncate">{e.tag || e.id}</span>
                {e.code ? (
                  <Badge variant={codeVariant(e.code)} className="ml-2 shrink-0">
                    {e.code}
                  </Badge>
                ) : (
                  <span className="ml-2 shrink-0 text-muted-foreground">·</span>
                )}
              </button>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* requirement + decision */}
      <div className="space-y-4">
        {requirement && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">
                  {requirement.tag || requirement.id}
                  <span className="ml-3 font-normal text-muted-foreground">
                    §{requirement.section}
                    {requirement.page ? ` · p.${requirement.page}` : ""}
                  </span>
                </CardTitle>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => goTo(session.cursor - 1)}
                    disabled={session.cursor === 0}
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => goTo(session.cursor + 1)}
                    disabled={session.cursor >= session.total - 1}
                  >
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {requirement.text}
              </p>

              {decided && (
                <div className="rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
                  <div className="mb-1 flex items-center gap-2">
                    <Badge variant={codeVariant(decided.code)}>{decided.code}</Badge>
                    {decided.open_sub_reason && (
                      <span className="text-xs text-muted-foreground">
                        {decided.open_sub_reason}
                      </span>
                    )}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {decided.decided_by}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap text-muted-foreground">
                    {decided.rationale}
                  </p>
                </div>
              )}

              {/* 1 — what it is and what it's for */}
              {briefing && !brief && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Spinner />
                  Reading the requirement…
                </div>
              )}

              {brief && (
                <div className="space-y-3 rounded-md border bg-muted/30 p-4 text-sm">
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      What it requires
                    </p>
                    <p>{brief.requires}</p>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Why it&apos;s there
                    </p>
                    <p>{brief.purpose}</p>
                  </div>
                  {brief.satisfied_by.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        What would satisfy it
                      </p>
                      <ul className="list-disc space-y-0.5 pl-5">
                        {brief.satisfied_by.map((x) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {brief.watch_for && (
                    <p className="rounded border-l-2 border-amber-500/60 bg-amber-500/5 py-1 pl-3 text-xs">
                      <span className="font-medium">Watch for: </span>
                      {brief.watch_for}
                    </p>
                  )}
                </div>
              )}

              {/* 2 — the question, and your answer */}
              {brief && !decided && (
                <div className="space-y-2">
                  <label className="block text-sm font-medium">
                    {brief.question || "Do you meet this?"}
                  </label>
                  <textarea
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    rows={3}
                    placeholder="In your own words — e.g. 'we don't HIP, we use a qualified anneal that closes porosity'"
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={advise}
                    disabled={advising || !answer.trim()}
                  >
                    {advising ? <Spinner className="mr-2" /> : <Sparkles className="mr-2 h-4 w-4" />}
                    Help me disposition this
                  </Button>
                  {!answer.trim() && (
                    <p className="text-xs text-muted-foreground">
                      Answer first — the advisor maps what you say onto a code, and
                      without an answer it can only guess.
                    </p>
                  )}
                </div>
              )}

              {decided && (
                <Button variant="outline" size="sm" onClick={advise} disabled={advising}>
                  {advising ? <Spinner className="mr-2" /> : <Sparkles className="mr-2 h-4 w-4" />}
                  Re-check this decision
                </Button>
              )}

              {proposal && (
                <div className="rounded-md border bg-muted/40 p-3 text-sm">
                  <div className="mb-2 flex items-center gap-2">
                    {proposal.is_question ? (
                      <Badge variant="outline">Needs your decision</Badge>
                    ) : (
                      <>
                        <Badge variant={codeVariant(proposal.code)}>
                          proposes {proposal.code}
                        </Badge>
                        <Badge variant="outline">{proposal.band}</Badge>
                      </>
                    )}
                  </div>
                  {proposal.basis && (
                    <p className="mb-2 text-xs text-muted-foreground">{proposal.basis}</p>
                  )}
                  <p className="whitespace-pre-wrap">{proposal.reasoning}</p>

                  {proposal.questions.length > 0 && (
                    <div className="mt-3">
                      <p className="text-xs font-medium">Needs an answer from you</p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                        {proposal.questions.map((q) => (
                          <li key={q}>{q}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {proposal.evidence_needed.length > 0 && (
                    <div className="mt-3">
                      <p className="text-xs font-medium">Would settle it</p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                        {proposal.evidence_needed.map((e) => (
                          <li key={e}>{e}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              <div className="space-y-2">
                <label className="text-sm font-medium">
                  Rationale <span className="text-destructive">*</span>
                </label>
                <textarea
                  value={rationale}
                  onChange={(e) => setRationale(e.target.value)}
                  rows={4}
                  placeholder="Why this disposition. For EX, say what would close it."
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">
                  Sub-reason (required for Unknown)
                </label>
                <select
                  value={subReason}
                  onChange={(e) => setSubReason(e.target.value)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="">—</option>
                  {SUB_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex flex-wrap gap-2 border-t pt-3">
                {CODES.map(({ code, label, hint }) => (
                  <Button
                    key={code}
                    size="sm"
                    variant={decided?.code === code ? "default" : "outline"}
                    onClick={() => decide(code)}
                    disabled={saving}
                    title={hint}
                  >
                    {label}
                  </Button>
                ))}
                {decided && (
                  <Button size="sm" variant="ghost" onClick={undo} disabled={saving}>
                    <RotateCcw className="mr-2 h-4 w-4" />
                    Undo
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
