"""
Oracle Build Pipeline — spec → build → review → final gate, fully automated.

The delivery half of the oracle toolchain. oracle.py polishes a spec; this tool
takes that polished spec and runs it through the build ensemble:

  1. BUILD  — Ben (Grok Build CLI) implements the spec in the target repo
  2. REVIEW — Atlas (Codex CLI, gpt-5.6-terra @ high effort) reviews the diff
  3. FIX    — if Atlas says FIX FIRST/BLOCK, Ben fixes the findings (looped)
  4. GATE   — Beth (Claude Fable, high effort) gives the final thumbs up/down
              against BOTH the spec and the final diff: APPROVED / CHANGES
              REQUIRED / REJECTED

NOTE: the build/fix stages run Grok Build unattended with tool execution
auto-approved (Joe authorized this 2026-07-13). Guardrails: requires a clean
working tree (unless --allow-dirty), never commits or pushes, Codex review is
read-only — a bad build is bounded to uncommitted changes in one repo.

Usage:
    py oracle_build.py FINAL_SPEC.md --repo D:/BoundState/boundstate_mira
    py oracle_build.py spec.md --fix-rounds 2          # allow 2 fix cycles
    py oracle_build.py spec.md --skip-build            # review+gate existing changes
    py oracle_build.py spec.md --allow-dirty           # don't require clean tree

Requires: grok CLI, codex CLI, ANTHROPIC_API_KEY (falls back to registry).
Shares its plumbing with oracle_review.py (same directory).
"""
__safety_critical__: bool = False

import argparse
import io
import logging
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

# Robust import so this works both as:
#   py pipeline/oracle_build.py   (script mode)
#   import pipeline.oracle_build  (package/submodule from server)
try:
    from . import oracle_review as orv  # when imported as package
except ImportError:
    import oracle_review as orv  # script / path mode


# Fix Windows console encoding
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger("oracle.pipeline.build")

BUILD_TIMEOUT_S = 3600    # grok build / fix passes
REVIEW_TIMEOUT_S = 1200   # codex review passes
ATLAS_PRESET = "terra-high"

BUILD_PROMPT = """You are Ben, BoundState's implementation engineer (Grok Build).

Implement the specification in the file at: {spec_path}

Rules:
- Work only in this repository. Follow the existing code style and structure.
- BoundState standards: Python type hints everywhere, Pydantic extra="forbid",
  no bare except, logging not print, docstrings on public classes/functions.
- Write tests alongside the implementation where the spec implies testable behavior.
- Do NOT git commit, push, or create branches — leave changes in the working tree.
- If part of the spec is ambiguous, make the pragmatic call and note it.

When finished, print a build summary as your final message: files created/modified,
key decisions made, anything you deliberately deferred, and how to run the tests."""

FIX_PROMPT = """You are Ben, BoundState's implementation engineer (Grok Build).

You previously implemented a spec in this repository. A code reviewer (Atlas)
has reviewed your diff and found issues. His review is in the file at: {review_path}
The original spec is at: {spec_path}

Fix every Critical and High finding. Fix Medium findings unless doing so
conflicts with the spec — if you dismiss a finding, say why. Low findings are
your judgment call.

Do NOT git commit or push. When finished, print a fix summary as your final
message: findings addressed (with what you changed), and findings dismissed (with why)."""

GATE_SYSTEM = """You are Beth, BoundState's CTO, performing the FINAL release gate on an
implementation that was built by Grok Build and reviewed by Codex.

Judge the final diff against the SPEC — not just against generic code quality:
- Does the implementation actually satisfy the spec's requirements? List any gaps.
- Were the reviewer's Critical/High findings genuinely fixed, or papered over?
- Correctness: any remaining real bugs with concrete failure scenarios.
- BoundState standards: evidence-first behavior, deterministic refusal on missing
  evidence, type hints, no bare except, __safety_critical__ headers where applicable.

Output format:
1. `## Final Verdict` — exactly one of: APPROVED / CHANGES REQUIRED / REJECTED,
   with one paragraph of justification.
2. `## Spec Coverage` — requirement-by-requirement: met / partial / missing.
3. `## Residual Findings` — anything still wrong, ranked, same format as the reviews.
4. `## Notes for Joe` — decisions he should personally sanity-check.

Be decisive. APPROVED means you would ship this diff as-is."""

