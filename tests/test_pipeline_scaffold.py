"""Tests for oracle_scaffold: the platform floor is stamped completely,
idempotently, and never over an existing file — and the scaffolded CI/config
actually parse."""
from __future__ import annotations

from pathlib import Path

import yaml

from pipeline import oracle_scaffold as osc


def test_scaffold_creates_full_floor(tmp_path: Path) -> None:
    results = dict(osc.scaffold(tmp_path, package="demo_platform"))
    assert set(results) == {
        ".github/workflows/tests.yml", "tests/test_smoke.py", ".oracle_protected",
        "AGENTS.md", ".gitignore", "pyproject.toml",
    }
    assert all(status == "created" for status in results.values())

    workflow = yaml.safe_load((tmp_path / ".github/workflows/tests.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["pytest"]["steps"]
    assert any("--cov-fail-under=70" in str(step.get("run", "")) for step in steps)

    pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "demo_platform"' in pyproject

    protected = (tmp_path / ".oracle_protected").read_text(encoding="utf-8")
    assert ".github/workflows/*" in protected  # builder cannot weaken its own gates
    assert ".oracle_protected" in protected    # ...or unprotect itself


def test_scaffold_is_idempotent_and_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("hand-written context\n", encoding="utf-8")
    first = dict(osc.scaffold(tmp_path))
    assert first["AGENTS.md"] == "exists"
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "hand-written context\n"

    second = osc.scaffold(tmp_path)
    assert all(status == "exists" for _, status in second)


def test_scaffold_package_defaults_to_dirname(tmp_path: Path) -> None:
    repo = tmp_path / "my-new-platform"
    repo.mkdir()
    osc.scaffold(repo)
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "my_new_platform"' in pyproject  # dashes normalized


def test_scaffolded_floor_satisfies_the_check_stages_platform_floor(tmp_path: Path) -> None:
    from pipeline import oracle_build as ob
    import subprocess

    osc.scaffold(tmp_path, package="demo")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "floor"],
                   check=True, capture_output=True)

    out = tmp_path / "oracle_builds" / "t"
    out.mkdir(parents=True)
    ok, report, _ = ob.run_checks(tmp_path, out, 1, None, True,
                                  ob.load_protected_patterns(tmp_path, ""))
    assert ok is True
    assert "CI workflows (.github/workflows/): present" in report
    assert "tests/ directory: present" in report

    # And the protections it installed actually bite: touching CI is a violation.
    (tmp_path / ".github" / "workflows" / "tests.yml").write_text("weakened: true\n",
                                                                  encoding="utf-8")
    ok2, report2, _ = ob.run_checks(tmp_path, out, 2, None, True,
                                    ob.load_protected_patterns(tmp_path, ""))
    assert ok2 is False
    assert "Protected paths — FAIL" in report2
