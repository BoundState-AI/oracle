"""Shared test fixtures for the ORACLE test suite."""
import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_vendor_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite's contract is keyless determinism (CI has no keys; every
    oracle call is mocked). On a developer machine WITH keys, key-aware code
    paths (chat LLM synthesis/fallback) otherwise activate and produce
    non-deterministic answers — observed as 6 spurious failures on the first
    keyed Windows run. Tests that need a key present set it explicitly via
    monkeypatch.setenv, which still works on top of this."""
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def workspace_tmp_path() -> Path:
    root = Path("tests/.tmp/runtime")
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
