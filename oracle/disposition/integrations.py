#!/usr/bin/env python3
"""
Module: oracle.disposition.integrations
Purpose: Phase 5 integration interfaces — read-only evidence/QMS connectors.

No network by default. Local filesystem connector is the MVP integration.
External QMS/PLM adapters implement the same protocol without writeback
(non-objective: no bidirectional write to customer systems in MVP).

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

LOGGER = logging.getLogger("oracle.disposition.integrations")


class ExternalEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system: str
    external_id: str
    doc_id: str
    revision: str
    title: str = ""
    uri: str = ""
    metadata: dict[str, Any] = {}


class EvidenceConnector(ABC):
    """Read-only evidence connector protocol (FR integration boundary)."""

    name: str = "base"

    @abstractmethod
    def list_references(self, query: str = "") -> list[ExternalEvidenceRef]:
        ...

    @abstractmethod
    def fetch_metadata(self, external_id: str) -> Optional[ExternalEvidenceRef]:
        ...


class LocalEvidenceConnector(EvidenceConnector):
    """
    Read-only scan of a local evidence directory.

    Expects optional manifest.jsonl with doc_id/revision/path fields,
    or plain files named {doc_id}_r{revision}.*
    """

    name = "local_filesystem"

    def __init__(self, root: Path | str):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"Evidence root not found: {self.root}")

    def list_references(self, query: str = "") -> list[ExternalEvidenceRef]:
        refs: list[ExternalEvidenceRef] = []
        manifest = self.root / "manifest.jsonl"
        if manifest.is_file():
            with manifest.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    ref = ExternalEvidenceRef(
                        system=self.name,
                        external_id=str(data.get("id") or f"local-{i}"),
                        doc_id=str(data["doc_id"]),
                        revision=str(data.get("revision") or "unknown"),
                        title=str(data.get("title") or ""),
                        uri=str(data.get("path") or data.get("uri") or ""),
                        metadata={k: v for k, v in data.items() if k not in {
                            "id", "doc_id", "revision", "title", "path", "uri"
                        }},
                    )
                    if query.lower() in (ref.doc_id + ref.title).lower() or not query:
                        refs.append(ref)
            return refs

        for p in sorted(self.root.iterdir()):
            if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".txt", ".json"}:
                stem = p.stem
                doc_id, rev = stem, "1"
                if "_r" in stem:
                    doc_id, rev = stem.rsplit("_r", 1)
                ref = ExternalEvidenceRef(
                    system=self.name,
                    external_id=stem,
                    doc_id=doc_id,
                    revision=rev,
                    title=stem,
                    uri=str(p.resolve()),
                )
                if query.lower() in stem.lower() or not query:
                    refs.append(ref)
        return refs

    def fetch_metadata(self, external_id: str) -> Optional[ExternalEvidenceRef]:
        for r in self.list_references():
            if r.external_id == external_id or r.doc_id == external_id:
                return r
        return None


class NullQmsConnector:
    """
    Placeholder QMS connector — documents the boundary without network I/O.

    Phase 5 security: read-only; no writeback; requires explicit enable.
    """

    name = "qms_null"

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def health(self) -> dict[str, Any]:
        return {
            "connector": self.name,
            "enabled": self.enabled,
            "mode": "read_only",
            "writeback": False,
            "note": "Enable only after security/data-governance review",
        }

    def list_controlled_docs(self) -> list[ExternalEvidenceRef]:
        if not self.enabled:
            raise RuntimeError("QMS connector disabled (default fail-closed)")
        return []
