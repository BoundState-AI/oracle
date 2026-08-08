"""Phase 0 — Curate: 6030+6033 packs, dependency graph. BoundState AI 2026."""

from __future__ import annotations

from oracle.disposition.graph import DEPENDENCY_SEEDS, DependencyGraph
from oracle.disposition.packs import SEED_6033, load_rdw_default_packs


def test_phase0_loads_6030_and_6033_with_unique_ids():
    recs, hashes = load_rdw_default_packs(include_6033=True, repin=True)
    assert SEED_6033.is_file()
    assert len(hashes) >= 2
    ids = [r.requirement_id for r in recs]
    assert len(ids) == len(set(ids))
    assert any(i.startswith("AMR-") for i in ids)
    assert any(i.startswith("EFCR-") for i in ids)
    assert len(recs) >= 115 + 8


def test_phase0_dependency_graph_no_hard_cycles_on_units():
    g = DependencyGraph.from_seeds()
    assert len(DEPENDENCY_SEEDS) >= 10
    # AMR-17 reachable from classification fact
    assert "AMR-17" in g.propagate_from_fact("classification.primary", committed=True)
    # Proposals do not propagate
    assert g.propagate_from_fact("classification.primary", committed=False) == []


def test_phase0_efcp_chain_edges():
    g = DependencyGraph.from_seeds()
    prereqs = [e.prerequisite_id for e in g.prerequisites_of("EFCR-2")]
    assert "AMR-14" in prereqs or "EFCR-1" in prereqs
