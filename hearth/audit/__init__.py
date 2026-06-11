#!/usr/bin/env python3
"""
Module: hearth.audit
Purpose: Per-run reproducibility artifacts (spec v0.3 §11).

Emission and verification of immutable AuditArtifacts for every
financially-critical run.

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
