#!/usr/bin/env python3
"""
Module: hearth.core.scrubber
Purpose: DocScrubber — the Kelly module (spec v0.3 §3.3, §12 P1-B).

Pipeline: text extraction → clause segmentation → deterministic micro-rule
match → findings. The LLM stage is a stubbed protocol (ClauseAnalyzer) in
Phase 1. Fails CLOSED end to end.

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

from hearth.core.scrubber.analyzer import ClauseAnalyzer, NullClauseAnalyzer
from hearth.core.scrubber.engine import ScrubberError, ScrubRun, refusal_run, scrub_document
from hearth.core.scrubber.extraction import ExtractionError, extract_text
from hearth.core.scrubber.matcher import MatchSpecError
from hearth.core.scrubber.segmentation import Clause, SegmentationError, segment_clauses

__all__ = [
    "Clause",
    "ClauseAnalyzer",
    "ExtractionError",
    "MatchSpecError",
    "NullClauseAnalyzer",
    "ScrubberError",
    "ScrubRun",
    "SegmentationError",
    "extract_text",
    "refusal_run",
    "scrub_document",
    "segment_clauses",
]
