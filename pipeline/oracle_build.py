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
import functools
import io
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
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
# Ben's model pin: --ben-model flag > ORACLE_BEN_MODEL env > grok CLI default.
# Atlas and Beth are already pinned (ATLAS_PRESETS, orv.BETH_MODEL); without
# this, Ben silently runs on whatever the local grok config says.
BEN_MODEL_ENV = "ORACLE_BEN_MODEL"

BUILD_PROMPT = """You are Ben, BoundState's implementation engineer (Grok Build).

Implement the specification in the file at: {spec_path}

Rules:
- Work only in this repository. Follow the existing code style and structure.
- BoundState standards: Python type hints everywhere, Pydantic extra="forbid",
  no bare except, logging not print, docstrings on public classes/functions.
- Write tests alongside the implementation where the spec implies testable
  behavior. The pipeline measures DIFF COVERAGE — the fraction of lines you
  add that your tests actually execute — and may fail the round below its
  floor. Write real tests, never assertion-free padding.
- Do not add dependencies without stating the justification in your build summary.
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
- Insufficient diff coverage: write real tests for the uncovered lines listed
  in the report. Never inflate coverage by deleting code or writing
  assertion-free tests.
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
- Deterministic check evidence (test run, diff coverage, protected-path scan)
  is included. Failing checks are disqualifying — never APPROVED over red
  evidence. If test evidence was skipped ("no tests collected/detected"),
  APPROVED requires the spec to plainly have no testable behavior; say so
  explicitly if you rely on that.
- The check report's "Platform floor" section says whether the repo ships CI
  workflows and a test suite. A platform build missing either is a gap —
  treat it as disqualifying unless the spec explicitly says otherwise.
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


def clamp_reason(
    gate_output: str, checks_ok: bool, review_verdict: str | None = None
) -> str | None:
    """Why an APPROVED gate must be clamped, or None if it may stand.

    Single source of truth for both the verdict and the report, so the rendered
    header can never disagree with the verdict the pipeline returns.
    """
    if parse_gate_verdict(gate_output) != "APPROVED":
        return None
    if not checks_ok:
        return "deterministic checks failed"
    if review_verdict and review_verdict.upper() != "SHIP":
        return (f"reviewer's final verdict was {review_verdict.upper()} "
                "and was never resolved")
    return None


def final_gate_verdict(
    gate_output: str, checks_ok: bool, review_verdict: str | None = None
) -> str:
    """Beth's verdict, clamped by deterministic evidence AND by an unresolved
    reviewer verdict. Neither red checks nor an unaddressed FIX FIRST can ship,
    no matter how persuasive the prose. REJECTED passes through — it is already
    more severe than the clamp.

    WHY the review clamp: fix rounds can be exhausted while the reviewer's last
    verdict is still FIX FIRST/BLOCK, and the pipeline then hands the gate the
    very diff the reviewer rejected. Before this clamp only the check channel
    had a deterministic floor, so green tests could launder an unresolved
    reviewer finding. In the 2026-07-29 S1 run three of four residual defects
    were semantic bugs — an inverted `supersedes` gate, an `or` where full
    scope coverage was required, whitespace satisfying required fields — that
    no coverage number can see. A human may still overrule a reviewer, but that
    decision belongs outside the pipeline, not inside an automated gate.
    """
    verdict = parse_gate_verdict(gate_output)
    reason = clamp_reason(gate_output, checks_ok, review_verdict)
    if reason:
        LOGGER.warning("Gate said APPROVED but %s — clamping to CHANGES REQUIRED", reason)
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


# ── Diff coverage (are the lines the build ADDED actually tested?) ─────────

def _is_test_or_artifact(path: str) -> bool:
    """Paths whose coverage is meaningless for the gate: tests themselves,
    pipeline artifacts, bytecode."""
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (p.startswith(("tests/", "oracle_builds/", "oracle_reviews/"))
            or "/tests/" in p or "__pycache__" in p
            or name.startswith("test_") or name == "conftest.py")


def added_py_lines(repo: Path) -> dict[str, set[int]]:
    """Line numbers added to each product .py file in the working tree.

    Tracked changes come from `git diff -U0`; untracked files count in full.
    Test files are excluded — the coverage gate asks whether *product* lines
    are tested, not whether tests cover themselves.
    """
    added: dict[str, set[int]] = {}
    current: str | None = None
    for line in orv._git(repo, "diff", "HEAD", "-U0", "--", "*.py").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            current = None if _is_test_or_artifact(path) else path
        elif line.startswith("@@") and current:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if not m:
                continue
            start, count = int(m.group(1)), int(m.group(2) or "1")
            if count:
                added.setdefault(current, set()).update(range(start, start + count))
    for raw in orv._git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
        path = raw.strip().replace("\\", "/")
        if not path.endswith(".py") or _is_test_or_artifact(path):
            continue
        try:
            n_lines = len((repo / path).read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        if n_lines:
            added.setdefault(path, set()).update(range(1, n_lines + 1))
    return added


def diff_coverage(repo: Path, added: dict[str, set[int]], cov_data: dict,
                  max_gaps: int = 15) -> tuple[float, int, int, list[str]]:
    """(percent, covered, measurable, gap descriptions) for the added lines.

    Measurable = added lines coverage.py considers executable. A changed file
    absent from the coverage report was never imported by any test — its
    non-blank, non-comment added lines all count as uncovered (errs toward
    demanding tests, which is the point of the gate).
    """
    files = {k.replace("\\", "/"): v for k, v in cov_data.get("files", {}).items()}
    covered = measurable = 0
    gaps: list[str] = []
    for path, lines in sorted(added.items()):
        entry = files.get(path)
        if entry is not None:
            executed = set(entry.get("executed_lines", []))
            missing = set(entry.get("missing_lines", []))
            file_measurable = lines & (executed | missing)
            file_covered = lines & executed
            file_missing = sorted(lines & missing)
        else:
            try:
                src = (repo / path).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            file_missing = sorted(
                n for n in lines
                if 0 < n <= len(src) and src[n - 1].strip() and not src[n - 1].lstrip().startswith("#"))
            file_measurable = set(file_missing)
            file_covered = set()
        measurable += len(file_measurable)
        covered += len(file_covered)
        if file_missing and len(gaps) < max_gaps:
            note = "" if entry is not None else " (module never imported by any test)"
            shown = ", ".join(str(n) for n in file_missing[:12])
            more = f" …+{len(file_missing) - 12}" if len(file_missing) > 12 else ""
            gaps.append(f"- `{path}`{note}: uncovered added lines {shown}{more}")
    pct = 100.0 if measurable == 0 else 100.0 * covered / measurable
    return pct, covered, measurable, gaps


def run_coverage_check(repo: Path, out_dir: Path, round_num: int,
                       floor: int) -> tuple[bool, list[str]]:
    """Run pytest under coverage and gate on diff coverage of added lines.

    Fails closed: with a floor set, missing pytest/pytest-cov or an absent
    coverage report is a FAIL with instructions, never a silent skip.

    Runs `<this interpreter> -m pytest` rather than the PATH pytest shim so
    the plugin set is the pipeline's own environment — a PATH pytest from a
    different install may lack pytest-cov even when the pipeline has it.
    """
    json_path = out_dir / f"coverage_round{round_num}.json"
    argv = [sys.executable, "-m", "pytest"] + \
        (["tests"] if (repo / "tests").is_dir() else []) + \
        ["-q", "--cov=.", f"--cov-report=json:{json_path}"]
    code, output = _run_check_cmd(argv, repo, CHECK_TIMEOUT_S)
    if not json_path.is_file():
        return False, [f"## Diff coverage — FAIL (no coverage report, exit {code})", "",
                       "The coverage run produced no report. Ensure pytest-cov is "
                       "installed in the target environment.", "",
                       "```", _tail(output, 2000), "```", ""]
    try:
        cov_data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [f"## Diff coverage — FAIL (unreadable coverage report: {exc})", ""]
    added = added_py_lines(repo)
    pct, covered, measurable, gaps = diff_coverage(repo, added, cov_data)
    if measurable == 0:
        return True, ["## Diff coverage — PASS (nothing to measure)", "",
                      "No new executable product lines in this diff.", ""]
    ok = pct >= floor
    header = (f"## Diff coverage — {'PASS' if ok else 'FAIL'} "
              f"({pct:.1f}% of {measurable} added executable lines; floor {floor}%)")
    lines = [header, ""]
    if gaps:
        lines += gaps + [""]
    if not ok:
        lines += ["Write real tests for the uncovered lines above. Deleting code or "
                  "adding assertion-free tests to move this number is a gate offense.", ""]
    return ok, lines


# ── Deterministic check stage ───────────────────────────────────────────────

# Appears in a check report when the failure is the OPERATOR'S environment
# (missing packages, broken tooling), not the build's code. run_pipeline halts
# to the operator on this marker instead of spending Ben fix rounds — a
# builder "fixing" the environment mutates the machine or deletes files at
# worst, and burns tokens at best.
ENV_FAIL_MARKER = "RESULT: FAIL (ENVIRONMENT)"

# Top-level packages of this repo: a missing module from OUTSIDE this set is
# an environment problem; a missing module INSIDE it is a build defect (e.g.
# Ben typo'd an import) and must still route to Ben.
_REPO_TOP_LEVELS = ("oracle", "hearth", "pipeline", "sentinel", "eval", "tests", "server")


def _looks_like_env_failure(output: str) -> bool:
    """Classify check-command output as environment failure vs code failure."""
    if 'requires "' in output and "to be installed" in output:
        return True  # fastapi-style "Form data requires "python-multipart"..."
    if "is not recognized as an internal or external command" in output \
            or "command not found" in output:
        return True
    for name in re.findall(r"No module named '([^']+)'", output):
        if name.split(".")[0] not in _REPO_TOP_LEVELS:
            return True
    return False


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
    if os.name == "nt":
        # WHY: non-posix shlex preserves surrounding quotes inside tokens, so a
        # quoted payload like -c "import x" reaches Python as the string
        # literal '"import x"' — which executes as a no-op and exits 0. A
        # false PASS from quoting semantics, observed live on the first
        # Windows run. Strip symmetric outer double quotes so quoted args
        # mean the same thing on both platforms.
        argv = [t[1:-1] if len(t) >= 2 and t[0] == '"' and t[-1] == '"' else t
                for t in argv]
    base = orv._resolve_cmd(argv[0])
    if not base:
        raise RuntimeError(f"--check-cmd not found on PATH: {argv[0]}")
    return base + argv[1:], False


# WHY: interpreter-shutdown callbacks can raise AFTER the test run finishes —
# on Windows, pytest's tmpdir cleanup hits PermissionError removing
# `Temp\pytest-of-<user>\pytest-current`. Python prints "Exception ignored in
# atexit callback" plus a traceback, which lands at the very END of the
# captured output, which is exactly where _tail() looks. The exit code is
# unaffected (the exception is ignored), so this never changes PASS/FAIL — but
# left in, the traceback can push real pytest failures out of the tail cap and
# leaves the check evidence Atlas and Beth read ending on a traceback for a run
# that actually passed. This is an evidence-fidelity fix, not a verdict fix.
_ATEXIT_NOISE_RE = re.compile(r"\n?Exception ignored in atexit callback.*\Z", re.DOTALL)


def _strip_atexit_noise(output: str) -> str:
    """Drop trailing interpreter-shutdown tracebacks from captured output.

    Only strips from the first such marker to end-of-output — atexit callbacks
    run after everything meaningful, so nothing recoverable follows them.
    """
    return _ATEXIT_NOISE_RE.sub("", output)


def _run_check_cmd(argv: list[str], repo: Path, timeout: int) -> tuple[int | None, str]:
    """Run the check command in the target repo. Returns (exit code | None on
    timeout, combined output). Never raises — a check that cannot run is a
    failed check, not a crashed pipeline.

    The verdict is taken from the exit code alone; captured output is evidence
    only. Trailing atexit noise is stripped so the evidence ends on the test
    runner's own summary.
    """
    try:
        result = subprocess.run(
            argv, cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"[TIMEOUT] check command exceeded {timeout}s"
    except OSError as exc:
        return 127, f"[ERROR] could not execute check command: {exc}"
    output = (result.stdout or "") + (f"\n{result.stderr}" if result.stderr else "")
    return result.returncode, _strip_atexit_noise(output).strip()


def run_checks(
    repo: Path,
    out_dir: Path,
    round_num: int,
    check_argv: list[str] | None,
    check_auto: bool,
    protected: list[str],
    *,
    coverage_floor: int = 0,
) -> tuple[bool, str, Path]:
    """Deterministic CHECK stage: protected-path scan + test run + optional
    diff-coverage gate + platform-floor report.

    Returns (ok, report_markdown, report_path). Fails closed: a timed-out or
    erroring test command is a FAIL, never a skip. In auto mode a repo where
    pytest collects nothing is a warning rather than a FAIL (a docs-only spec
    is legitimate — the gate must justify it); with an explicit --check-cmd,
    any non-zero exit is a FAIL.
    """
    lines: list[str] = [f"# Deterministic Checks — Round {round_num}", ""]
    ok = True
    environment_failure = False

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
            env_note = " — ENVIRONMENT: missing packages or broken tooling; operator action required" \
                if _looks_like_env_failure(output) else ""
            exit_desc = f"exit code {code}" if code is not None else f"TIMEOUT after {CHECK_TIMEOUT_S}s"
            lines += [f"## Tests — FAIL ({exit_desc}{env_note})", "", f"Command: `{cmd_str}`", "",
                      "```", _tail(output, CHECK_OUTPUT_CAP), "```", ""]
            if env_note:
                environment_failure = True

    if coverage_floor > 0:
        cov_ok, cov_lines = run_coverage_check(repo, out_dir, round_num, coverage_floor)
        ok = ok and cov_ok
        lines += cov_lines
        if not cov_ok and _looks_like_env_failure("\n".join(cov_lines)):
            environment_failure = True

    # Informational only — the gate judges it (a platform build without CI or
    # tests is a gap), but it never reds a round by itself.
    workflows_dir = repo / ".github" / "workflows"
    has_ci = workflows_dir.is_dir() and any(workflows_dir.glob("*.y*ml"))
    lines += ["## Platform floor — INFO", "",
              f"- CI workflows (.github/workflows/): {'present' if has_ci else 'MISSING'}",
              f"- tests/ directory: {'present' if (repo / 'tests').is_dir() else 'MISSING'}", ""]

    if ok:
        lines += ["RESULT: PASS"]
    elif environment_failure:
        lines += [ENV_FAIL_MARKER]
    else:
        lines += ["RESULT: FAIL"]
    report = "\n".join(lines)
    path = out_dir / f"check_round{round_num}.md"
    path.write_text(report + "\n", encoding="utf-8")
    return ok, report, path


# ── Stage runners ───────────────────────────────────────────────────────────

def resolve_ben_model(cli_value: str | None) -> str | None:
    """Ben's model pin: explicit flag wins, then ORACLE_BEN_MODEL, then None
    (grok CLI default — the historical behavior)."""
    return cli_value or os.environ.get(BEN_MODEL_ENV) or None


def _grok_argv(base: list[str], prompt: str, model: str | None) -> list[str]:
    """Argv for a Ben pass. The model pin is appended only when configured;
    verify the flag name against your grok CLI (`grok --help`) if it rejects
    --model."""
    argv = base + ["-p", prompt, "--output-format", "plain", "--always-approve",
                   "--max-turns", "200"]
    if model:
        argv += ["--model", model]
    return argv


def run_grok(prompt: str, repo: Path, timeout: int, model: str | None = None) -> str:
    """Run a Grok Build pass with write access to the repo (auto-approved tools)."""
    base = orv._resolve_cmd("grok")
    if not base:
        raise RuntimeError("grok CLI not found on PATH")
    return orv._run_cli(_grok_argv(base, prompt, model), cwd=repo, timeout=timeout)


def toolchain_line(ben_model: str | None) -> str:
    """Provenance line recording who the three legs are for this run —
    the same model-identity-per-run rule the disposition spec (§16) demands
    of evaluation runs, applied to our own builds."""
    base = orv._resolve_cmd("grok")
    grok_version = "not on PATH"
    if base:
        probe = orv._run_cli(base + ["--version"], cwd=Path.cwd(), timeout=30)
        grok_version = probe.splitlines()[0][:120] if probe and not probe.startswith("[ERROR]") else "version probe failed"
    atlas_model, atlas_effort = orv.ATLAS_PRESETS[ATLAS_PRESET]
    return (f"Ben: grok ({grok_version}), model: {ben_model or 'CLI default — UNPINNED'} | "
            f"Atlas: codex {atlas_model} @ {atlas_effort} | Beth: {orv.BETH_MODEL}")


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


@dataclass(frozen=True)
class PipelineAgents:
    """Injectable stage runners — the dependency seam for orchestration tests.

    Production uses default_agents() (real grok/codex/Anthropic calls); tests
    substitute deterministic fakes so run_pipeline's control flow is testable
    without any agent CLI or API key (repo standard: DI over monkeypatching).
    Signatures match run_grok / run_atlas_review / orv._call_anthropic.
    """
    build: Callable[[str, Path, int], str]
    review: Callable[..., tuple[str, Path]]
    gate: Callable[..., str]


def default_agents(ben_model: str | None = None) -> PipelineAgents:
    """The real production ensemble: Ben (grok), Atlas (codex), Beth (Anthropic).
    With a model pin, Ben's runner is bound to it for build AND fix passes."""
    build = run_grok if ben_model is None else functools.partial(run_grok, model=ben_model)
    return PipelineAgents(build=build, review=run_atlas_review, gate=orv._call_anthropic)


