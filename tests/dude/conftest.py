"""Shared fixtures for the DUDE test suite (spec v0.2 §7 — invariant
tests are written against the store interface, no monkeypatching)."""

from __future__ import annotations

import pytest

from dude.data import Case
from dude.store.jsonl import CaseStore


@pytest.fixture()
def store(tmp_path) -> CaseStore:
    return CaseStore(root=tmp_path / "dude_home")


@pytest.fixture()
def case(store: CaseStore) -> Case:
    record = Case(title="Test case")
    store.create_case(record)
    return record
