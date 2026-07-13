"""
Oracle Code Review — automated adversarial CODE review across multiple AI agents.

The code-review sibling of oracle.py. Where oracle.py reviews specs via raw APIs,
this tool reviews diffs/code using the locally installed agent CLIs, so reviewers
can read the actual repo for context (and bill to existing subscriptions):

  - Atlas (Codex CLI, `codex exec`, gpt-5.6 sol/terra) — adversarial code architecture review
  - Ben   (Grok Build CLI, `grok -p`)                  — practical/scale/simplification review
  - Beth  (Claude Fable via Anthropic API)             — correctness + standards, synthesizer

Workflow:
  1. Collect the diff (working tree vs HEAD by default, or vs --base ref)
  2. Write a review request file (instructions + diff) into the output dir
  3. Run all reviewers in PARALLEL; CLI agents run with cwd = the target repo
  4. Beth synthesizes all reviews into MERGED_REVIEW.md with a verdict:
     SHIP / FIX FIRST / BLOCK

Usage:
    py oracle_review.py                                # review uncommitted changes in cwd
    py oracle_review.py --repo D:/BoundState/boundstate_mira
    py oracle_review.py --base main                    # review branch vs main
    py oracle_review.py --files src/engine.py          # review specific files (no git needed)
    py oracle_review.py --reviewers atlas beth         # subset of reviewers
    py oracle_review.py --atlas terra-high             # Codex on gpt-5.6-terra, high effort
    py oracle_review.py --no-synthesis                 # skip Beth's merge pass
    py oracle_review.py --list                         # show reviewer availability

Requires: codex CLI (Atlas), grok CLI (Ben), ANTHROPIC_API_KEY (Beth + synthesis).
Missing reviewers are skipped with a warning, not a crash.
"""
__safety_critical__: bool = False

import argparse
import io
import logging
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Fix Windows console encoding
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger("oracle.pipeline.review")

MAX_DIFF_CHARS = 200_000  # hard cap on diff size embedded in the request file
DEFAULT_TIMEOUT_S = 900   # 15 min per reviewer

BETH_MODEL = "claude-fable-5"
# Atlas presets per Joe: "sol medium" (deep model, medium effort) or "terra high"
ATLAS_PRESETS: dict[str, tuple[str, str]] = {
    "sol-medium": ("gpt-5.6-sol", "medium"),
    "terra-high": ("gpt-5.6-terra", "high"),
}
DEFAULT_ATLAS_PRESET = "sol-medium"

# ── Review lenses ───────────────────────────────────────────────────────────

FINDINGS_FORMAT = """Report findings as a numbered list, most severe first. For each:
**[SEVERITY: Critical|High|Medium|Low] file:line — one-line summary**
- Issue: what is wrong
- Why it matters: the concrete failure scenario (inputs/state -> wrong behavior)
- Fix: the minimal suggested change (sketch code where useful)

End with a one-line verdict: `VERDICT: SHIP` (no blocking issues),
`VERDICT: FIX FIRST` (fix High/Critical before merge), or `VERDICT: BLOCK`
(fundamental problem, needs rework). If you found nothing real, say so plainly —
do not invent findings to look thorough."""

REVIEWERS: dict[str, dict[str, Any]] = {
    "atlas": {
        "name": "Atlas",
        "role": "Code Architecture Review (Codex)",
        "kind": "cli",
        "lens": """You are Atlas, BoundState's adversarial code architecture reviewer.

Your review lens:
- Correctness first: logic errors, off-by-ones, race conditions, broken edge cases.
- Structure: right abstractions, right boundaries, right naming? Testable without mocking the world?
- Dependencies and integration: does this fit the existing codebase? Breaking changes?
- Performance: obvious bottlenecks, N+1 queries, unnecessary work in hot paths.
- Python: type hints, Pydantic extra="forbid", no bare except, logging not print.
- TypeScript/React: component-level types, Tailwind, no inline styles.

You may read any file in this repository (read-only) to understand context around
the diff. Follow changed functions to their call sites before judging them.""",
    },
    "ben": {
        "name": "Ben",
        "role": "Practical / Scale / Simplification (Grok)",
        "kind": "cli",
        "lens": """You are Ben, BoundState's blunt practical reviewer.

Your review lens:
- Is this over-engineered? Is there a version half this size that does the same job?
- Scale: what happens at 10x data, 10x users, 10x call volume?
- Cost and operational reality: what pages someone at 3 AM?
- Dead weight: unused params, speculative generality, copy-paste drift.
- Say what everyone's thinking: if a change is gold, say so; if it's vanity, say that too.

You may read any file in this repository (READ-ONLY — do not modify anything)
to understand context around the diff.""",
    },
    "beth": {
        "name": "Beth",
        "role": "Correctness + BoundState Standards (Claude)",
        "kind": "api",
        "lens": """You are Beth, BoundState's CTO and lead reviewer.

Your review lens:
- Correctness: real bugs with concrete failure scenarios, not style nits.
- Evidence-first / negative-selection philosophy: does the code refuse deterministically
  when evidence is insufficient? No claims without provenance?
- Safety-critical standards where applicable: NASA-STD-8739.8B, SWE-013/032/033,
  __safety_critical__ headers on compliance/materials/engineering modules.
- Interfaces: could another engineer extend this without reading the whole system?
- Will this still make sense in 6 months?""",
    },
}

