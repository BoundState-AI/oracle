#!/usr/bin/env python3
"""
Module: dude.data
Purpose: Pydantic v2 data contracts for DUDE (spec v0.2).

Single import surface. All models inherit DudeModel (extra="forbid";
unknown keys are defects, not extensions).

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

from dude.data.actions import ActionEvaluation, ActionOption, ActionRecommendation
from dude.data.base import DudeModel
from dude.data.case import (
    AnalysisRun,
    Case,
    CumulativePattern,
    Deadline,
    HypothesisDelta,
    Refusal,
    ScopeFingerprint,
)
from dude.data.enums import (
    CHRONIC_SAFETY_CATEGORIES,
    CaseStatus,
    ConfidenceBand,
    CreatedBy,
    GateMode,
    HarmClass,
    HypothesisArchetype,
    OutcomeProvenance,
    SafetyCategory,
    SourceType,
    TriggerCalibration,
    TriggerConfidence,
    UnknownImportance,
)
from dude.data.evidence import (
    Artifact,
    Capture,
    Event,
    Interpretation,
    Observation,
    Outcome,
    Provenance,
    Unknown,
)
from dude.data.hypotheses import AdversaryAnnotation, Hypothesis
from dude.data.safety import (
    CrisisResource,
    SafetyEvent,
    SafetyFlag,
    SafetyScanResult,
)
from dude.data.triggers import (
    AdjustmentContribution,
    AdjustmentEffect,
    ConfidenceAdjustment,
    TriggerMatch,
    TriggerPattern,
)

__all__ = [
    "ActionEvaluation",
    "ActionOption",
    "ActionRecommendation",
    "AdjustmentContribution",
    "AdjustmentEffect",
    "AdversaryAnnotation",
    "AnalysisRun",
    "Artifact",
    "CHRONIC_SAFETY_CATEGORIES",
    "Capture",
    "Case",
    "CaseStatus",
    "ConfidenceAdjustment",
    "ConfidenceBand",
    "CreatedBy",
    "CrisisResource",
    "CumulativePattern",
    "Deadline",
    "DudeModel",
    "Event",
    "GateMode",
    "HarmClass",
    "Hypothesis",
    "HypothesisArchetype",
    "HypothesisDelta",
    "Interpretation",
    "Observation",
    "Outcome",
    "OutcomeProvenance",
    "Provenance",
    "Refusal",
    "SafetyCategory",
    "SafetyEvent",
    "SafetyFlag",
    "SafetyScanResult",
    "ScopeFingerprint",
    "SourceType",
    "TriggerCalibration",
    "TriggerConfidence",
    "TriggerMatch",
    "TriggerPattern",
    "Unknown",
    "UnknownImportance",
]
