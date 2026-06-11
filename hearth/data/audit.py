#!/usr/bin/env python3
"""
Module: hearth.data.audit
Purpose: AuditArtifact — per-run reproducibility record (spec v0.3 §11).

Every financially-critical run (scrub, valuation, scenario) emits an
immutable audit artifact: source snapshot IDs, JurisdictionPack version and
contributing rule_ids, scoring-profile version, code/model/prompt hashes,
and the rendered output. Any later pack/source/model/prompt change that
would alter a prior result must be reproducible and explainable.

The artifact carries its own content hash (artifact_sha256, computed over
the canonical JSON dump excluding that field) so tampering is detectable;
emission and verification live in hearth.audit.artifact.

Safety Critical: False
Financially Critical: False (contract definition; emission/verification in
  hearth.audit.artifact is the financially-critical surface)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

from datetime import datetime
from typing import Literal

from pydantic import Field

from hearth.data.base import HearthModel
from hearth.data.scrub import ScrubFinding

RunType = Literal["scrub", "valuation", "scenario"]

# §12 P1-B: prompt/model hash may be stubbed constants in P1 — there is no
# model and no prompt in the deterministic-only pipeline. Honest constants,
# not fabricated hashes.
STUB_MODEL_HASH = "P1-STUB:no-model-in-deterministic-pipeline"
STUB_PROMPT_HASH = "P1-STUB:no-prompt-in-deterministic-pipeline"


class AuditArtifact(HearthModel):
    """Immutable record of one financially-critical run (§11)."""

    artifact_schema_version: Literal["1"] = "1"
    run_id: str = Field(min_length=8)
    run_type: RunType
    created_at: datetime
    # Which data rows/versions fed the run, e.g.
    # "doc:<name>:sha256:<hash>" and "pack:CO-Larimer@2026.06:sha256:<hash>".
    source_snapshot_ids: list[str]
    jurisdiction_pack_id: str | None
    contributing_rule_ids: list[str]
    scoring_profile_version: str | None = None
    code_hash: str = Field(min_length=1)
    model_hash: str = Field(min_length=1)
    prompt_hash: str = Field(min_length=1)
    findings: list[ScrubFinding]
    rendered_output: str
    exit_code: int
    artifact_sha256: str = Field(min_length=64, max_length=64)
