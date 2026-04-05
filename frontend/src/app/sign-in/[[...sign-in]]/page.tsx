import Link from "next/link";
import { SignIn } from "@clerk/nextjs";
import { ArrowLeft, ShieldCheck, Workflow } from "lucide-react";
import { BoundStateLogo } from "@/components/BoundStateLogo";

export default function SignInPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-8rem] top-[-6rem] h-72 w-72 rounded-full bg-sky-500/12 blur-3xl" />
        <div className="absolute right-[-4rem] top-20 h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl" />
      </div>

      <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-6 py-8 lg:grid lg:grid-cols-[1fr_420px] lg:items-center lg:gap-16">
        <div className="space-y-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <BoundStateLogo variant="full" size="sm" />
              <div className="h-5 w-px bg-border" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                Oracle
              </span>
            </div>
            <Link
              href="/"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-4 text-sm font-medium transition-colors hover:bg-accent"
            >
              <ArrowLeft className="h-4 w-4" />
              Overview
            </Link>
          </div>

          <div className="space-y-5 pt-12 lg:pt-0">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-sky-200/80">
              Secure access
            </p>
            <h1 className="max-w-2xl text-4xl font-semibold tracking-tight text-balance md:text-5xl">
              Enter Oracle without dropping users into a blank auth wall.
            </h1>
            <p className="max-w-xl text-base leading-8 text-muted-foreground">
              Sign in to open the Oracle workspace and continue reviewing,
              refining, and returning polished deliverables.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-[1.5rem] border border-border/80 bg-card/70 p-5">
              <Workflow className="mb-4 h-5 w-5 text-sky-200" />
              <h2 className="text-sm font-semibold text-foreground">
                Guided workflow
              </h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Review state, critique, and downloads stay in one coherent path.
              </p>
            </div>
            <div className="rounded-[1.5rem] border border-border/80 bg-card/70 p-5">
              <ShieldCheck className="mb-4 h-5 w-5 text-sky-200" />
              <h2 className="text-sm font-semibold text-foreground">
                Controlled access
              </h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Auth remains explicit while the product surface stays polished.
              </p>
            </div>
          </div>
        </div>

        <div className="mt-10 rounded-[2rem] border border-border/80 bg-card/80 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur lg:mt-0">
          <div className="rounded-[1.5rem] border border-border/80 bg-background/70 p-4">
            <SignIn />
          </div>
        </div>
      </div>
    </div>
  );
}
