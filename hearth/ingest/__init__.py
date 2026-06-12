#!/usr/bin/env python3
"""
Module: hearth.ingest
Purpose: Source adapters — bulk-file based in Phase 2 (spec v0.3 §4, §4.1;
         §13 P2-C).

No adapter may be built before its data-rights matrix row is declared
(§4.1); the declarations live on each adapter and are enforced per batch
in hearth.ingest.base. No live network adapters exist in Phase 2 — the
operator supplies downloaded export files.

Safety Critical: False
Financially Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

from hearth.ingest.base import (
    IngestAdapter,
    IngestBatch,
    IngestError,
    RawPropertyRecord,
    validate_batch,
)
from hearth.ingest.larimer_assessor import LarimerAssessorAdapter
from hearth.ingest.larimer_permits import LarimerPermitsAdapter

ADAPTERS: dict[str, IngestAdapter] = {
    LarimerAssessorAdapter.source_id: LarimerAssessorAdapter(),
    LarimerPermitsAdapter.source_id: LarimerPermitsAdapter(),
}


def get_adapter(name: str) -> IngestAdapter:
    """Adapter by source_id; IngestError on unknown (fail closed)."""
    adapter = ADAPTERS.get(name)
    if adapter is None:
        raise IngestError(
            f"unknown ingest adapter {name!r}; available: {sorted(ADAPTERS)}"
        )
    return adapter


__all__ = [
    "ADAPTERS",
    "IngestAdapter",
    "IngestBatch",
    "IngestError",
    "RawPropertyRecord",
    "get_adapter",
    "validate_batch",
]
