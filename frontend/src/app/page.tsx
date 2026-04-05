import Link from "next/link";
import {
  ArrowRight,
  FileSearch,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import { BoundStateLogo } from "@/components/BoundStateLogo";

const capabilities = [
  {
    title: "Structured review",
    description:
      "Turn dense drafts into an actionable issue ledger with concrete fixes and evidence.",
    icon: FileSearch,
  },
  {
    title: "Operational resilience",
    description:
      "Long-running review sessions survive disconnects, surface progress clearly, and fail more safely.",
    icon: Workflow,
  },
  {
    title: "Decision support",
    description:
      "Help teams pressure-test complex documents before they move into delivery or governance paths.",
    icon: ShieldCheck,
  },
];

const steps = [
  "Upload a proposal, spec, or working draft.",
  "Run a guided review pass and inspect the critique.",
  "Download polished artifacts directly from the workspace.",
];

export default function OracleLandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-10%] top-[-8rem] h-80 w-80 rounded-full bg-sky-500/12 blur-3xl" />
        <div className="absolute right-[-8%] top-24 h-96 w-96 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-72 bg-[radial-gradient(circle_at_top,rgba(96,165,250,0.18),transparent_55%)]" />
      </div>

      <header className="border-b border-border/80 bg-background/70 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <BoundStateLogo variant="full" size="sm" />
            <div className="h-5 w-px bg-border" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Oracle
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/sign-in"
              className="inline-flex h-9 items-center rounded-lg border border-border px-4 text-sm font-medium text-foreground transition-colors hover:bg-accent"
            >
              Sign In
            </Link>
            <Link
              href="/workspace"
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90"
            >
              Open Workspace
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-16">
        <section className="grid gap-12 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
          <div className="space-y-8">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-400/8 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.28em] text-sky-200">
              <Sparkles className="h-3.5 w-3.5" />
              Document Intelligence
            </div>

            <div className="space-y-4">
              <h1 className="max-w-3xl text-2xl font-semibold tracking-tight text-balance text-foreground md:text-3xl">
                Review dense drafts with the kind of operator experience they
                actually deserve.
              </h1>
              <p className="max-w-2xl text-lg leading-8 text-muted-foreground">
                Oracle is BoundState&apos;s document intelligence workspace for
                reviewing, refining, and returning polished artifacts without
                losing visibility into what the system is doing.
              </p>
            </div>

            <div className="flex flex-wrap gap-4">
              <Link
                href="/workspace"
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-medium text-primary-foreground transition-transform hover:-translate-y-0.5"
              >
                Enter Oracle
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/sign-in"
                className="inline-flex h-11 items-center rounded-lg border border-border bg-card px-5 text-sm font-medium text-foreground transition-colors hover:bg-accent"
              >
                Sign In
              </Link>
            </div>

            <div className="grid gap-3 pt-2 text-sm text-muted-foreground sm:grid-cols-3">
              <div className="rounded-2xl border border-border/80 bg-card/70 px-4 py-4">
                Multi-step critique
              </div>
              <div className="rounded-2xl border border-border/80 bg-card/70 px-4 py-4">
                Live progress visibility
              </div>
              <div className="rounded-2xl border border-border/80 bg-card/70 px-4 py-4">
                Polished deliverables
              </div>
            </div>
          </div>

          <div className="rounded-[2rem] border border-border/80 bg-card/70 p-6 shadow-2xl shadow-sky-950/20 backdrop-blur">
            <div className="rounded-[1.5rem] border border-sky-400/15 bg-[linear-gradient(180deg,rgba(8,47,73,0.65),rgba(15,23,42,0.85))] p-6">
              <div className="mb-5 flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-[0.28em] text-sky-200/80">
                  Workflow
                </span>
                <span className="rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1 text-xs text-sky-100">
                  Public entry
                </span>
              </div>
              <div className="space-y-4">
                {steps.map((step, index) => (
                  <div
                    key={step}
                    className="flex items-start gap-4 rounded-2xl border border-white/8 bg-black/10 px-4 py-4"
                  >
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-400/15 text-xs font-semibold text-sky-100">
                      {index + 1}
                    </div>
                    <p className="text-sm leading-6 text-slate-200">{step}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mt-20 grid gap-5 md:grid-cols-3">
          {capabilities.map(({ title, description, icon: Icon }) => (
            <div
              key={title}
              className="rounded-[1.75rem] border border-border/80 bg-card/70 p-6 shadow-lg shadow-slate-950/10"
            >
              <div className="mb-5 inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-sky-400/10 text-sky-200">
                <Icon className="h-5 w-5" />
              </div>
              <h2 className="text-lg font-semibold text-foreground">{title}</h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">
                {description}
              </p>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
