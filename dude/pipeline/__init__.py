#!/usr/bin/env python3
"""
Module: dude.pipeline
Purpose: Analysis orchestration (spec v0.2 §2).

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

from dude.pipeline.engine import AnalysisResult, analyze, capture

__all__ = ["AnalysisResult", "analyze", "capture"]
