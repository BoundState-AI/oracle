#!/usr/bin/env python3
"""
Module: dude.triggers
Purpose: The Trigger Calibration Engine (trigger spec v1, amended by the
         v1.1 R1-R11 binding resolutions).

Import surface only. The load-bearing invariants live in the submodules:
contracts (shape/status discipline), status (R4 promotion/demotion),
assess (R5/R6/R8 matching + policy), distortion (R3 vocabulary),
migrate (R9 legacy migration), seed (R6 custody import), store
(append-only persistence).

Safety Critical: False
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

from dude.triggers.contracts import (
    DEFAULT_USER_ID,
    CalibrationDimension,
    CalibrationPair,
    CalibrationPrompt,
    CaseTriggerAssessment,
    EvidenceSourceType,
    EvidenceStrength,
    FeatureCitation,
    FeatureType,
    LegacyTriggerLink,
    OverlapLevel,
    PairContrastResult,
    PersonalTriggerProfile,
    ProvenanceClass,
    SupportDirection,
    SuspendedReducer,
    TriggerCalibrationResponse,
    TriggerEvidence,
    TriggerFamily,
    TriggerFamilyStatus,
    TriggerFeature,
)
from dude.triggers.store import TriggerBundle, TriggerStore

__all__ = [
    "CalibrationDimension",
    "CalibrationPair",
    "CalibrationPrompt",
    "CaseTriggerAssessment",
    "DEFAULT_USER_ID",
    "EvidenceSourceType",
    "EvidenceStrength",
    "FeatureCitation",
    "FeatureType",
    "LegacyTriggerLink",
    "OverlapLevel",
    "PairContrastResult",
    "PersonalTriggerProfile",
    "ProvenanceClass",
    "SupportDirection",
    "SuspendedReducer",
    "TriggerBundle",
    "TriggerCalibrationResponse",
    "TriggerEvidence",
    "TriggerFamily",
    "TriggerFamilyStatus",
    "TriggerFeature",
    "TriggerStore",
]
