#!/usr/bin/env python3
"""
Module: dude.data.enums
Purpose: Shared enums for the DUDE contracts (spec v0.2 §1, §3, §5).

Enums live in one module so the vocabulary is defined exactly once; every
contract and engine imports from here. External confidence is ALWAYS one of
ConfidenceBand's five values (v0.2 I13) — internal floats never render.

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

from enum import Enum


class ConfidenceBand(str, Enum):
    """External confidence vocabulary (v0.1 §18; v0.2 I13)."""

    SUPPORTED = "supported"
    PLAUSIBLE = "plausible"
    WEAKLY_SUPPORTED = "weakly_supported"
    UNRESOLVED = "unresolved"
    CONTRADICTED = "contradicted"


class GateMode(str, Enum):
    """Analysis gate outcomes (v0.2 §3)."""

    NEW_EVIDENCE = "new_evidence"
    NEW_HYPOTHESIS_REANALYSIS = "new_hypothesis_reanalysis"
    SCOPE_CHANGE = "scope_change"
    NO_NEW_DATA = "no_new_data"
    # WHY: "no new data, no new analysis" presumes the prior analysis
    # actually ran. A prior run with refused passes is incomplete; re-running
    # it is completion, not recomputation, and must never be gated.
    INCOMPLETE_PRIOR_RERUN = "incomplete_prior_rerun"


class CaseStatus(str, Enum):
    """Stored lifecycle states (v0.1 §10 minus WAITING_FOR_DATA, which is
    computed from the gate, never stored — v0.2 spec, review A15)."""

    UNSTRUCTURED = "unstructured"
    STRUCTURED = "structured"
    ACTIVE = "active"
    ACTION_SELECTED = "action_selected"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class HypothesisArchetype(str, Enum):
    """Hypothesis slots (v0.1 Stage 6 + the mandatory adversarial-cause
    archetype added by v0.2 I9)."""

    USER_FAVORED = "user_favored"
    BORING = "boring"
    MIXED_CAUSE = "mixed_cause"
    MISSING_VARIABLE = "missing_variable"
    ADVERSARIAL_CAUSE = "adversarial_cause"
    OTHER = "other"


class HarmClass(str, Enum):
    """Stakes classification per hypothesis (v0.2 I9)."""

    NONE = "none"
    RECOVERABLE = "recoverable"
    CATASTROPHIC_TO_USER = "catastrophic_to_user"


class SafetyCategory(str, Enum):
    """Safety floor categories (v0.2 §5)."""

    SELF_HARM = "self_harm"
    VIOLENCE_THREAT = "violence_threat"
    CHILD_DANGER = "child_danger"
    MEDICAL_EMERGENCY = "medical_emergency"
    STALKING_PATTERN = "stalking_pattern"
    COERCIVE_CONTROL = "coercive_control"
    LEGAL_DEADLINE = "legal_deadline"


# Acute categories bypass everything; chronic categories additionally feed
# the course-of-conduct accrual engine (v0.2 §5, review A3/A4).
CHRONIC_SAFETY_CATEGORIES = frozenset(
    {SafetyCategory.STALKING_PATTERN, SafetyCategory.COERCIVE_CONTROL}
)


class SourceType(str, Enum):
    """Provenance source vocabulary (v0.1 §31)."""

    USER_STATEMENT = "user_statement"
    EMAIL = "email"
    SCREENSHOT = "screenshot"
    DOCUMENT = "document"
    VOICE = "voice"
    EXTERNAL_SOURCE = "external_source"
    PRIOR_OBSERVATION = "prior_observation"
    SILENCE_CHECKPOINT = "silence_checkpoint"


class CreatedBy(str, Enum):
    """Who authored a record. User material enters the fingerprint;
    engine/model material never does (v0.2 I5)."""

    USER = "user"
    ENGINE = "engine"
    MODEL = "model"
    MODEL_STUB = "model_stub"


class OutcomeProvenance(str, Enum):
    """Outcome labels need the same discipline as everything else
    (review A14): calibration may only generalize from VERIFIED."""

    VERIFIED = "verified"
    USER_REPORTED = "user_reported"
    ASSUMED = "assumed"


class TriggerCalibration(str, Enum):
    """Per-trigger calibration tag (v0.2 I7; review A6)."""

    OVERFIRES = "overfires"
    NEUTRAL = "neutral"
    HISTORICALLY_ACCURATE = "historically_accurate"


class TriggerConfidence(str, Enum):
    """How a trigger entered the profile. clinician_supplied is removed
    from Phase 1 (v0.2 §6 — no clinical workflow in any surface)."""

    USER_STATED = "user_stated"
    INFERRED = "inferred"


class UnknownImportance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
