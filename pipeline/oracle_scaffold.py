"""
Oracle Platform Scaffold — pour the harness before the build.

Every platform the build pipeline generates must ship with CI, a test suite,
and its own guardrails from commit zero. Asking the builder model to create
those is unreliable (a prompt can be ignored); this tool stamps them
deterministically, so the floor exists before Ben writes a line — and the
`.oracle_protected` it installs stops Ben from weakening his own gates.

Stamped files (existing files are NEVER overwritten):

  .github/workflows/tests.yml   pytest + coverage floor on every push/PR
  tests/test_smoke.py           day-zero test so pytest collects from commit 1
  .oracle_protected             protects CI + itself from pipeline builds
  AGENTS.md                     standing context stub for builder agents
  .gitignore                    bytecode, coverage, pipeline artifacts
  pyproject.toml                minimal project + pytest config (only if absent)

Usage:
    py pipeline/oracle_scaffold.py --repo D:/BoundState/new_platform
    py pipeline/oracle_scaffold.py --repo . --package myplatform

Standalone like its siblings — no imports from the ORACLE/HEARTH app.
"""
__safety_critical__: bool = False

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger("oracle.pipeline.scaffold")

TESTS_YML = """name: tests

# Scaffolded by oracle_scaffold: full suite + coverage floor on every push
# and PR. Raise the floor as the platform grows — never lower it to make a
# PR pass. Add a boot-smoke job (start the app, probe its health endpoint)
# once the platform has a runnable surface; see the oracle repo's tests.yml
# for the pattern.
on:
  push:
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  pytest:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          pip install pytest pytest-cov
      - name: Run test suite with coverage floor
        run: python -m pytest tests/ -v --cov=. --cov-report=term --cov-fail-under=70
"""

SMOKE_TEST = '''"""Day-zero scaffold test.

Exists so pytest collects (and CI is green) from the first commit. Replace
the placeholder with real tests as the platform grows — the build pipeline's
diff-coverage gate requires the lines each build adds to be genuinely
executed by tests, so this file cannot be used to fake coverage.
"""


def test_scaffold_placeholder() -> None:
    assert True  # TODO: import your package and assert something real
'''

ORACLE_PROTECTED = """# Paths the oracle build pipeline must never modify (one glob per line).
# Read by pipeline/oracle_build.py's CHECK stage; a spec's "## Never touch"
# section adds task-specific patterns on top. Inline comments after " #"
# are stripped.
#
# The first two lines are the point: the builder must not be able to weaken
# its own gates.
.github/workflows/* # CI is the floor — changes go through humans, not builds
.oracle_protected # this file protects itself
"""

AGENTS_STUB = """# AGENTS.md — standing context for builder agents

<!-- Scaffolded by oracle_scaffold. Fill in the TODOs, keep the whole file
     under 300 lines (oversized standing context measurably degrades agent
     task completion), and prune it as the platform evolves. -->

## Project

TODO: one paragraph — what this platform is and who it serves.

## Layout

TODO: the two or three directories that matter and what lives in each.

## Commands

- `python -m pytest tests/ -q` — test suite (CI enforces a coverage floor)

## Standards

- Python type hints everywhere; Pydantic `extra="forbid"` at API boundaries.
- No bare `except`; logging, not print, in library code.
- Tests accompany every behavior change — the build pipeline measures diff
  coverage of the lines you add.

## Never

- Edit `.github/workflows/` or `.oracle_protected` (protected; humans only).
- Add dependencies without stating the justification in your summary.
"""

GITIGNORE = """__pycache__/
*.py[cod]
.pytest_cache/
.coverage
coverage.json
oracle_builds/
oracle_reviews/
.env
"""

PYPROJECT = """[project]
name = "{package}"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
"""


def scaffold(repo: Path, package: str | None = None) -> list[tuple[str, str]]:
    """Stamp the platform floor into `repo`. Returns (relative_path, status)
    where status is "created" or "exists". Never overwrites existing files —
    a repo's own harness always wins over the template."""
    package_name = package or repo.resolve().name.replace("-", "_")
    files: dict[str, str] = {
        ".github/workflows/tests.yml": TESTS_YML,
        "tests/test_smoke.py": SMOKE_TEST,
        ".oracle_protected": ORACLE_PROTECTED,
        "AGENTS.md": AGENTS_STUB,
        ".gitignore": GITIGNORE,
        "pyproject.toml": PYPROJECT.format(package=package_name),
    }
    results: list[tuple[str, str]] = []
    for rel_path, content in files.items():
        target = repo / rel_path
        if target.exists():
            results.append((rel_path, "exists"))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        results.append((rel_path, "created"))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Oracle Platform Scaffold — stamp CI, tests, and guardrails "
                    "into a platform repo before the build pipeline runs")
    parser.add_argument("--repo", default=".", help="Target repo (default: cwd)")
    parser.add_argument("--package", help="Package name for pyproject.toml "
                                          "(default: repo directory name)")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        LOGGER.error("Repo directory not found: %s", repo)
        sys.exit(1)

    results = scaffold(repo, args.package)
    created = sum(1 for _, status in results if status == "created")
    print(f"\nPlatform floor for {repo}:")
    for rel_path, status in results:
        marker = "+" if status == "created" else "="
        print(f"  {marker} {rel_path:<32s} {status}")
    print(f"\n{created} file(s) created, {len(results) - created} already present.")
    if created:
        print("Review the TODOs in AGENTS.md, then commit the floor before building.")


if __name__ == "__main__":
    main()
