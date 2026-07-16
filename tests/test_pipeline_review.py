"""Tests for oracle_review.py's deterministic plumbing: diff collection
(including truncation and strict mode), untracked-file filtering, CLI
resolution/execution, and the run_review orchestration's graceful degradation
when no reviewer is available. No LLM or agent CLI is exercised."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import oracle_review as orv


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@boundstate.ai")
    _git(repo, "config", "user.name", "test")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


# ── collect_diff ────────────────────────────────────────────────────────────

def test_collect_diff_working_tree_includes_untracked_with_filters(repo: Path) -> None:
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "new_small.py").write_text("y = 1\n", encoding="utf-8")
    (repo / "new_big.txt").write_text("z" * 200_001, encoding="utf-8")
    (repo / "oracle_reviews").mkdir()
    (repo / "oracle_reviews" / "old.md").write_text("artifact\n", encoding="utf-8")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"\x00")

    label, diff = orv.collect_diff(repo, base=None, files=None)
    assert label == "git diff HEAD (uncommitted changes)"
    assert "x = 2" in diff
    assert "### NEW FILE: new_small.py" in diff and "y = 1" in diff
    assert "### NEW FILE (too large to inline): new_big.txt" in diff
    assert "oracle_reviews" not in diff
    assert "pycache" not in diff


def test_collect_diff_base_mode_spans_commits_and_working_tree(repo: Path) -> None:
    _git(repo, "branch", "basepoint")
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "second")
    (repo / "app.py").write_text("x = 3\n", encoding="utf-8")
    (repo / "extra.py").write_text("e = 1\n", encoding="utf-8")

    label, diff = orv.collect_diff(repo, base="basepoint", files=None)
    assert "basepoint...HEAD" in label
    assert "x = 2" in diff                      # committed change vs base
    assert "uncommitted working-tree changes" in diff and "x = 3" in diff
    assert "### NEW FILE: extra.py" in diff     # untracked collected in base mode too


def test_collect_diff_files_mode(repo: Path) -> None:
    label, content = orv.collect_diff(repo, base=None, files=["app.py"])
    assert label == "files: app.py"
    assert "### FILE: app.py" in content and "x = 1" in content

    with pytest.raises(FileNotFoundError):
        orv.collect_diff(repo, base=None, files=["missing.py"])

    (repo / "huge.bin").write_text("h" * 2_000_001, encoding="utf-8")
    with pytest.raises(ValueError, match=">2MB"):
        orv.collect_diff(repo, base=None, files=["huge.bin"])


def test_collect_diff_empty_raises(repo: Path) -> None:
    with pytest.raises(ValueError, match="Nothing to review"):
        orv.collect_diff(repo, base=None, files=None)


def test_collect_diff_truncates_unless_strict(repo: Path) -> None:
    (repo / "app.py").write_text("x" * (orv.MAX_DIFF_CHARS + 50_000), encoding="utf-8")
    _, diff = orv.collect_diff(repo, base=None, files=None)
    assert "TRUNCATED — diff exceeded size cap" in diff
    assert len(diff) <= orv.MAX_DIFF_CHARS + 200

    with pytest.raises(ValueError, match="exceeds final-gate capacity"):
        orv.collect_diff(repo, base=None, files=None, strict=True)


# ── CLI resolution and execution ────────────────────────────────────────────

def test_resolve_cmd_found_and_missing() -> None:
    resolved = orv._resolve_cmd(Path(sys.executable).name)
    assert resolved is not None
    assert orv._resolve_cmd("definitely-not-a-real-command-xyz") is None


def test_run_cli_success_failure_and_empty(tmp_path: Path) -> None:
    ok = orv._run_cli([sys.executable, "-c", "print('review text')"], tmp_path, timeout=30)
    assert ok == "review text"

    err = orv._run_cli(
        [sys.executable, "-c",
         "import sys; print('partial out'); sys.stderr.write('boom'); sys.exit(2)"],
        tmp_path, timeout=30)
    assert err.startswith("[ERROR] exit code 2")
    assert "boom" in err and "partial out" in err

    empty = orv._run_cli([sys.executable, "-c", "pass"], tmp_path, timeout=30)
    assert empty.startswith("[ERROR] empty output")


@pytest.mark.skipif(shutil.which("codex") is not None, reason="codex CLI installed")
def test_run_atlas_skips_when_cli_missing(tmp_path: Path) -> None:
    out = orv.run_atlas(tmp_path / "req.md", tmp_path, timeout=5,
                        preset=orv.DEFAULT_ATLAS_PRESET)
    assert out.startswith("[SKIPPED] codex CLI not found")


@pytest.mark.skipif(shutil.which("grok") is not None, reason="grok CLI installed")
def test_run_ben_skips_when_cli_missing(tmp_path: Path) -> None:
    out = orv.run_ben(tmp_path / "req.md", tmp_path, timeout=5)
    assert out.startswith("[SKIPPED] grok CLI not found")


# ── Anthropic leg degrades cleanly without a key ────────────────────────────

def test_call_anthropic_skips_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # env-var isolation only — no code objects are patched
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert orv._anthropic_api_key() is None
    out = orv._call_anthropic("system", "user", timeout=5)
    assert out == "[SKIPPED] ANTHROPIC_API_KEY not set"
    assert orv.run_beth("request", timeout=5) == "[SKIPPED] ANTHROPIC_API_KEY not set"


# ── run_review orchestration (graceful degradation, artifact writing) ───────

def test_build_request_embeds_instructions_and_diff() -> None:
    text = orv.build_request("scope-label", "THE-DIFF", Path("/repo"))
    assert "**Scope:** scope-label" in text
    assert "VERDICT: SHIP" in text  # findings format included
    assert "THE-DIFF" in text


@pytest.mark.skipif(shutil.which("codex") is not None or shutil.which("grok") is not None,
                    reason="agent CLI installed — would launch a real review")
def test_run_review_all_reviewers_unavailable_still_writes_artifacts(
        repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    out = tmp_path / "reviews"

    orv.run_review(repo, base=None, files=None, reviewer_ids=["atlas", "ben", "beth"],
                   output_dir=out, timeout=10, synthesize=True)

    assert (out / "review_request.md").is_file()
    for rid in ("atlas", "ben", "beth"):
        content = (out / f"{rid}.md").read_text(encoding="utf-8")
        assert "[SKIPPED]" in content
    # <2 usable reviews: synthesis must be skipped, never crash
    assert not (out / "MERGED_REVIEW.md").exists()
