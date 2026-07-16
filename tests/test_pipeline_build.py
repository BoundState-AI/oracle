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
