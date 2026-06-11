#!/usr/bin/env python3
"""
Module: hearth.api
Purpose: FastAPI endpoints, single-tenant (spec v0.3 §1).

Health endpoint only in Phase 1 (§12 constraints).

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