VERDICT_RE = re.compile(r"VERDICT:\s*(SHIP|FIX FIRST|BLOCK)", re.IGNORECASE)
GATE_VERDICT_RE = re.compile(r"(APPROVED|CHANGES REQUIRED|REJECTED)", re.IGNORECASE)


def parse_verdict(review: str) -> str:
    """Extract the reviewer's verdict; default to FIX FIRST when absent."""
    m = VERDICT_RE.search(review)
    return m.group(1).upper() if m else "FIX FIRST"


def parse_gate_verdict(gate_output: str) -> str:
    """Extract Beth's final gate verdict. Fails closed to CHANGES REQUIRED.

    Only the token under the canonical `## Final Verdict` heading counts —
    a free-text scan can read "I cannot mark this APPROVED" as APPROVED.
    """
    if not gate_output or gate_output.strip().startswith(("[ERROR]", "[SKIPPED]", "[GATE INPUT ERROR]")):
        LOGGER.warning("Gate output missing, skipped, or errored — failing closed as CHANGES REQUIRED")
        return "CHANGES REQUIRED"
    heading = re.search(r"##\s*Final Verdict\b(.{0,400})", gate_output, re.IGNORECASE | re.DOTALL)
    if not heading:
        LOGGER.warning("Gate output has no '## Final Verdict' heading — failing closed")
        return "CHANGES REQUIRED"
    m = GATE_VERDICT_RE.search(heading.group(1))
    if not m:
        LOGGER.warning("No APPROVED/CHANGES REQUIRED/REJECTED under the verdict heading — failing closed")
        return "CHANGES REQUIRED"
    v = m.group(1).upper()
    return "CHANGES REQUIRED" if "CHANGES" in v else v


def run_grok(prompt: str, repo: Path, timeout: int) -> str:
    """Run a Grok Build pass with write access to the repo (auto-approved tools)."""
    base = orv._resolve_cmd("grok")
    if not base:
        raise RuntimeError("grok CLI not found on PATH")
    return orv._run_cli(
        base + ["-p", prompt, "--output-format", "plain", "--always-approve",
                "--max-turns", "200"],
        cwd=repo, timeout=timeout)


def run_atlas_review(spec_path: Path, repo: Path, out_dir: Path, round_num: int) -> tuple[str, Path]:
    """Codex (terra-high) reviews the current diff against the spec. Returns (review, path)."""
    # Atlas has repo access via sandbox; truncation is a warning only.
    label, diff = orv.collect_diff(repo, base=None, files=None)
    request_text = (
        f"# Code Review Request (Build Pipeline, round {round_num})\n\n"
        f"**Repo:** {repo}\n**Scope:** {label}\n\n"
        f"## The Spec This Diff Implements\n\nRead it at: {spec_path}\n\n"
        f"## Instructions\n\nReview the diff BOTH for correctness and for whether it "
        f"actually implements the spec. Flag spec requirements the diff misses.\n\n"
        f"{orv.FINDINGS_FORMAT}\n\n"
        f"## Diff Under Review\n\n{diff}\n"
    )
    request_path = out_dir / f"review_request_round{round_num}.md"
    request_path.write_text(request_text, encoding="utf-8")

    base = orv._resolve_cmd("codex")
    if not base:
        raise RuntimeError("codex CLI not found on PATH")
    model, effort = orv.ATLAS_PRESETS[ATLAS_PRESET]
    prompt = (
        f"{orv.REVIEWERS['atlas']['lens']}\n\n"
        f"Read the review request at this path: {request_path.resolve()}\n"
        f"It contains the instructions and the diff; it also points at the spec file — "
        f"read that too. Perform the review, then print your COMPLETE review "
        f"(findings + verdict) as your final message."
    )
    review = orv._run_cli(
        base + ["exec", "--sandbox", "read-only", "--skip-git-repo-check",
                "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-"],
        cwd=repo, timeout=REVIEW_TIMEOUT_S, stdin_text=prompt)

    review_path = out_dir / f"atlas_review_round{round_num}.md"
    review_path.write_text(f"# Atlas Review — Round {round_num}\n\n{review}\n", encoding="utf-8")
    return review, review_path


