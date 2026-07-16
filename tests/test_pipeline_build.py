"""Tests for the build pipeline's deterministic layer (assessment §3.1–§3.3):
the CHECK stage (test run + protected paths), PIPELINE_STATE.md carry-forward,
and the red-checks verdict clamp. No LLM/CLI agents are involved — everything
here is the deterministic plumbing around them."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import oracle_build as ob


# ── Fixtures ────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with one committed file — the pipeline's plumbing is
    git-based, so these tests exercise real git rather than fakes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@boundstate.ai")
    _git(repo, "config", "user.name", "test")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "secret").mkdir()
    (repo / "secret" / "config.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


# ── Never-touch spec parsing ────────────────────────────────────────────────

SPEC_WITH_NEVER_TOUCH = """# Goal
Do the thing.

## Never touch
- `db/migrations/*` already merged.
- Anything under `legacy/`.
- The session cookie format.
- tests/golden/fixtures/*.json — regenerate deliberately only
- `db/migrations/*` (duplicate on purpose)

## Stop if
- More than 3 files change.
"""


def test_parse_never_touch_extracts_globs_and_skips_prose() -> None:
    patterns = ob.parse_never_touch(SPEC_WITH_NEVER_TOUCH)
    assert patterns == ["db/migrations/*", "legacy/", "tests/golden/fixtures/*.json"]
    # prose-only bullet ("The session cookie format.") produced no junk pattern
    assert not any(p.startswith("The") for p in patterns)


def test_parse_never_touch_stops_at_next_heading() -> None:
    patterns = ob.parse_never_touch(SPEC_WITH_NEVER_TOUCH)
    assert not any("3 files" in p or "More" in p for p in patterns)


def test_parse_never_touch_absent_returns_empty() -> None:
    assert ob.parse_never_touch("# Goal\nJust build it.\n") == []


def test_load_protected_patterns_merges_spec_and_repo_file(repo: Path) -> None:
    (repo / ob.PROTECTED_FILE).write_text(
        "# defaults\nsecret/* # signed material\n\nlegacy/ # dup with spec\n",
        encoding="utf-8")
    patterns = ob.load_protected_patterns(repo, SPEC_WITH_NEVER_TOUCH)
    assert "secret/*" in patterns
    assert patterns.count("legacy/") == 1  # deduplicated across sources
    assert "db/migrations/*" in patterns


# ── Touched paths + violations ──────────────────────────────────────────────

def test_touched_paths_excludes_pipeline_artifacts(repo: Path) -> None:
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "newfile.txt").write_text("new\n", encoding="utf-8")
    artifacts = repo / "oracle_builds" / "20260716_000000"
    artifacts.mkdir(parents=True)
    (artifacts / "PIPELINE_STATE.md").write_text("state\n", encoding="utf-8")
    assert sorted(ob.touched_paths(repo)) == ["app.py", "newfile.txt"]


def test_protected_violations_matches_glob_and_dir_forms(repo: Path) -> None:
    (repo / "secret" / "config.json").write_text('{"a": 1}\n', encoding="utf-8")
    (repo / "app.py").write_text("x = 3\n", encoding="utf-8")
    hits = ob.protected_violations(repo, ["secret/*"])
    assert hits == [("secret/config.json", "secret/*")]
    # bare directory pattern (no glob, no trailing slash) protects its contents
    hits_dir = ob.protected_violations(repo, ["secret"])
    assert hits_dir == [("secret/config.json", "secret")]
    # deleting a protected file is also a violation
    (repo / "secret" / "config.json").unlink()
    assert ob.protected_violations(repo, ["secret/*"])


def test_protected_violations_clean_tree_is_empty(repo: Path) -> None:
    assert ob.protected_violations(repo, ["secret/*"]) == []


# ── Check-command resolution ────────────────────────────────────────────────

def test_resolve_check_cmd_none_disables(repo: Path) -> None:
    assert ob.resolve_check_cmd(repo, "none") == (None, False)
    assert ob.resolve_check_cmd(repo, "NONE") == (None, False)


def test_resolve_check_cmd_auto_without_test_setup_skips(repo: Path) -> None:
    argv, auto = ob.resolve_check_cmd(repo, "auto")
    assert argv is None
    assert auto is True


def test_resolve_check_cmd_auto_detects_tests_dir(repo: Path) -> None:
    (repo / "tests").mkdir()
    argv, auto = ob.resolve_check_cmd(repo, "auto")
    assert auto is True
    if shutil.which("pytest"):
        assert argv is not None and argv[-2:] == ["tests", "-q"]
    else:  # pytest missing from PATH degrades to skip, never crashes
        assert argv is None


def test_resolve_check_cmd_explicit_missing_is_hard_error(repo: Path) -> None:
    with pytest.raises(RuntimeError, match="not found on PATH"):
        ob.resolve_check_cmd(repo, "definitely-not-a-real-command-xyz --flag")


# ── run_checks ──────────────────────────────────────────────────────────────

def _py_cmd(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_checks_pass(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    ok, report, path = ob.run_checks(repo, out, 1, _py_cmd("pass"), False, ["secret/*"])
    assert ok is True
    assert "RESULT: PASS" in report
    assert "Protected paths — PASS" in report
    assert path == out / "check_round1.md" and path.is_file()


def test_run_checks_failing_command_fails_with_output_tail(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    ok, report, _ = ob.run_checks(
        repo, out, 2, _py_cmd("print('boom marker'); raise SystemExit(3)"), False, [])
    assert ok is False
    assert "RESULT: FAIL" in report
    assert "exit code 3" in report
    assert "boom marker" in report


def test_run_checks_exit_5_is_warning_in_auto_but_fail_when_explicit(
        repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    argv = _py_cmd("raise SystemExit(5)")
    ok_auto, report_auto, _ = ob.run_checks(repo, out, 1, argv, True, [])
    assert ok_auto is True
    assert "NO TESTS COLLECTED" in report_auto
    ok_explicit, report_explicit, _ = ob.run_checks(repo, out, 2, argv, False, [])
    assert ok_explicit is False
    assert "exit code 5" in report_explicit


def test_run_checks_protected_violation_fails_before_tests_can_pass(
        repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (repo / "secret" / "config.json").write_text('{"tampered": true}\n', encoding="utf-8")
    ok, report, _ = ob.run_checks(repo, out, 1, _py_cmd("pass"), False, ["secret/*"])
    assert ok is False
    assert "Protected paths — FAIL" in report
    assert "secret/config.json" in report and "secret/*" in report
    assert "Tests — PASS" in report  # tests passing does not rescue the round


def test_run_checks_skipped_tests_are_flagged_not_failed(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    ok, report, _ = ob.run_checks(repo, out, 1, None, True, [])
    assert ok is True
    assert "Tests — SKIPPED" in report
    assert "Protected paths — SKIPPED" in report


# ── Verdict clamp ───────────────────────────────────────────────────────────

APPROVED_GATE = "## Final Verdict\nAPPROVED\n\nShip it.\n"


def test_final_gate_verdict_clamps_approved_on_red_checks() -> None:
    assert ob.final_gate_verdict(APPROVED_GATE, checks_ok=False) == "CHANGES REQUIRED"
    assert ob.final_gate_verdict(APPROVED_GATE, checks_ok=True) == "APPROVED"


def test_final_gate_verdict_rejected_passes_through_clamp() -> None:
    gate = "## Final Verdict\nREJECTED\n\nFundamentally wrong.\n"
    assert ob.final_gate_verdict(gate, checks_ok=False) == "REJECTED"


def test_clamped_report_parses_as_changes_required_everywhere() -> None:
    # The server UI re-parses PIPELINE_REPORT.md for the verdict; a clamped
    # report must never surface Beth's original APPROVED to any parser.
    verdict = ob.final_gate_verdict(APPROVED_GATE, checks_ok=False)
    report = ob._pipeline_report(Path("spec.md"), Path("."), ["### Atlas Review — Round 1"],
                                 "SHIP", False, verdict, APPROVED_GATE)
    assert ob.parse_gate_verdict(report) == "CHANGES REQUIRED"
    assert "clamped from APPROVED" in report
    assert "**Checks:** FAIL" in report


def test_unclamped_report_keeps_gate_verdict() -> None:
    report = ob._pipeline_report(Path("spec.md"), Path("."), ["### Atlas Review — Round 1"],
                                 "SHIP", True, "APPROVED", APPROVED_GATE)
    assert ob.parse_gate_verdict(report) == "APPROVED"
    assert "clamped" not in report


# ── Pipeline state file ─────────────────────────────────────────────────────

def test_pipeline_state_persists_and_caps_entries(tmp_path: Path) -> None:
    state = ob.PipelineState(tmp_path / "PIPELINE_STATE.md", entry_cap=100)
    state.add("Round 1 — Ben fix summary (review findings)", "tail-marker " + "x" * 500)
    assert (tmp_path / "PIPELINE_STATE.md").is_file()  # written after every add
    rendered = state.render()
    assert "## Round 1 — Ben fix summary (review findings)" in rendered
    assert "chars truncated" in rendered
    assert rendered.endswith("x" * 50)  # the tail survives, not the head
    state.add("Round 1 — Atlas verdict", "FIX FIRST")
    on_disk = (tmp_path / "PIPELINE_STATE.md").read_text(encoding="utf-8")
    assert "Atlas verdict" in on_disk


def test_pipeline_state_empty_render() -> None:
    state = ob.PipelineState(Path("unused.md"))
    assert state.render() == "(no rounds recorded yet)"


# ── run_pipeline orchestration (fake agents via the PipelineAgents seam) ────

PASS_CMD = f"{sys.executable} -c pass"
PYTEST_CMD = f"{sys.executable} -m pytest tests -q"
APPROVED = "## Final Verdict\nAPPROVED\n\nShip it.\n"


def make_agents(
    verdicts: list[str],
    gate_output: str = APPROVED,
    on_fix=None,
) -> tuple[ob.PipelineAgents, dict]:
    """Deterministic stand-ins for grok/codex/Anthropic. `on_fix` runs on every
    fix prompt so a fake fix can genuinely repair the repo between rounds."""
    calls: dict = {"build": [], "review": [], "gate": []}
    verdict_iter = iter(verdicts)

    def build(prompt: str, _repo: Path, _timeout: int) -> str:
        calls["build"].append(prompt)
        if on_fix is not None and "Implement the specification" not in prompt:
            on_fix(prompt)
        return "fake build/fix summary"

    def review(_spec: Path, _repo: Path, out_dir: Path, round_num: int,
               *, state_md: str = "") -> tuple[str, Path]:
        calls["review"].append({"round": round_num, "state_md": state_md})
        text = f"1. nothing real\n\nVERDICT: {next(verdict_iter)}"
        path = out_dir / f"atlas_review_round{round_num}.md"
        path.write_text(text, encoding="utf-8")
        return text, path

    def gate(_system: str, user_prompt: str, timeout=None) -> str:
        calls["gate"].append(user_prompt)
        return gate_output

    return ob.PipelineAgents(build=build, review=review, gate=gate), calls


@pytest.fixture
def build_repo(tmp_path: Path) -> Path:
    """Repo with a committed passing test and a tracked file to modify."""
    repo = tmp_path / "build_repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@boundstate.ai")
    _git(repo, "config", "user.name", "test")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n",
                                                encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")  # non-empty diff for the gate
    return repo


def _spec(tmp_path: Path) -> Path:
    spec = tmp_path / "spec.md"
    spec.write_text("# Goal\nChange x.\n", encoding="utf-8")
    return spec


def test_run_pipeline_happy_path(build_repo: Path, tmp_path: Path) -> None:
    agents, calls = make_agents(verdicts=["SHIP"])
    out = tmp_path / "out"
    verdict = ob.run_pipeline(_spec(tmp_path), build_repo, 1, False, out,
                              check_cmd=PASS_CMD, agents=agents)
    assert verdict == "APPROVED"
    assert len(calls["build"]) == 1  # BUILD only, no fixes
    assert "Implement the specification" in calls["build"][0]
    assert [c["round"] for c in calls["review"]] == [1]
    assert len(calls["gate"]) == 1
    gate_prompt = calls["gate"][0]
    assert "## Deterministic Check Evidence" in gate_prompt
    assert "### Atlas Review — Round 1" in gate_prompt
    report = (out / "PIPELINE_REPORT.md").read_text(encoding="utf-8")
    assert "**Checks:** PASS" in report and "**Final Gate:** APPROVED" in report
    assert (out / "build_log.md").is_file()
    state = (out / "PIPELINE_STATE.md").read_text(encoding="utf-8")
    assert "Build — Ben's summary" in state


def test_run_pipeline_red_check_routes_to_fix_and_skips_review(
        build_repo: Path, tmp_path: Path) -> None:
    test_file = build_repo / "tests" / "test_app.py"
    test_file.write_text("def test_ok():\n    assert False\n", encoding="utf-8")

    def fix(prompt: str) -> None:
        assert "deterministic checks" in prompt  # CHECK_FIX_PROMPT, not FIX_PROMPT
        test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    agents, calls = make_agents(verdicts=["SHIP"], on_fix=fix)
    out = tmp_path / "out"
    verdict = ob.run_pipeline(_spec(tmp_path), build_repo, 1, True, out,
                              check_cmd=PYTEST_CMD, agents=agents)
    assert verdict == "APPROVED"
    assert len(calls["build"]) == 1  # exactly one fix pass, no build (skip_build)
    assert [c["round"] for c in calls["review"]] == [2]  # round 1 never reached Atlas
    assert (out / "fix_log_round1.md").is_file()
    assert "FAIL" in (out / "check_round1.md").read_text(encoding="utf-8")
    assert "RESULT: PASS" in (out / "check_round2.md").read_text(encoding="utf-8")


def test_run_pipeline_exhausted_red_checks_clamps_gate(
        build_repo: Path, tmp_path: Path) -> None:
    (build_repo / "tests" / "test_app.py").write_text(
        "def test_ok():\n    assert False\n", encoding="utf-8")
    agents, calls = make_agents(verdicts=[], gate_output=APPROVED)
    out = tmp_path / "out"
    verdict = ob.run_pipeline(_spec(tmp_path), build_repo, 0, True, out,
                              check_cmd=PYTEST_CMD, agents=agents)
    assert verdict == "CHANGES REQUIRED"  # Beth said APPROVED; evidence wins
    assert calls["review"] == []          # no reviewer tokens on red code
    assert len(calls["gate"]) == 1        # gate still ran, for the report
    report = (out / "PIPELINE_REPORT.md").read_text(encoding="utf-8")
    assert "clamped from APPROVED" in report
    assert "**Atlas rounds:** 0" in report
    assert ob.parse_gate_verdict(report) == "CHANGES REQUIRED"


def test_run_pipeline_review_fix_carries_state_forward(
        build_repo: Path, tmp_path: Path) -> None:
    agents, calls = make_agents(verdicts=["FIX FIRST", "SHIP"])
    out = tmp_path / "out"
    verdict = ob.run_pipeline(_spec(tmp_path), build_repo, 1, True, out,
                              check_cmd=PASS_CMD, agents=agents)
    assert verdict == "APPROVED"
    assert [c["round"] for c in calls["review"]] == [1, 2]
    round2_state = calls["review"][1]["state_md"]
    assert "Round 1 — Atlas verdict" in round2_state
    assert "Ben fix summary (review findings)" in round2_state
    assert "code reviewer (Atlas)" in calls["build"][0]  # FIX_PROMPT variant used
    gate_prompt = calls["gate"][0]
    assert "### Atlas Review — Round 1" in gate_prompt
    assert "### Atlas Review — Round 2" in gate_prompt


def test_run_pipeline_oversized_diff_refuses_gate(build_repo: Path, tmp_path: Path) -> None:
    (build_repo / "app.py").write_text("x" * 250_001, encoding="utf-8")
    agents, calls = make_agents(verdicts=["SHIP"])
    out = tmp_path / "out"
    verdict = ob.run_pipeline(_spec(tmp_path), build_repo, 1, True, out,
                              check_cmd=PASS_CMD, agents=agents)
    assert verdict == "CHANGES REQUIRED"
    assert calls["gate"] == []  # Beth never sees a truncated diff
    report = (out / "PIPELINE_REPORT.md").read_text(encoding="utf-8")
    assert "[GATE INPUT ERROR]" in report


def test_default_agents_wires_real_runners() -> None:
    agents = ob.default_agents()
    assert agents.build is ob.run_grok
    assert agents.review is ob.run_atlas_review


# ── Real stage runners fail loudly when their CLI is absent ─────────────────

@pytest.mark.skipif(shutil.which("grok") is not None, reason="grok CLI installed")
def test_run_grok_missing_cli_raises(repo: Path) -> None:
    with pytest.raises(RuntimeError, match="grok CLI not found"):
        ob.run_grok("prompt", repo, timeout=5)


@pytest.mark.skipif(shutil.which("codex") is not None, reason="codex CLI installed")
def test_run_atlas_review_writes_request_with_state_before_failing(
        build_repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(RuntimeError, match="codex CLI not found"):
        ob.run_atlas_review(_spec(tmp_path), build_repo, out, 3, state_md="PRIOR-MARKER")
    request = (out / "review_request_round3.md").read_text(encoding="utf-8")
    assert "## Prior Rounds (pipeline state)" in request
    assert "PRIOR-MARKER" in request
    assert "## Diff Under Review" in request
