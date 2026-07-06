#!/usr/bin/env python3
"""
Module: dude.data.base
Purpose: Shared Pydantic base for all DUDE data contracts.

Every DUDE model inherits DudeModel so the contract posture is uniform:
extra="forbid" everywhere (unknown keys are defects, not extensions) and
lossless JSON round-trips, matching the HEARTH contract discipline.

Safety Critical: False
Psychologically Critical: False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = False

import json
from typing import Any

from pydantic import BaseModel, ConfigDict


class DudeModel(BaseModel):
    """Base class for all DUDE data contracts (spec v0.2 §7)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    def to_json_dict(self) -> dict[str, Any]:
        """Canonical JSON-mode dump used by round-trip tests and hashing."""
        return json.loads(self.model_dump_json())
