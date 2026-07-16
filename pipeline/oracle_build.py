"""
Oracle Build Pipeline — spec → build → check → review → final gate, fully automated.

The delivery half of the oracle toolchain. oracle.py polishes a spec; this tool
takes that polished spec and runs it through the build ensemble:

  1. BUILD  — Ben (Grok Build CLI) implements the spec in the target repo
  2. CHECK  — deterministic gate: run the repo's tests and scan for protected-path
              edits; failures route straight back to Ben, so no reviewer tokens
              are spent on code that is already known-red
  3. REVIEW — Atlas (Codex CLI, gpt-5.6-terra @ high effort) reviews the diff
  4. FIX    — if CHECK or Atlas fails the round, Ben fixes the findings (looped);
              PIPELINE_STATE.md carries each round's record forward so dismissed
              findings are not re-litigated round after round
  5. GATE   — Beth (Claude Fable, high effort) rules against the spec, the final
              diff, AND the deterministic check evidence: APPROVED / CHANGES
              REQUIRED / REJECTED. Failing checks can never gate APPROVED.

Protected paths come from two sources: a `## Never touch` section in the spec
(bullet list of glob patterns) and a `.oracle_protected` file at the target
repo root (one glob per line, `#` comments).

NOTE: the build/fix stages run Grok Build unattended with tool execution
auto-approved (Joe authorized this 2026-07-13). Guardrails: requires a clean
working tree (unless --allow-dirty), never commits or pushes, Codex review is
read-only — a bad build is bounded to uncommitted changes in one repo.

Usage:
    py oracle_build.py FINAL_SPEC.md --repo D:/BoundState/boundstate_mira
    py oracle_build.py spec.md --fix-rounds 2                # allow 2 fix cycles
    py oracle_build.py spec.md --check-cmd "pytest tests -q" # explicit test gate
    py oracle_build.py spec.md --check-cmd none              # disable the test gate
    py oracle_build.py spec.md --skip-build                  # review+gate existing changes
    py oracle_build.py spec.md --allow-dirty                 # don't require clean tree

Requires: grok CLI, codex CLI, ANTHROPIC_API_KEY (falls back to registry).
Shares its plumbing with oracle_review.py (same directory).
"""
__safety_critical__: bool = False

import argparse
import fnmatch
import io
import logging
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

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
CHECK_TIMEOUT_S = 1200    # deterministic test command
CHECK_OUTPUT_CAP = 8000   # chars of test output kept (tail — pytest prints failures last)
STATE_ENTRY_CAP = 6000    # chars per PIPELINE_STATE.md entry (bounds context growth)
ATLAS_PRESET = "terra-high"
PROTECTED_FILE = ".oracle_protected"

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
your judgment call. Never relax, skip, or delete a test to make a finding
go away, and never swallow errors to silence one.

Do NOT git commit or push. When finished, print a fix summary as your final
message: findings addressed (with what you changed), and findings dismissed (with why)."""

CHECK_FIX_PROMPT = """You are Ben, BoundState's implementation engineer (Grok Build).

You previously implemented a spec in this repository. The pipeline's
deterministic checks (test run and/or protected-path scan) FAILED. The check
report is in the file at: {check_path}
The original spec is at: {spec_path}

Fix the failures:
- Failing tests: fix the code. If the test itself is wrong against the spec,
  fix the test and say so explicitly. NEVER relax, skip, or delete a test just
  to make it pass, and never swallow errors to silence a failure.
- Protected-path violations: revert every change to those paths (`git checkout
  -- <path>` for tracked files; delete new files you created there). Protected
  paths are outside this build's authority no matter what the spec seems to
  need — if that makes part of the spec unimplementable, say so in your summary.

Do NOT git commit or push. When finished, print a fix summary as your final
message: what was failing, what you changed, anything you could not fix."""

GATE_SYSTEM = """You are Beth, BoundState's CTO, performing the FINAL release gate on an
implementation that was built by Grok Build and reviewed by Codex.