def run_pipeline(
    spec_path: Path,
    repo: Path,
    fix_rounds: int,
    skip_build: bool,
    out_dir: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> str:
    """Execute build → review → fix loop → Fable final gate.

    Returns the final gate verdict: APPROVED / CHANGES REQUIRED / REJECTED.

    If `progress` is provided (for web UI), stage headers and key summaries
    are also emitted to it. CLI behavior is unchanged.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_text = spec_path.read_text(encoding="utf-8")

    def emit(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass
        # Always log for CLI + file capture
        LOGGER.info(msg)

    # ── Stage 1: Build ──────────────────────────────────────────────────
    if skip_build:
        emit("═══ Stage 1: BUILD skipped (--skip-build) ═══")
    else:
        emit("═══ Stage 1: BUILD — Ben (Grok Build) implements the spec ═══")
        build_log = run_grok(BUILD_PROMPT.format(spec_path=spec_path.resolve()),
                             repo, BUILD_TIMEOUT_S)
        (out_dir / "build_log.md").write_text(f"# Build Log (Grok)\n\n{build_log}\n",
                                              encoding="utf-8")
        # CLI-visible banner + progress
        summary = f"\n{'─' * 60}\n  BEN — BUILD SUMMARY\n{'─' * 60}\n{build_log}\n"
        print(summary)
        emit("BEN BUILD SUMMARY (see build_log.md)")

    # ── Stage 2/3: Review + fix loop ────────────────────────────────────
    reviews: list[str] = []
    verdict = "FIX FIRST"
    for round_num in range(1, fix_rounds + 2):  # initial review + one per fix round
        emit(f"═══ Stage 2: REVIEW round {round_num} — Atlas (Codex {ATLAS_PRESET}) ═══")
        review, review_path = run_atlas_review(spec_path, repo, out_dir, round_num)
        reviews.append(f"### Atlas Review — Round {round_num}\n{review}")
        verdict = parse_verdict(review)
        review_banner = f"\n{'─' * 60}\n  ATLAS — REVIEW ROUND {round_num} → {verdict}\n{'─' * 60}\n{review}\n"
        print(review_banner)
        emit(f"ATLAS REVIEW ROUND {round_num} → {verdict} (see atlas_review_round{round_num}.md)")

        if verdict == "SHIP":
            break
        if round_num > fix_rounds:
            emit(f"Fix rounds exhausted with verdict {verdict} — proceeding to gate")
            break

        emit(f"═══ Stage 3: FIX round {round_num} — Ben addresses findings ═══")
        fix_log = run_grok(
            FIX_PROMPT.format(review_path=review_path.resolve(), spec_path=spec_path.resolve()),
            repo, BUILD_TIMEOUT_S)
        (out_dir / f"fix_log_round{round_num}.md").write_text(
            f"# Fix Log — Round {round_num}\n\n{fix_log}\n", encoding="utf-8")
        fix_banner = f"\n{'─' * 60}\n  BEN — FIX ROUND {round_num}\n{'─' * 60}\n{fix_log}\n"
        print(fix_banner)
        emit(f"BEN FIX ROUND {round_num} (see fix_log_round{round_num}.md)")

    # ── Stage 4: Fable final gate ───────────────────────────────────────
    emit("═══ Stage 4: FINAL GATE — Beth (Claude Fable, high effort) ═══")
    try:
        _, final_diff = orv.collect_diff(repo, base=None, files=None, strict=True)
    except ValueError as exc:
        # Fail closed: Beth must see the full diff. Emit a gate failure verdict.
        gate = f"[GATE INPUT ERROR] {exc}\n\n## Final Verdict\nCHANGES REQUIRED\n\nDiff too large for safe final gate without repository context."
        report = (
            f"# Oracle Build Pipeline Report\n\n"
            f"**Spec:** {spec_path}\n**Repo:** {repo}\n"
            f"**Date:** {datetime.now().isoformat()}\n"
            f"**Atlas rounds:** {len(reviews)} (last verdict: {verdict})\n\n"
            f"{gate}\n"
        )
        (out_dir / "PIPELINE_REPORT.md").write_text(report, encoding="utf-8")
        gate_banner = f"\n{'═' * 60}\n  BETH (FABLE) — FINAL GATE (REFUSED INPUT)\n{'═' * 60}\n{gate}\n"
        print(gate_banner)
        emit("BETH FINAL GATE REFUSED — diff exceeded gate capacity")
        return "CHANGES REQUIRED"  # fail closed; final_diff is unbound past here

    review_history = "\n\n".join(reviews)
    gate = orv._call_anthropic(
        GATE_SYSTEM,
        f"## The Spec\n\n{spec_text}\n\n"
        f"## The Final Diff\n\n{final_diff}\n\n"
        f"## Review History (Atlas, chronological)\n\n{review_history}\n\n"
        f"## Your Task\nPerform the final release gate.",
        timeout=1800,  # generous for high-effort Fable gate; still bounded
    )

    gate_verdict = parse_gate_verdict(gate)
    report = (
        f"# Oracle Build Pipeline Report\n\n"
        f"**Spec:** {spec_path}\n**Repo:** {repo}\n"
        f"**Date:** {datetime.now().isoformat()}\n"
        f"**Atlas rounds:** {len(reviews)} (last verdict: {verdict})\n"
        f"**Final Gate:** {gate_verdict}\n\n"
        f"{gate}\n"
    )
    (out_dir / "PIPELINE_REPORT.md").write_text(report, encoding="utf-8")
    gate_banner = f"\n{'═' * 60}\n  BETH (FABLE) — FINAL GATE → {gate_verdict}\n{'═' * 60}\n{gate}\n"
    print(gate_banner)
    emit(f"BETH FINAL GATE → {gate_verdict} (see PIPELINE_REPORT.md)")
    emit(f"Pipeline artifacts saved to {out_dir}")
    return gate_verdict


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Oracle Build Pipeline — spec → Grok builds → Codex reviews → Fable gates")
    parser.add_argument("spec", help="Path to the polished spec (e.g. FINAL_SPEC.md from oracle.py)")
    parser.add_argument("--repo", default=".", help="Target repo (default: cwd)")
    parser.add_argument("--fix-rounds", type=int, default=1,
                        help="Max Ben fix cycles after a non-SHIP review (default: 1)")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip the build stage; review+gate the existing working-tree changes")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="Proceed even if the working tree has pre-existing changes")
    parser.add_argument("--output", help="Artifact dir (default: <repo>/oracle_builds/<timestamp>)")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        LOGGER.error("Spec not found: %s", spec_path)
        sys.exit(1)

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        LOGGER.error("%s is not a git repository — the pipeline needs git to diff the build", repo)
        sys.exit(1)

    if not args.skip_build and not args.allow_dirty:
        status = orv._git(repo, "status", "--porcelain").strip()
        if status:
            LOGGER.error("Working tree is not clean — the build diff would mix with existing "
                         "changes. Commit/stash first, or pass --allow-dirty.")
            sys.exit(1)

    out_dir = (Path(args.output) if args.output
               else repo / "oracle_builds" / datetime.now().strftime("%Y%m%d_%H%M%S"))

    print(f"\n{'═' * 60}")
    print("  ORACLE BUILD PIPELINE")
    print(f"  Spec: {spec_path.name}")
    print(f"  Repo: {repo}")
    print(f"  Build: {'skipped' if args.skip_build else 'Ben (Grok Build)'}")
    print(f"  Review: Atlas (Codex {ATLAS_PRESET}), {args.fix_rounds} fix round(s)")
    print("  Gate: Beth (Claude Fable, high effort)")
    print(f"{'═' * 60}\n")

    final_gate = run_pipeline(spec_path, repo, args.fix_rounds, args.skip_build, out_dir)

    status = "APPROVED" if final_gate == "APPROVED" else f"GATE {final_gate}"
    print(f"\n{'═' * 60}\n  PIPELINE COMPLETE — {status} — {out_dir / 'PIPELINE_REPORT.md'}\n{'═' * 60}\n")
    if final_gate != "APPROVED":
        LOGGER.error("Final gate verdict is %s (not APPROVED) — failing closed with non-zero exit.", final_gate)
        sys.exit(1)


if __name__ == "__main__":
    main()
