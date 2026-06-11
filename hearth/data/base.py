#!/usr/bin/env python3
"""
Module: hearth.data.base
Purpose: Shared Pydantic base for all HEARTH data contracts.

Every HEARTH model inherits HearthModel so the contract posture is uniform:
extra="forbid" at every API boundary (spec v0.3 §2 — the schemas ARE the
contract; unknown keys are a defect, not an extension point), and JSON
round-trips are lossless (P1-A acceptance criterion).

Safety Critical: False
Financially Critical: False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

import json
from typing import Any

from pydantic import BaseModel, ConfigDict


class HearthModel(BaseModel):
    """Base class for all HEARTH data contracts (spec v0.3 §2)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    def to_json_dict(self) -> dict[str, Any]:
        """Canonical JSON-mode dump used by round-trip tests and hashing."""
        return json.loads(self.model_dump_json())
