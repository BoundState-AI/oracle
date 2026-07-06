/**
 * DudeWorkspace — the DUDE case list + new-case surface.
 *
 * Visual language: the shared BoundState dark shell with a violet accent to
 * distinguish the DUDE organ from Oracle's sky-blue and HEARTH's ember.
 * All case data comes from the backend via the /api/dude proxy; this
 * surface owns navigation chrome only.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Compass, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";

import { createCase, fetchCases, type DudeCase } from "@/lib/dudeApi";

export function DudeWorkspace() {
  const router = useRouter();
  const [cases, setCases] = useState<DudeCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetchCases()
      .then(setCases)
      .catch(() => toast.error("Could not load cases"))
      .finally(() => setLoading(false));
  }, []);

  const handleCreate = useCallback(async () => {
    const trimmed = title.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      const { case_id } = await createCase(trimmed);
      router.push(`/dude/case/${encodeURIComponent(case_id)}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create case");
      setCreating(false);
    }
  }, [title, creating, router]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-10%] top-[-8rem] h-80 w-80 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="absolute right-[-8%] top-24 h-96 w-96 rounded-full bg-indigo-400/8 blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-72 bg-[radial-gradient(circle_at_top,rgba(139,92,246,0.12),transparent_55%)]" />
      </div>

      <header className="border-b border-border/80 bg-background/70 backdrop-blur-sm">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <Compass className="h-5 w-5 text-violet-400" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              DUDE · Decision Support Under Uncertainty
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

      <main className="mx-auto max-w-4xl space-y-8 px-6 py-10">
        <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6 shadow-lg shadow-slate-950/10">
          <h1 className="text-lg font-semibold text-foreground">New case</h1>
          <div className="mt-4 flex gap-3">
            <input
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void handleCreate();
              }}
              placeholder="Case title"
              className="h-11 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-violet-400/40"
            />
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={!title.trim() || creating}
              className="inline-flex h-11 shrink-0 items-center gap-2 rounded-lg bg-violet-500 px-5 text-sm font-semibold text-white transition-colors hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              New case
            </button>
          </div>
        </section>

        <section className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6">
          <h2 className="text-base font-semibold text-foreground">Cases</h2>
          {loading ? (
            <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading cases…
            </p>
          ) : cases.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">
              No cases yet. Create one above to start capturing evidence.
            </p>
          ) : (
            <ul className="mt-4 divide-y divide-border/60">
              {cases.map((dudeCase) => (
                <li key={dudeCase.case_id}>
                  <Link
                    href={`/dude/case/${encodeURIComponent(dudeCase.case_id)}`}
                    className="flex items-center justify-between gap-4 rounded-lg px-3 py-3 transition-colors hover:bg-accent"
                  >
                    <span className="truncate text-sm font-medium text-foreground">
                      {dudeCase.title}
                    </span>
                    <span className="shrink-0 rounded-full border border-violet-400/25 bg-violet-400/10 px-3 py-0.5 text-[10px] font-medium uppercase tracking-[0.2em] text-violet-200">
                      {dudeCase.status}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  );
}
