"""P1-D static boundary scan (spec v0.3 §1.1, §6, §12 P1-D).

Phase 1 hearth code has ZERO outbound network call sites, so the static
invariant is total: no module under hearth/ may import an outbound-capable
library, stdlib or third-party. Any future adapter that legitimately needs
one must be added to ALLOWED_IMPORTS with a WHY comment and a matching
runtime boundary test — that review moment is the control."""

from __future__ import annotations

import ast
from pathlib import Path

from .conftest import REPO_ROOT

HEARTH_PACKAGE = REPO_ROOT / "hearth"

# Outbound-capable modules: opening any of these inside hearth/ is a
# build-failing event until it passes boundary review.
BANNED_IMPORTS = frozenset(
    {
        "socket", "ssl", "http", "urllib", "urllib3", "httpx", "requests",
        "aiohttp", "websockets", "websocket", "smtplib", "ftplib", "poplib",
        "imaplib", "telnetlib", "xmlrpc", "grpc", "paramiko", "boto3",
        "anthropic", "openai", "google",
        # Dynamic-import / FFI escape hatches: banning them keeps the static
        # scan honest — code that needs runtime imports must pass boundary
        # review instead of slipping past the AST walk.
        "importlib", "ctypes",
    }
)

# (module path relative to repo root, banned import) pairs that passed
# boundary review. Growing this list requires a WHY and a runtime canary
# covering the new surface.
ALLOWED_IMPORTS: frozenset[tuple[str, str]] = frozenset(
    {
        # §14 P3-A: the fetch layer pulls PUBLIC bulk market data only.
        # BuyerPack material never reaches it — proven by the runtime canary
        # (test_boundary_canary covers the fetch plan + a mocked-transport
        # pull with canary BuyerPack in memory). Reviewed 2026-06-12.
        ("hearth/ingest/fetch.py", "httpx"),
    }
)


def iter_hearth_sources() -> list[Path]:
    return sorted(HEARTH_PACKAGE.rglob("*.py"))


def banned_imports_in(source: str) -> set[str]:
    """Top-level package names from import statements that are banned."""
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level>0) stay inside hearth by construction.
            names = [node.module] if node.module and node.level == 0 else []
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top in BANNED_IMPORTS:
                found.add(name)
    return found


def test_hearth_package_has_sources():
    assert len(iter_hearth_sources()) > 10  # the scan must scan something


def test_no_outbound_capable_imports_anywhere_in_hearth():
    violations = []
    for path in iter_hearth_sources():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for name in banned_imports_in(path.read_text(encoding="utf-8")):
            if (rel, name) not in ALLOWED_IMPORTS:
                violations.append(f"{rel} imports {name}")
    assert not violations, (
        "BuyerPack trust boundary (§1.1): outbound-capable imports inside "
        f"hearth/: {violations}"
    )


def test_scanner_detects_a_violation():
    """The scan itself must be alive: a deliberate leak module turns it red."""
    leaky = "import json\nimport httpx\nfrom urllib.request import urlopen\n"
    assert banned_imports_in(leaky) == {"httpx", "urllib.request"}


def test_scanner_sees_function_level_imports_too():
    leaky = "def hidden():\n    import socket\n    return socket\n"
    assert banned_imports_in(leaky) == {"socket"}


def test_scanner_ignores_safe_imports():
    clean = "import logging\nfrom hearth.data import BuyerPack\nimport fitz\n"
    assert banned_imports_in(clean) == set()
