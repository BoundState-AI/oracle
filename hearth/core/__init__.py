#!/usr/bin/env python3
"""
Module: hearth.core
Purpose: Core engines namespace (spec v0.3 §3).

Phase 1 ships the scrubber only; valuation/signals/optimizer/fit/
identity are skeleton packages per §12.

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