SYNTH_SYSTEM = """You are Beth, BoundState's CTO. You have received code-review findings
from multiple reviewers on the same diff. Synthesize them into ONE authoritative review.

Rules:
- Deduplicate: reviewers often find the same issue — merge into one finding, note who flagged it.
- Adjudicate: if reviewers disagree, or a finding looks wrong against the diff, make the call
  and say why. Kill hallucinated findings (issues not actually supported by the diff).
- Rank the merged findings most-severe first, keeping the same per-finding format.
- Be decisive, no hedging.

Output format:
1. `## Verdict` — SHIP / FIX FIRST / BLOCK, one paragraph of justification.
2. `## Merged Findings` — the deduplicated, adjudicated, ranked list.
3. `## Dismissed` — findings you rejected and the one-line reason each.
4. `## Reviewer Disagreements` — any calls you made between conflicting reviewers."""


# ── Diff collection ─────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    """Run a git command in the repo and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _collect_untracked(repo: Path) -> str:
    """Collect contents of untracked files for review (shared by base and no-base paths).

    Filters out pipeline outputs and bytecode. Large files are noted rather than inlined.
    """
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard").strip()
    if not untracked:
        return ""
    parts: list[str] = ["\n\n# --- untracked files (contents) ---\n\n"]
    for f in untracked.splitlines():
        # never review pipeline output or bytecode
        if (f.startswith(("oracle_reviews/", "oracle_builds/"))
                or "__pycache__" in f or f.endswith((".pyc", ".pyo"))):
            continue
        p = repo / f
        try:
            if p.stat().st_size > 200_000:
                parts.append(f"### NEW FILE (too large to inline): {f}\n\n")
                continue
            parts.append(f"### NEW FILE: {f}\n```\n{p.read_text(encoding='utf-8', errors='replace')}\n```\n\n")
        except Exception:
            parts.append(f"### NEW FILE (unreadable): {f}\n\n")
    return "".join(parts)


def collect_diff(repo: Path, base: str | None, files: list[str] | None, *, strict: bool = False) -> tuple[str, str]:
    """Collect the text to review. Returns (label, content).

    When strict=True (final gate), fail instead of truncating: Beth has no
    repository access and a truncated diff means she cannot see the full change.
    """
    if files:
        parts = []
        for f in files:
            p = (repo / f) if not Path(f).is_absolute() else Path(f)
            if not p.exists():
                raise FileNotFoundError(f"File not found: {p}")
            if p.stat().st_size > 2_000_000:
                raise ValueError(f"{p} is >2MB — review it in pieces, not whole")
            parts.append(f"### FILE: {f}\n```\n{p.read_text(encoding='utf-8', errors='replace')}\n```")
        return f"files: {', '.join(files)}", "\n\n".join(parts)

    if base:
        label = f"git diff {base}...HEAD (+ working tree)"
        diff = _git(repo, "diff", f"{base}...HEAD")
        wt = _git(repo, "diff", "HEAD")
        if wt.strip():
            diff += "\n\n# --- uncommitted working-tree changes on top ---\n\n" + wt
        # Untracked files are part of the working tree for any review scope.
        # Previously only collected in the no-base path (Medium finding).
        diff += _collect_untracked(repo)
    else:
        label = "git diff HEAD (uncommitted changes)"
        diff = _git(repo, "diff", "HEAD")
        diff += _collect_untracked(repo)

    if not diff.strip():
        raise ValueError("Nothing to review — diff is empty. Use --base <ref> or --files.")
    if len(diff) > MAX_DIFF_CHARS:
        if strict:
            raise ValueError(
                f"Diff is {len(diff)} chars — exceeds final-gate capacity of {MAX_DIFF_CHARS}. "
                "Beth (no repo access) cannot review a truncated diff. Reduce scope or split the change."
            )
        LOGGER.warning("Diff is %d chars; truncating to %d. Consider reviewing in pieces.",
                       len(diff), MAX_DIFF_CHARS)
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[... TRUNCATED — diff exceeded size cap ...]"
    return label, diff


