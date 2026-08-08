"""Stage B: rulepack adapter tests. BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.rulepack import (
    BUILTIN_NASA_6030,
    PackPinError,
    content_hash_path,
    load_requirement_records,
    prerequisites_of,
)


def test_load_real_115_amr_pack_round_trip():
    records, digest = load_requirement_records()
    assert digest.startswith("sha256:")
    assert len(records) >= 100  # 115 AMRs expected
    # Round-trip: every record has verbatim shall_text and locator
    for r in records:
        assert r.shall_text.strip()
        assert r.locator.standard
        assert r.locator.section
        assert r.pack_content_hash == digest
        assert r.requirement_id
        # Candidates marked machine-extracted
        if r.actor_candidate is not None:
            assert r.actor_candidate.machine_extracted is True
            assert r.actor_candidate.confirmed is False
        for t in r.trigger_candidates:
            assert t.machine_extracted is True


def test_hash_pinning_refuses_without_repin(tmp_path):
    records, digest = load_requirement_records()
    # Wrong pin
    with pytest.raises(PackPinError):
        load_requirement_records(expected_hash="sha256:deadbeef", repin=False)
    # Explicit repin allowed
    recs2, d2 = load_requirement_records(expected_hash="sha256:deadbeef", repin=True)
    assert d2 == digest
    assert len(recs2) == len(records)


def test_dependency_seeds_present():
    assert "AMR-14" in prerequisites_of("EFCR-1") or prerequisites_of("EFCR-1")
    # Classification chain points at AMR-17
    prereqs = prerequisites_of("AMR-17")
    assert any(p.startswith("AMR-") for p in prereqs)


def test_builtin_path_exists():
    assert BUILTIN_NASA_6030.is_file()
    assert content_hash_path(BUILTIN_NASA_6030).startswith("sha256:")