Judge the final diff against the SPEC — not just against generic code quality:
- Does the implementation actually satisfy the spec's requirements? List any gaps.
- Were the reviewer's Critical/High findings genuinely fixed, or papered over?
- Correctness: any remaining real bugs with concrete failure scenarios.
- Deterministic check evidence (test run + protected-path scan) is included.
  Failing checks are disqualifying — never APPROVED over red evidence. If test
  evidence was skipped ("no tests collected/detected"), APPROVED requires the
  spec to plainly have no testable behavior; say so explicitly if you rely on that.
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
NEVER_TOUCH_RE = re.compile(r"^#{1,6}\s*never\s+touch\b.*$", re.IGNORECASE | re.MULTILINE)


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


def final_gate_verdict(gate_output: str, checks_ok: bool) -> str:
    """Beth's verdict, clamped by deterministic evidence: red checks can never
    ship, no matter how persuasive the prose. REJECTED passes through — it is
    already more severe than the clamp."""
    verdict = parse_gate_verdict(gate_output)
    if not checks_ok and verdict == "APPROVED":
        LOGGER.warning("Gate said APPROVED but deterministic checks failed — "
                       "clamping to CHANGES REQUIRED")
        return "CHANGES REQUIRED"
    return verdict


# ── Small rendering helpers ─────────────────────────────────────────────────

def _tail(text: str, cap: int) -> str:
    """Keep the last `cap` chars of text (failures print last in test output)."""
    if len(text) <= cap:
        return text
    return f"[... {len(text) - cap} chars truncated ...]\n{text[-cap:]}"


def _banner(title: str, body: str, char: str = "─") -> str:
    line = char * 60
    return f"\n{line}\n  {title}\n{line}\n{body}\n"


class PipelineState:
    """Round-by-round record carried across fix rounds and into the gate.

    Each Atlas round previously re-reviewed the diff blind: findings Ben had
    already dismissed-with-reason could be re-raised and re-litigated every
    round. This record is appended to every review request and to the gate
    input so later rounds argue against the stated reasons, not from scratch.
    Written to disk after every entry so a crashed or watched run still shows
    live state.
    """

    def __init__(self, path: Path, entry_cap: int = STATE_ENTRY_CAP) -> None:
        self.path = path
        self.entry_cap = entry_cap
        self.entries: list[tuple[str, str]] = []

    def add(self, title: str, body: str) -> None:
        self.entries.append((title, _tail(body.strip(), self.entry_cap)))
        self.path.write_text(self.render() + "\n", encoding="utf-8")

    def render(self) -> str:
        if not self.entries:
            return "(no rounds recorded yet)"
        parts = ["# Pipeline State — round-by-round record", ""]
        for title, body in self.entries:
            parts += [f"## {title}", "", body, ""]
        return "\n".join(parts).rstrip()


# ── Protected paths (deterministic scope enforcement) ───────────────────────

def parse_never_touch(spec_text: str) -> list[str]:
    """Extract glob patterns from the spec's `## Never touch` section.

    Bullets are read until the next markdown heading. Backticked spans are
    taken verbatim; bare tokens count only if they look like a path (contain
    `/`, `*`, or `.`) so prose bullets ("The session cookie format.") don't
    become junk patterns.
    """
    m = NEVER_TOUCH_RE.search(spec_text)
    if not m:
        return []
    section = spec_text[m.end():]
    stop = re.search(r"^#{1,6}\s", section, re.MULTILINE)
    if stop:
        section = section[:stop.start()]
    patterns: list[str] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith(("-", "*")):
            continue
        body = line.lstrip("-*").strip()
        spans = [s.strip() for s in re.findall(r"`([^`]+)`", body) if s.strip()]
        if spans:
            patterns.extend(spans)
        elif body:
            token = body.split()[0].rstrip(".,;:")
            if any(c in token for c in "/*."):
                patterns.append(token)
    return list(dict.fromkeys(patterns))