# ── Reviewer runners ────────────────────────────────────────────────────────

def _resolve_cmd(name: str) -> list[str] | None:
    """Resolve a CLI to an invocable argv, handling Windows .cmd/.bat shims."""
    path = shutil.which(name)
    if not path:
        return None
    if path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", path]
    return [path]


def _run_cli(argv: list[str], cwd: Path, timeout: int, stdin_text: str | None = None) -> str:
    """Run a CLI reviewer and return combined output."""
    result = subprocess.run(
        argv, cwd=str(cwd), input=stdin_text,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    out = result.stdout.strip()
    if result.returncode != 0:
        err = result.stderr.strip()[-2000:]
        return f"[ERROR] exit code {result.returncode}\nstderr tail:\n{err}\n\npartial stdout:\n{out}"
    return out or f"[ERROR] empty output. stderr tail:\n{result.stderr.strip()[-2000:]}"


def _reviewer_prompt(reviewer_id: str, request_path: Path) -> str:
    """The short prompt handed to a CLI agent (full request lives in the file)."""
    return (
        f"{REVIEWERS[reviewer_id]['lens']}\n\n"
        f"Read the review request at this path: {request_path}\n"
        f"It contains the full instructions and the diff. Perform the review, then print "
        f"your COMPLETE review (findings + verdict) as your final message."
    )


def run_atlas(request_path: Path, repo: Path, timeout: int, preset: str) -> str:
    """Atlas = codex exec, read-only sandbox, prompt via stdin."""
    base = _resolve_cmd("codex")
    if not base:
        return "[SKIPPED] codex CLI not found on PATH"
    model, effort = ATLAS_PRESETS[preset]
    return _run_cli(
        base + ["exec", "--sandbox", "read-only", "--skip-git-repo-check",
                "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-"],
        cwd=repo, timeout=timeout, stdin_text=_reviewer_prompt("atlas", request_path))


def run_ben(request_path: Path, repo: Path, timeout: int) -> str:
    """Ben = grok CLI single-turn headless mode."""
    base = _resolve_cmd("grok")
    if not base:
        return "[SKIPPED] grok CLI not found on PATH"
    return _run_cli(
        base + ["-p", _reviewer_prompt("ben", request_path),
                "--output-format", "plain", "--max-turns", "40"],
        cwd=repo, timeout=timeout)


def _anthropic_api_key() -> str | None:
    """ANTHROPIC_API_KEY from the environment, falling back to the user-level
    registry value on Windows (long-lived shells inherit stale copies after setx)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    reg_key: str | None = None
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as env:
                reg_key = winreg.QueryValueEx(env, "ANTHROPIC_API_KEY")[0]
        except OSError:
            reg_key = None
    if reg_key and reg_key != key:
        LOGGER.warning("Process ANTHROPIC_API_KEY differs from user-level value; "
                       "using the user-level (setx) one.")
        return reg_key
    return key


def _call_anthropic(system: str, user_prompt: str, timeout: int | None = None) -> str:
    """Call Claude via the Anthropic API (Beth review + synthesis).

    Respects the caller's timeout (passed to client) so a hung Beth call
    cannot block the review pipeline indefinitely.
    """
    try:
        import anthropic
    except ImportError:
        return "[SKIPPED] anthropic package not installed. Run: uv pip install anthropic"
    api_key = _anthropic_api_key()
    if not api_key:
        return "[SKIPPED] ANTHROPIC_API_KEY not set"
    # Use provided timeout (or a conservative default) on the client.
    # This ensures the HTTP layer itself will time out rather than hang.
    client_timeout = float(timeout) if timeout is not None else 600.0
    client = anthropic.Anthropic(api_key=api_key, timeout=client_timeout)
    try:
        create_args: dict = dict(
            model=BETH_MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # claude-fable-5: thinking is always on and effort defaults to "high" —
        # exactly what we want, so send NO thinking/effort config. Explicit
        # `thinking: {type: "enabled", budget_tokens: N}` returns 400 on Fable,
        # and `output_config` requires a newer anthropic SDK than installed.

        # Some SDK versions accept per-call timeout here; the client already has one.
        if timeout is not None:
            create_args["timeout"] = float(timeout)

        response = client.messages.create(**create_args)
    except anthropic.APIError as e:
        return f"[ERROR] Anthropic API call failed: {e}"
    # Reasoning models return thinking blocks before text — keep only text blocks
    text = "".join(b.text for b in response.content if b.type == "text")
    return text or "[ERROR] empty text response from Anthropic API"


def run_beth(request_text: str, timeout: int) -> str:
    """Beth = Claude via API. Gets the request text directly (no repo access)."""
    return _call_anthropic(
        REVIEWERS["beth"]["lens"],
        f"{request_text}\n\nNote: you are reviewing the diff as given — you cannot read "
        f"the rest of the repo. Flag anything you'd want to verify against surrounding "
        f"code as `[NEEDS REPO CHECK]` rather than asserting it.",
        timeout=timeout,
    )


# ── Orchestration ───────────────────────────────────────────────────────────

def build_request(label: str, diff: str, repo: Path) -> str:
    """The shared review request document all reviewers see."""
    return (
        f"# Code Review Request\n\n"
        f"**Repo:** {repo}\n"
        f"**Scope:** {label}\n"
        f"**Date:** {datetime.now().isoformat()}\n\n"
        f"## Instructions\n\n{FINDINGS_FORMAT}\n\n"
        f"## Diff / Code Under Review\n\n{diff}\n"
    )


def run_review(
    repo: Path,
    base: str | None,
    files: list[str] | None,
    reviewer_ids: list[str],
    output_dir: Path,
    timeout: int,
    synthesize: bool,
    atlas_preset: str = DEFAULT_ATLAS_PRESET,
) -> None:
    """Collect diff, fan out to reviewers in parallel, optionally synthesize."""
    label, diff = collect_diff(repo, base, files)
    LOGGER.info("Collected %s (%d chars)", label, len(diff))

    output_dir.mkdir(parents=True, exist_ok=True)
    request_text = build_request(label, diff, repo)
    request_path = output_dir / "review_request.md"
    request_path.write_text(request_text, encoding="utf-8")

    runners: dict[str, Callable[[], str]] = {
        "atlas": lambda: run_atlas(request_path.resolve(), repo, timeout, atlas_preset),
        "ben": lambda: run_ben(request_path.resolve(), repo, timeout),
        "beth": lambda: run_beth(request_text, timeout),
    }

    LOGGER.info("═══ Phase 1: Parallel Review (%s) ═══", ", ".join(reviewer_ids))
    reviews: dict[str, str] = {}
    executor = ThreadPoolExecutor(max_workers=len(reviewer_ids))
    try:
        futures = {rid: executor.submit(runners[rid]) for rid in reviewer_ids}
        for rid, fut in futures.items():
            try:
                reviews[rid] = fut.result(timeout=timeout + 60)
            except subprocess.TimeoutExpired:
                reviews[rid] = f"[ERROR] {REVIEWERS[rid]['name']} timed out after {timeout}s"
            except FutureTimeout:
                reviews[rid] = f"[ERROR] {REVIEWERS[rid]['name']} timed out after {timeout}s"
            except Exception as e:  # noqa: BLE001 — reviewer failure must not kill the run
                reviews[rid] = f"[ERROR] {REVIEWERS[rid]['name']} failed: {e}"
            LOGGER.info("  %s done (%d chars)", REVIEWERS[rid]["name"], len(reviews[rid]))
    finally:
        # Use wait=False so that a hung (or just-slow-finishing) reviewer thread
        # cannot block process exit or the next stage of the pipeline.
        executor.shutdown(wait=False)

    for rid, review in reviews.items():
        name = REVIEWERS[rid]["name"]
        (output_dir / f"{rid}.md").write_text(
            f"# {name} — {REVIEWERS[rid]['role']}\n\n{review}\n", encoding="utf-8")
        print(f"\n{'─' * 60}\n  {name} ({REVIEWERS[rid]['role']})\n{'─' * 60}\n{review}\n")

    usable = {rid: r for rid, r in reviews.items()
              if not r.startswith(("[SKIPPED]", "[ERROR]"))}

    if synthesize and len(usable) >= 2:
        LOGGER.info("═══ Phase 2: Beth Synthesizes → MERGED_REVIEW.md ═══")
        feedback = "\n\n".join(
            f"### Review by {REVIEWERS[rid]['name']} ({REVIEWERS[rid]['role']})\n{r}"
            for rid, r in usable.items())
        merged = _call_anthropic(
            SYNTH_SYSTEM,
            f"## The Diff Under Review\n\n{diff}\n\n## Reviewer Findings\n\n{feedback}\n\n"
            f"## Your Task\nSynthesize into the single authoritative review.",
            timeout=timeout,
        )
        if merged.startswith(("[ERROR]", "[SKIPPED]")):
            LOGGER.warning("Synthesis failed: %s — individual reviews are still saved", merged)
        (output_dir / "MERGED_REVIEW.md").write_text(
            f"# Merged Oracle Code Review\n\n**Scope:** {label}\n\n{merged}\n",
            encoding="utf-8")
        print(f"\n{'═' * 60}\n  MERGED REVIEW (Beth synthesis)\n{'═' * 60}\n{merged}\n")
    elif synthesize:
        LOGGER.warning("Skipping synthesis — need >=2 successful reviews, got %d", len(usable))

    LOGGER.info("Outputs saved to %s", output_dir)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Oracle Code Review — adversarial multi-agent code review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py oracle_review.py                          # review uncommitted changes in cwd
  py oracle_review.py --repo D:/BoundState/boundstate_mira --base main
  py oracle_review.py --files src/engine.py    # no git required
  py oracle_review.py --reviewers atlas beth   # subset
""",
    )
    parser.add_argument("--repo", default=".", help="Target repo (default: cwd)")
    parser.add_argument("--base", help="Base ref: review base...HEAD + working tree "
                                       "(default: uncommitted changes only)")
    parser.add_argument("--files", nargs="+", help="Review specific files instead of a diff")
    parser.add_argument("--reviewers", nargs="+", choices=list(REVIEWERS.keys()),
                        default=list(REVIEWERS.keys()), help="Which reviewers (default: all)")
    parser.add_argument("--output", help="Output dir (default: <repo>/oracle_reviews/<timestamp>)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S,
                        help=f"Per-reviewer timeout in seconds (default: {DEFAULT_TIMEOUT_S})")
    parser.add_argument("--atlas", choices=list(ATLAS_PRESETS.keys()),
                        default=DEFAULT_ATLAS_PRESET,
                        help=f"Codex model preset for Atlas (default: {DEFAULT_ATLAS_PRESET})")
    parser.add_argument("--no-synthesis", action="store_true", help="Skip Beth's merge pass")
    parser.add_argument("--list", action="store_true", help="Show reviewer availability")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable Reviewers:")
        checks = {
            "atlas": lambda: shutil.which("codex") is not None,
            "ben": lambda: shutil.which("grok") is not None,
            "beth": lambda: bool(_anthropic_api_key()),
        }
        for rid, rv in REVIEWERS.items():
            ok = "✓" if checks[rid]() else "✗"
            print(f"  {rid:<8s} {rv['name']:<8s} {rv['role']:<45s} [{rv['kind']}] {ok}")
        print("\nSynthesis requires ANTHROPIC_API_KEY.")
        return

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        LOGGER.error("Repo directory not found: %s", repo)
        sys.exit(1)

    output_dir = (Path(args.output) if args.output
                  else repo / "oracle_reviews" / datetime.now().strftime("%Y%m%d_%H%M%S"))

    print(f"\n{'═' * 60}")
    print("  ORACLE CODE REVIEW")
    print(f"  Repo: {repo}")
    print(f"  Reviewers: {', '.join(REVIEWERS[r]['name'] for r in args.reviewers)}")
    print(f"{'═' * 60}\n")

    run_review(repo, args.base, args.files, args.reviewers, output_dir,
               args.timeout, synthesize=not args.no_synthesis, atlas_preset=args.atlas)

    print(f"\n{'═' * 60}\n  REVIEW COMPLETE — {output_dir}\n{'═' * 60}\n")


if __name__ == "__main__":
    main()