def run_fix_round(
    prompt: str,
    repo: Path,
    out_dir: Path,
    round_num: int,
    reason: str,
    state: PipelineState,
    emit: Callable[[str], None],
    build: Callable[[str, Path, int], str],
) -> None:
    """One Ben fix pass; logs the fix and records his summary in the state file."""
    emit(f"═══ Stage 4: FIX round {round_num} — Ben addresses {reason} ═══")
    fix_log = build(prompt, repo, BUILD_TIMEOUT_S)
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
    """Render PIPELINE_REPORT.md. When Beth's APPROVED was clamped — by red
    checks or by an unresolved reviewer verdict — a canonical verdict section is
    prepended so every downstream parser (server UI included) reads the clamped
    verdict, not her original.

    An unresolved reviewer verdict is additionally surfaced as its own banner
    even when the gate did not say APPROVED, so a FIX FIRST diff is never
    presented as final without the reader being told.
    """
    reason = clamp_reason(gate, checks_ok, last_verdict if reviews else None)
    body = gate
    clamp_note = ""
    if reason:
        clamp_note = f" (clamped from APPROVED — {reason})"
        body = (f"## Final Verdict\nCHANGES REQUIRED — pipeline clamp: {reason}. "
                "Beth's original gate (APPROVED) follows below.\n\n" + gate)
    atlas_line = (f"{len(reviews)} (last verdict: {last_verdict})" if reviews
                  else "0 (checks never passed — no review ran)")
    unresolved = ""
    if reviews and last_verdict.upper() != "SHIP":
        unresolved = (
            f"> **UNRESOLVED REVIEW — the reviewer's final verdict was "
            f"{last_verdict.upper()}, and this diff is the diff they rejected.**\n"
            f"> Fix rounds were exhausted before the reviewer was satisfied. Every\n"
            f"> finding in `atlas_review_round{len(reviews)}.md` should be treated as\n"
            f"> open unless the gate below explicitly adjudicates it. Green\n"
            f"> deterministic checks do not resolve a review finding.\n\n"
        )
    return (
        f"# Oracle Build Pipeline Report\n\n"
        f"**Spec:** {spec_path}\n**Repo:** {repo}\n"
        f"**Date:** {datetime.now().isoformat()}\n"
        f"**Checks:** {'PASS' if checks_ok else 'FAIL'} (final round — see check_round*.md)\n"
        f"**Atlas rounds:** {atlas_line}\n"
        f"**Final Gate:** {gate_verdict}{clamp_note}\n\n"
        f"{unresolved}"
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
    coverage_floor: int = 0,
    ben_model: str | None = None,
    agents: PipelineAgents | None = None,
) -> str:
    """Execute build → check → review → fix loop → Fable final gate.

    Returns the final gate verdict: APPROVED / CHANGES REQUIRED / REJECTED.
    Deterministic checks (test run + protected-path scan) run before every
    review round: red checks route straight back to Ben without spending
    reviewer tokens, and the gate can never return APPROVED over failing checks.

    If `progress` is provided (for web UI), stage headers and key summaries
    are also emitted to it. CLI behavior is unchanged. `agents` overrides the
    stage runners (tests only — production always uses default_agents()).
    """
    ben_model = resolve_ben_model(ben_model)
    agents = agents or default_agents(ben_model=ben_model)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_text = spec_path.read_text(encoding="utf-8")
    check_argv, check_auto = resolve_check_cmd(repo, check_cmd)
    protected = load_protected_patterns(repo, spec_text)
    state = PipelineState(out_dir / "PIPELINE_STATE.md")
    state.add("Toolchain", toolchain_line(ben_model))

    def emit(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass
        # Always log for CLI + file capture
        LOGGER.info(msg)

    emit(f"Checks: {' '.join(check_argv) if check_argv else 'none'}"
         f"{' (auto)' if check_auto else ''} | protected patterns: {len(protected)}"
         f" | coverage floor: {coverage_floor if coverage_floor else 'off'}")

    # ── Stage 1: Build ──────────────────────────────────────────────────
    if skip_build:
        emit("═══ Stage 1: BUILD skipped (--skip-build) ═══")
        state.add("Build", "Skipped (--skip-build) — reviewing existing working-tree changes.")
    else:
        emit("═══ Stage 1: BUILD — Ben (Grok Build) implements the spec ═══")
        build_log = agents.build(BUILD_PROMPT.format(spec_path=spec_path.resolve()),
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
            repo, out_dir, round_num, check_argv, check_auto, protected,
            coverage_floor=coverage_floor)
        state.add(f"Round {round_num} — deterministic checks",
                  "PASS" if checks_ok else check_report)
        print(_banner(f"CHECKS — ROUND {round_num} → {'PASS' if checks_ok else 'FAIL'}",
                      check_report))
        emit(f"CHECKS ROUND {round_num} → {'PASS' if checks_ok else 'FAIL'} (see {check_path.name})")

        if not checks_ok:
            if ENV_FAIL_MARKER in check_report:
                # Environment failures are the operator's, not the build's:
                # routing them to Ben burns tokens at best and mutates the
                # machine or deletes untracked files at worst. Halt fail-closed.
                gate = ("[ENVIRONMENT FAILURE] Deterministic checks failed for environment "
                        "reasons outside the build's authority (missing packages or broken "
                        "tooling).\n\n## Final Verdict\nCHANGES REQUIRED\n\n"
                        f"Fix the environment (see {check_path.name}) and re-run the pipeline. "
                        "No fix rounds were spent and no reviewer was invoked.")
                report = _pipeline_report(spec_path, repo, reviews, verdict, False,
                                          "CHANGES REQUIRED", gate)
                (out_dir / "PIPELINE_REPORT.md").write_text(report, encoding="utf-8")
                print(_banner("PIPELINE HALT — ENVIRONMENT FAILURE (operator action required)",
                              gate, "═"))
                emit("PIPELINE HALTED — environment failure; fix the environment and re-run")
                return "CHANGES REQUIRED"
            if round_num > fix_rounds:
                emit("Fix rounds exhausted with failing checks — proceeding to gate")
                break
            # Red checks are the cheapest findings there are: send them straight
            # back to Ben instead of spending Atlas tokens on known-broken code.
            run_fix_round(
                CHECK_FIX_PROMPT.format(check_path=check_path.resolve(),
                                        spec_path=spec_path.resolve()),
                repo, out_dir, round_num, "failing checks", state, emit, agents.build)
            continue

        emit(f"═══ Stage 3: REVIEW round {round_num} — Atlas (Codex {ATLAS_PRESET}) ═══")
        review, review_path = agents.review(spec_path, repo, out_dir, round_num,
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
            repo, out_dir, round_num, "review findings", state, emit, agents.build)

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
    gate = agents.gate(
        GATE_SYSTEM,
        f"## The Spec\n\n{spec_text}\n\n"
        f"## The Final Diff\n\n{final_diff}\n\n"
        f"## Deterministic Check Evidence (final round)\n\n{check_report}\n\n"
        f"## Pipeline State (round-by-round record)\n\n{state.render()}\n\n"
        f"## Review History (Atlas, chronological)\n\n{review_history}\n\n"
        f"## Your Task\nPerform the final release gate.",
        timeout=1800,  # generous for high-effort Fable gate; still bounded
    )

    # `verdict` is the reviewer's last word; pass it so an unresolved FIX FIRST
    # clamps APPROVED exactly as red checks do. Only meaningful when a review
    # actually ran — no reviews means no reviewer finding to be unresolved.
    gate_verdict = final_gate_verdict(gate, checks_ok, verdict if reviews else None)
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
    parser.add_argument("--coverage-floor", type=int, default=0,
                        help="Minimum %% diff coverage: lines the build adds must be "
                             "executed by tests (0 disables; 70-85 recommended for "
                             "platform builds; requires pytest-cov in the target env)")
    parser.add_argument("--ben-model", default=None,
                        help=f"Pin Ben's grok model for build+fix passes (falls back to "
                             f"{BEN_MODEL_ENV} env, then the grok CLI's own default). "
                             f"Recorded in PIPELINE_STATE.md either way.")
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
    resolved_ben = resolve_ben_model(args.ben_model)
    print(f"  Build: {'skipped' if args.skip_build else 'Ben (Grok Build)'}"
          + (f" [model: {resolved_ben}]" if resolved_ben else " [model: CLI default — unpinned]"))
    print(f"  Checks: {' '.join(check_argv) if check_argv else 'none detected/disabled'}"
          + (f" | diff coverage ≥{args.coverage_floor}%" if args.coverage_floor else ""))
    print(f"  Review: Atlas (Codex {ATLAS_PRESET}), {args.fix_rounds} fix round(s)")
    print("  Gate: Beth (Claude Fable, high effort)")
    print(f"{'═' * 60}\n")

    final_gate = run_pipeline(spec_path, repo, args.fix_rounds, args.skip_build, out_dir,
                              check_cmd=args.check_cmd, coverage_floor=args.coverage_floor,
                              ben_model=args.ben_model)

    status = "APPROVED" if final_gate == "APPROVED" else f"GATE {final_gate}"
    print(f"\n{'═' * 60}\n  PIPELINE COMPLETE — {status} — {out_dir / 'PIPELINE_REPORT.md'}\n{'═' * 60}\n")
    if final_gate != "APPROVED":
        LOGGER.error("Final gate verdict is %s (not APPROVED) — failing closed with non-zero exit.", final_gate)
        sys.exit(1)


if __name__ == "__main__":
    main()
