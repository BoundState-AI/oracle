#!/usr/bin/env python3
"""
Module: oracle.disposition.graph
Purpose: RDW Phase 0/1 dependency graph — seeds, cycle detection, propagation.

Committed-trigger only: accepted facts/decisions propagate; proposals do not.
Re-confirmation over silent thrash: reopened rows are flagged for human re-election.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable, Optional

from pydantic import BaseModel, ConfigDict

LOGGER = logging.getLogger("oracle.disposition.graph")


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prerequisite_id: str
    dependent_id: str
    kind: str  # classification | plan | control | fact
    note: str = ""
    fact_key: Optional[str] = None  # optional project-fact prerequisite


def _e(
    prereq: str,
    dep: str,
    kind: str,
    note: str = "",
    fact_key: Optional[str] = None,
) -> DependencyEdge:
    return DependencyEdge(
        prerequisite_id=prereq,
        dependent_id=dep,
        kind=kind,
        note=note,
        fact_key=fact_key,
    )


# Extended human-authored seeds (Phase 0 curation)
DEPENDENCY_SEEDS: tuple[DependencyEdge, ...] = (
    # Classification package gates class-conditional AMRs
    _e("AMR-5", "AMR-17", "classification", "Primary class → quantitative NDE"),
    _e("AMR-6", "AMR-17", "classification", "Secondary/fracture inputs → NDE"),
    _e("AMR-8", "AMR-17", "classification", "Classification package completeness"),
    _e("AMR-10", "AMR-18", "classification", "Class-conditional special NDE"),
    _e("AMR-11", "AMR-18", "classification", "Class-conditional special NDE"),
    _e("AMR-12", "AMR-18", "classification", "Class-conditional special NDE"),
    _e("AMR-15", "AMR-17", "classification", "Related class controls"),
    # Fact-level classification
    _e("classification.primary", "AMR-17", "fact", "Primary class fact gates AMR-17", "classification.primary"),
    _e("classification.primary", "AMR-18", "fact", "Primary class fact gates AMR-18", "classification.primary"),
    _e("classification.primary", "AMR-5", "fact", "Classification unresolved keeps AMR-5 conditional", "classification.primary"),
    _e("classification.primary", "AMR-6", "fact", "Classification unresolved keeps AMR-6 conditional", "classification.primary"),
    _e("classification.primary", "AMR-8", "fact", "Classification unresolved keeps AMR-8 conditional", "classification.primary"),
    _e("classification.primary", "AMR-10", "fact", "Classification unresolved keeps AMR-10 conditional", "classification.primary"),
    _e("classification.primary", "AMR-12", "fact", "Classification unresolved keeps AMR-12 conditional", "classification.primary"),
    _e("classification.primary", "AMR-15", "fact", "Classification unresolved keeps AMR-15 conditional", "classification.primary"),
    # AMCP
    _e("AMR-2", "AMR-3", "plan", "AMCP gates AMCP-referenced rows"),
    _e("plan.AMCP", "AMR-2", "fact", "AMCP presence fact", "plan.AMCP"),
    # FR1: CEO identity governs AMCP submittal + supplier flow-down (AMR-2/AMR-4)
    _e("ceo.identity", "AMR-2", "fact", "CEO identity governs AMCP submittal responsibility", "ceo.identity"),
    _e("ceo.identity", "AMR-4", "fact", "CEO identity governs supplier flow-down responsibility", "ceo.identity"),
    # EFCP / 6033 chain
    _e("AMR-14", "EFCR-1", "control", "EFCP gates EFCR chain"),
    _e("AMR-14", "EFCR-2", "control", "EFCP gates NDE controls"),
    _e("EFCR-1", "EFCR-2", "control", "EFCP doc before NDE credit"),
    _e("EFCR-1", "EFCR-3", "control", "EFCP before flaw-size credit"),
    _e("plan.EFCP", "AMR-14", "fact", "EFCP plan presence", "plan.EFCP"),
    _e("plan.EFCP", "EFCR-1", "fact", "EFCP plan presence", "plan.EFCP"),
)


@dataclass
class DependencyGraph:
    """Immutable-per-run graph snapshot with cycle detection."""

    edges: list[DependencyEdge] = field(default_factory=list)

    @classmethod
    def from_seeds(
        cls, extra: Iterable[DependencyEdge] | None = None
    ) -> "DependencyGraph":
        edges = list(DEPENDENCY_SEEDS)
        if extra:
            edges.extend(extra)
        g = cls(edges=edges)
        cycles = g.find_cycles()
        if cycles:
            # Benign citation cycles must not halt; log and keep acyclic override paths
            LOGGER.warning("Dependency cycles detected (override paths): %s", cycles[:5])
        return g

    def dependents_of(self, node_id: str) -> list[str]:
        return [e.dependent_id for e in self.edges if e.prerequisite_id == node_id]

    def prerequisites_of(self, node_id: str) -> list[DependencyEdge]:
        return [e for e in self.edges if e.dependent_id == node_id]

    def find_cycles(self) -> list[list[str]]:
        """DFS cycle detection; returns list of cycle node paths."""
        adj: dict[str, list[str]] = defaultdict(list)
        for e in self.edges:
            if e.kind == "fact":
                continue  # fact nodes are external
            adj[e.prerequisite_id].append(e.dependent_id)

        cycles: list[list[str]] = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = defaultdict(int)
        stack: list[str] = []

        def visit(u: str) -> None:
            color[u] = GRAY
            stack.append(u)
            for v in adj.get(u, []):
                if color[v] == GRAY:
                    if v in stack:
                        i = stack.index(v)
                        cycles.append(stack[i:] + [v])
                elif color[v] == WHITE:
                    visit(v)
            stack.pop()
            color[u] = BLACK

        for n in list(adj.keys()):
            if color[n] == WHITE:
                visit(n)
        return cycles

    def propagate_from_fact(
        self,
        fact_key: str,
        *,
        committed: bool = True,
    ) -> list[str]:
        """
        Return unit ids that must re-enter review when a committed fact changes.

        Proposals (committed=False) never propagate.
        """
        if not committed:
            return []
        affected: set[str] = set()
        queue: deque[str] = deque()
        # Direct fact edges
        for e in self.edges:
            if e.fact_key == fact_key or e.prerequisite_id == fact_key:
                affected.add(e.dependent_id)
                queue.append(e.dependent_id)
        # BFS through unit→unit edges
        seen = set(affected)
        while queue:
            u = queue.popleft()
            for v in self.dependents_of(u):
                if v not in seen:
                    seen.add(v)
                    affected.add(v)
                    queue.append(v)
        # Filter to requirement-like ids (AMR-/EFCR-)
        return sorted(
            x
            for x in affected
            if x.startswith("AMR-") or x.startswith("EFCR-") or x.startswith("amr-")
        )


def normalize_req_id(raw: str) -> str:
    s = (raw or "").strip().replace(" ", "-")
    if not s:
        return s
    parts = s.split("-", 1)
    if len(parts) == 2:
        return f"{parts[0].upper()}-{parts[1]}"
    return s.upper()