def load_protected_patterns(repo: Path, spec_text: str) -> list[str]:
    """Protected patterns = spec `## Never touch` + repo `.oracle_protected`."""
    patterns = parse_never_touch(spec_text)
    protected_file = repo / PROTECTED_FILE
    if protected_file.is_file():
        for raw in protected_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line.split(" #", 1)[0].strip())
    return list(dict.fromkeys(p for p in patterns if p))


def touched_paths(repo: Path) -> list[str]:
    """Paths the build touched: tracked changes vs HEAD + untracked files.

    Pipeline artifacts and bytecode are excluded — the pipeline itself writes
    into <repo>/oracle_builds/, and that must never read as a violation.
    """
    tracked = orv._git(repo, "diff", "--name-only", "HEAD").splitlines()
    untracked = orv._git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    paths: list[str] = []
    for raw in tracked + untracked:
        p = raw.strip().replace("\\", "/")
        if not p:
            continue
        if (p.startswith(("oracle_builds/", "oracle_reviews/"))
                or "__pycache__" in p or p.endswith((".pyc", ".pyo"))):
            continue
        paths.append(p)
    return list(dict.fromkeys(paths))


def protected_violations(repo: Path, patterns: list[str]) -> list[tuple[str, str]]:
    """Return (touched_path, matching_pattern) pairs. `dir` and `dir/` patterns
    also match everything beneath them; fnmatch `*` crosses `/`, which errs
    toward protection."""
    if not patterns:
        return []
    hits: list[tuple[str, str]] = []
    for path in touched_paths(repo):
        for pat in patterns:
            base = pat.replace("\\", "/").rstrip("/")
            if fnmatch.fnmatchcase(path, base) or fnmatch.fnmatchcase(path, base + "/*"):
                hits.append((path, pat))
                break
    return hits


# ── Deterministic check stage ───────────────────────────────────────────────

def resolve_check_cmd(repo: Path, check_cmd: str) -> tuple[list[str] | None, bool]:
    """Resolve --check-cmd into an argv. Returns (argv | None, auto_mode).

    "auto" detects pytest (tests/ dir, else a pytest-capable config file) and
    degrades to None — checks skipped but flagged to the gate — when nothing
    is detected or pytest isn't installed. "none" disables explicitly. Anything
    else must resolve on PATH: an explicit check command that can't run is a
    hard error, never a silent skip.
    """
    choice = check_cmd.strip()
    if choice.lower() == "none":
        return None, False
    if choice.lower() == "auto":
        if (repo / "tests").is_dir():
            args = ["tests", "-q"]
        elif any((repo / f).is_file() for f in ("pytest.ini", "pyproject.toml", "setup.cfg")):
            args = ["-q"]
        else:
            return None, True
        base = orv._resolve_cmd("pytest")
        if not base:
            LOGGER.warning("auto check: pytest not found on PATH — test check will be skipped")
            return None, True
        return base + args, True
    argv = shlex.split(choice, posix=(os.name != "nt"))
    base = orv._resolve_cmd(argv[0])
    if not base:
        raise RuntimeError(f"--check-cmd not found on PATH: {argv[0]}")
    return base + argv[1:], False


def _run_check_cmd(argv: list[str], repo: Path, timeout: int) -> tuple[int | None, str]:
    """Run the check command in the target repo. Returns (exit code | None on
    timeout, combined output). Never raises — a check that cannot run is a
    failed check, not a crashed pipeline."""
    try:
        result = subprocess.run(
            argv, cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"[TIMEOUT] check command exceeded {timeout}s"
    except OSError as exc:
        return 127, f"[ERROR] could not execute check command: {exc}"
    output = (result.stdout or "") + (f"\n{result.stderr}" if result.stderr else "")
    return result.returncode, output.strip()


def run_checks(
    repo: Path,
    out_dir: Path,
    round_num: int,
    check_argv: list[str] | None,
    check_auto: bool,
    protected: list[str],
) -> tuple[bool, str, Path]:
    """Deterministic CHECK stage: protected-path scan + test run.

    Returns (ok, report_markdown, report_path). Fails closed: a timed-out or
    erroring test command is a FAIL, never a skip. In auto mode a repo where
    pytest collects nothing is a warning rather than a FAIL (a docs-only spec
    is legitimate — the gate must justify it); with an explicit --check-cmd,
    any non-zero exit is a FAIL.
    """
    lines: list[str] = [f"# Deterministic Checks — Round {round_num}", ""]
    ok = True

    violations = protected_violations(repo, protected)
    if violations:
        ok = False
        lines += ["## Protected paths — FAIL", ""]
        lines += [f"- `{path}` matches protected pattern `{pat}`" for path, pat in violations]
        lines += ["", "These paths are outside the build's authority. Revert every change to them.", ""]
    elif protected:
        lines += ["## Protected paths — PASS", "",
                  f"{len(protected)} pattern(s) checked; no protected path touched.", ""]
    else:
        lines += ["## Protected paths — SKIPPED", "",
                  f"No `## Never touch` section in the spec and no {PROTECTED_FILE} in the repo.", ""]

    if check_argv is None:
        reason = "auto mode: no test setup detected" if check_auto else "disabled via --check-cmd none"
        lines += ["## Tests — SKIPPED", "", reason, ""]
    else:
        code, output = _run_check_cmd(check_argv, repo, CHECK_TIMEOUT_S)
        cmd_str = " ".join(check_argv)
        if code == 0:
            lines += ["## Tests — PASS", "", f"`{cmd_str}` exited 0.", "",
                      "```", _tail(output, CHECK_OUTPUT_CAP), "```", ""]
        elif code == 5 and check_auto:
            # pytest exit 5 = no tests collected. Only auto-detected commands
            # get this leniency; an explicit --check-cmd was asked to pass.
            lines += ["## Tests — NO TESTS COLLECTED (warning)", "",
                      f"`{cmd_str}` exited 5 (pytest: no tests collected). "
                      "The gate must justify shipping without test evidence.", ""]
        else:
            ok = False
            exit_desc = f"exit code {code}" if code is not None else f"TIMEOUT after {CHECK_TIMEOUT_S}s"
            lines += [f"## Tests — FAIL ({exit_desc})", "", f"Command: `{cmd_str}`", "",
                      "```", _tail(output, CHECK_OUTPUT_CAP), "```", ""]

    lines += [f"RESULT: {'PASS' if ok else 'FAIL'}"]
    report = "\n".join(lines)
    path = out_dir / f"check_round{round_num}.md"
    path.write_text(report + "\n", encoding="utf-8")
    return ok, report, path


# ── Stage runners ───────────────────────────────────────────────────────────

def run_grok(prompt: str, repo: Path, timeout: int) -> str:
    """Run a Grok Build pass with write access to the repo (auto-approved tools)."""
    base = orv._resolve_cmd("grok")
    if not base:
        raise RuntimeError("grok CLI not found on PATH")
    return orv._run_cli(
        base + ["-p", prompt, "--output-format", "plain", "--always-approve",
                "--max-turns", "200"],
        cwd=repo, timeout=timeout)


def run_atlas_review(
    spec_path: Path, repo: Path, out_dir: Path, round_num: int, *, state_md: str = "",
) -> tuple[str, Path]:
    """Codex (terra-high) reviews the current diff against the spec. Returns (review, path)."""
    # Atlas has repo access via sandbox; truncation is a warning only.
    label, diff = orv.collect_diff(repo, base=None, files=None)
    prior = ""
    if state_md:
        prior = (
            f"## Prior Rounds (pipeline state)\n\n{state_md}\n\n"
            "Findings the implementer dismissed carry his stated reason above. Do not\n"
            "re-raise a dismissed finding unless you can rebut that reason — and if you\n"
            "re-raise one, quote the reason and say why it is wrong.\n\n"
        )
    request_text = (
        f"# Code Review Request (Build Pipeline, round {round_num})\n\n"
        f"**Repo:** {repo}\n**Scope:** {label}\n\n"
        f"## The Spec This Diff Implements\n\nRead it at: {spec_path}\n\n"
        f"## Instructions\n\nReview the diff BOTH for correctness and for whether it "
        f"actually implements the spec. Flag spec requirements the diff misses.\n\n"
        f"{orv.FINDINGS_FORMAT}\n\n"
        f"{prior}"
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


def run_fix_round(
    prompt: str,
    repo: Path,
    out_dir: Path,
    round_num: int,
    reason: str,
    state: PipelineState,
    emit: Callable[[str], None],
) -> None:
    """One Ben fix pass; logs the fix and records his summary in the state file."""
    emit(f"═══ Stage 4: FIX round {round_num} — Ben addresses {reason} ═══")
    fix_log = run_grok(prompt, repo, BUILD_TIMEOUT_S)
    (out_dir / f"fix_log_round{round_num}.md").write_text(
        f"# Fix Log — Round {round_num} ({reason})\n\n{fix_log}\n", encoding="utf-8")
    state.add(f"Round {round_num} — Ben fix summary ({reason})", fix_log)
    print(_banner(f"BEN — FIX ROUND {round_num} ({reason.upper()})", fix_log))
    emit(f"BEN FIX ROUND {round_num} ({reason}) — see fix_log_round{round_num}.md")


def _pipeline_report(
    spec_path: Path,
    repo: Path,
    reviews: list[str],
    last_verdict: str,
    checks_ok: bool,
    gate_verdict: str,
    gate: str,
) -> str:
    """Render PIPELINE_REPORT.md. When Beth's APPROVED was clamped by red
    checks, a canonical verdict section is prepended so every downstream
    parser (server UI included) reads the clamped verdict, not her original."""
    clamped = not checks_ok and parse_gate_verdict(gate) == "APPROVED"
    body = gate
    clamp_note = ""
    if clamped:
        clamp_note = " (clamped from APPROVED — deterministic checks failed)"
        body = ("## Final Verdict\nCHANGES REQUIRED — pipeline clamp: deterministic "
                "checks failed. Beth's original gate (APPROVED) follows below.\n\n" + gate)
    atlas_line = (f"{len(reviews)} (last verdict: {last_verdict})" if reviews
                  else "0 (checks never passed — no review ran)")
    return (
        f"# Oracle Build Pipeline Report\n\n"
        f"**Spec:** {spec_path}\n**Repo:** {repo}\n"
        f"**Date:** {datetime.now().isoformat()}\n"
        f"**Checks:** {'PASS' if checks_ok else 'FAIL'} (final round — see check_round*.md)\n"
        f"**Atlas rounds:** {atlas_line}\n"
        f"**Final Gate:** {gate_verdict}{clamp_note}\n\n"
        f"{body}\n"
    )


# ── Orchestration ───────────────────────────────────────────────────────────

def run_pipeline(
    spec_path: Path,
    repo: Path,
    fix_rounds: int,
    skip_build: bool,
    out_dir: Path,
    *,
    progress: Callable[[str], None] | None = None,
    check_cmd: str = "auto",
) -> str:
    """Execute build → check → review → fix loop → Fable final gate.

    Returns the final gate verdict: APPROVED / CHANGES REQUIRED / REJECTED.
    Deterministic checks (test run + protected-path scan) run before every
    review round: red checks route straight back to Ben without spending
    reviewer tokens, and the gate can never return APPROVED over failing checks.

    If `progress` is provided (for web UI), stage headers and key summaries
    are also emitted to it. CLI behavior is unchanged.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_text = spec_path.read_text(encoding="utf-8")
    check_argv, check_auto = resolve_check_cmd(repo, check_cmd)
    protected = load_protected_patterns(repo, spec_text)
    state = PipelineState(out_dir / "PIPELINE_STATE.md")

    def emit(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass
        # Always log for CLI + file capture
        LOGGER.info(msg)

    emit(f"Checks: {' '.join(check_argv) if check_argv else 'none'}"
         f"{' (auto)' if check_auto else ''} | protected patterns: {len(protected)}")

    # ── Stage 1: Build ──────────────────────────────────────────────────
    if skip_build:
        emit("═══ Stage 1: BUILD skipped (--skip-build) ═══")
        state.add("Build", "Skipped (--skip-build) — reviewing existing working-tree changes.")
    else:
        emit("═══ Stage 1: BUILD — Ben (Grok Build) implements the spec ═══")
        build_log = run_grok(BUILD_PROMPT.format(spec_path=spec_path.resolve()),
                             repo, BUILD_TIMEOUT_S)
        (out_dir / "build_log.md").write_text(f"# Build Log (Grok)\n\n{build_log}\n",
                                              encoding="utf-8")
        state.add("Build — Ben's summary", build_log)
        print(_banner("BEN — BUILD SUMMARY", build_log))
        emit("BEN BUILD SUMMARY (see build_log.md)")

    # ── Stages 2/3/4: check → review → fix loop ─────────────────────────
    # Invariant: a fix pass only runs when round_num <= fix_rounds, so every
    # fix is followed by a fresh CHECK — checks_ok/check_report are always
    # current (post-last-write) when the loop exits.
    reviews: list[str] = []
    verdict = "FIX FIRST"
    checks_ok = False
    check_report = "[checks did not run]"
    for round_num in range(1, fix_rounds + 2):  # initial pass + one per fix round
        emit(f"═══ Stage 2: CHECK round {round_num} — tests + protected paths ═══")
        checks_ok, check_report, check_path = run_checks(
            repo, out_dir, round_num, check_argv, check_auto, protected)
        state.add(f"Round {round_num} — deterministic checks",
                  "PASS" if checks_ok else check_report)
        print(_banner(f"CHECKS — ROUND {round_num} → {'PASS' if checks_ok else 'FAIL'}",
                      check_report))
        emit(f"CHECKS ROUND {round_num} → {'PASS' if checks_ok else 'FAIL'} (see {check_path.name})")

        if not checks_ok:
            if round_num > fix_rounds:
                emit("Fix rounds exhausted with failing checks — proceeding to gate")
                break
            # Red checks are the cheapest findings there are: send them straight
            # back to Ben instead of spending Atlas tokens on known-broken code.
            run_fix_round(
                CHECK_FIX_PROMPT.format(check_path=check_path.resolve(),
                                        spec_path=spec_path.resolve()),
                repo, out_dir, round_num, "failing checks", state, emit)
            continue

        emit(f"═══ Stage 3: REVIEW round {round_num} — Atlas (Codex {ATLAS_PRESET}) ═══")
        review, review_path = run_atlas_review(spec_path, repo, out_dir, round_num,
                                               state_md=state.render())
        reviews.append(f"### Atlas Review — Round {round_num}\n{review}")
        verdict = parse_verdict(review)
        state.add(f"Round {round_num} — Atlas verdict", verdict)
        print(_banner(f"ATLAS — REVIEW ROUND {round_num} → {verdict}", review))
        emit(f"ATLAS REVIEW ROUND {round_num} → {verdict} (see atlas_review_round{round_num}.md)")

        if verdict == "SHIP":
            break
        if round_num > fix_rounds:
            emit(f"Fix rounds exhausted with verdict {verdict} — proceeding to gate")
            break

        run_fix_round(
            FIX_PROMPT.format(review_path=review_path.resolve(),
                              spec_path=spec_path.resolve()),
            repo, out_dir, round_num, "review findings", state, emit)

    # ── Stage 5: Fable final gate ───────────────────────────────────────
    emit("═══ Stage 5: FINAL GATE — Beth (Claude Fable, high effort) ═══")
    try:
        _, final_diff = orv.collect_diff(repo, base=None, files=None, strict=True)
    except ValueError as exc:
        # Fail closed: Beth must see the full diff. Emit a gate failure verdict.
        gate = (f"[GATE INPUT ERROR] {exc}\n\n## Final Verdict\nCHANGES REQUIRED\n\n"
                f"Diff too large for safe final gate without repository context.")
        report = _pipeline_report(spec_path, repo, reviews, verdict, checks_ok,
                                  "CHANGES REQUIRED", gate)
        (out_dir / "PIPELINE_REPORT.md").write_text(report, encoding="utf-8")
        print(_banner("BETH (FABLE) — FINAL GATE (REFUSED INPUT)", gate, "═"))
        emit("BETH FINAL GATE REFUSED — diff exceeded gate capacity")
        return "CHANGES REQUIRED"  # fail closed; final_diff is unbound past here

    review_history = ("\n\n".join(reviews) if reviews
                      else "[no Atlas review completed — deterministic checks never passed]")
    gate = orv._call_anthropic(
        GATE_SYSTEM,
        f"## The Spec\n\n{spec_text}\n\n"
        f"## The Final Diff\n\n{final_diff}\n\n"
        f"## Deterministic Check Evidence (final round)\n\n{check_report}\n\n"
        f"## Pipeline State (round-by-round record)\n\n{state.render()}\n\n"
        f"## Review History (Atlas, chronological)\n\n{review_history}\n\n"
        f"## Your Task\nPerform the final release gate.",
        timeout=1800,  # generous for high-effort Fable gate; still bounded
    )

    gate_verdict = final_gate_verdict(gate, checks_ok)
    report = _pipeline_report(spec_path, repo, reviews, verdict, checks_ok, gate_verdict, gate)
    (out_dir / "PIPELINE_REPORT.md").write_text(report, encoding="utf-8")
    print(_banner(f"BETH (FABLE) — FINAL GATE → {gate_verdict}", gate, "═"))
    emit(f"BETH FINAL GATE → {gate_verdict} (see PIPELINE_REPORT.md)")
    emit(f"Pipeline artifacts saved to {out_dir}")
    return gate_verdict


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Oracle Build Pipeline — spec → Grok builds → checks run → Codex reviews → Fable gates")
    parser.add_argument("spec", help="Path to the polished spec (e.g. FINAL_SPEC.md from oracle.py)")
    parser.add_argument("--repo", default=".", help="Target repo (default: cwd)")
    parser.add_argument("--fix-rounds", type=int, default=1,
                        help="Max Ben fix cycles after a failed check or non-SHIP review (default: 1)")
    parser.add_argument("--check-cmd", default="auto",
                        help='Deterministic test command run before each review round '
                             '(default: auto — detect pytest; "none" disables)')
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip the build stage; check+review+gate the existing working-tree changes")
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

    try:
        check_argv, _ = resolve_check_cmd(repo, args.check_cmd)
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
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
    print(f"  Checks: {' '.join(check_argv) if check_argv else 'none detected/disabled'}")
    print(f"  Review: Atlas (Codex {ATLAS_PRESET}), {args.fix_rounds} fix round(s)")
    print("  Gate: Beth (Claude Fable, high effort)")
    print(f"{'═' * 60}\n")

    final_gate = run_pipeline(spec_path, repo, args.fix_rounds, args.skip_build, out_dir,
                              check_cmd=args.check_cmd)

    status = "APPROVED" if final_gate == "APPROVED" else f"GATE {final_gate}"
    print(f"\n{'═' * 60}\n  PIPELINE COMPLETE — {status} — {out_dir / 'PIPELINE_REPORT.md'}\n{'═' * 60}\n")
    if final_gate != "APPROVED":
        LOGGER.error("Final gate verdict is %s (not APPROVED) — failing closed with non-zero exit.", final_gate)
        sys.exit(1)


if __name__ == "__main__":
    main()
