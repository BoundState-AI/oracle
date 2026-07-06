#!/usr/bin/env python3
"""
Module: dude.pom.contracts
Purpose: Typed POM records (build instruction §1–§10).

Epistemic statuses are never collapsed: a user-reported fact and an
assistant interpretation are not equivalent, and the contract itself
refuses an assistant interpretation marked user-confirmed — promotion
requires a superseding record with a new status, never a flag flip.

WorkingModel carries the MODEL-LAG structure: components with current
supporting and contradicting evidence, plus when the model was adaptive.
Model lag is not "cognitive distortion" — it is a predictive model that
may still be optimized for a world state that no longer fully exists.

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

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import Field, model_validator

from dude.data.base import DudeModel
from dude.data.enums import ConfidenceBand


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AllowedUse(str, Enum):
    """The ONLY vocabulary by which POM knowledge reaches an analysis.
    There is deliberately no evidence-class member (§4, §17)."""

    COMMUNICATION_ADAPTATION = "communication_adaptation"
    TRIGGER_CONTEXT = "trigger_context"
    UNCERTAINTY_WIDENING = "uncertainty_widening"
    GROUNDING = "grounding"
    SAFETY_CONTEXT = "safety_context"
    ACTION_CONSTRAINT = "action_constraint"
    STRATEGIC_CONTEXT = "strategic_context"
    RELATIONSHIP_CONTEXT = "relationship_context"
    CASE_RETRIEVAL = "case_retrieval"


# The banned vocabulary (§4). These are names an attacker (or a lazy
# integration) might pass as a use; the policy engine raises on ALL of
# them for EVERY item — biography is never evidence (§5, §17).
PROHIBITED_USES = frozenset(
    {
        "discount_current_observation",
        "infer_current_threat_false",
        "infer_current_threat_true",
        "support_current_hypothesis",
        "contradict_current_hypothesis",
        "diagnose_third_party",
        "employment_inference",
        "cross_case_corroboration",
    }
)


class PomCategory(str, Enum):
    IDENTITY = "identity"
    COMMUNICATION_PREFERENCE = "communication_preference"
    TRIGGER_PATTERN = "trigger_pattern"
    REASONING_PATTERN = "reasoning_pattern"
    PROTECTIVE_FACTOR = "protective_factor"
    GROUNDING_COORDINATE = "grounding_coordinate"
    RELATIONSHIP_CONTEXT = "relationship_context"
    LIFE_PRIORITY = "life_priority"
    STRATEGIC_CONTEXT = "strategic_context"
    BOUNDARY_PATTERN = "boundary_pattern"
    DECISION_PREFERENCE = "decision_preference"
    WORKING_MODEL = "working_model"
    HISTORICAL_CASE_CONTEXT = "historical_case_context"


class EpistemicStatus(str, Enum):
    USER_STATED_FACT = "user_stated_fact"
    USER_REPORTED_EVENT = "user_reported_event"
    USER_CONFIRMED_PATTERN = "user_confirmed_pattern"
    ASSISTANT_INTERPRETATION = "assistant_interpretation"
    WORKING_HYPOTHESIS = "working_hypothesis"
    DERIVED_SUMMARY = "derived_summary"


# Statuses that import as UNCONFIRMED, always (§13). Preserve uncertainty.
UNCONFIRMED_ON_IMPORT = frozenset(
    {
        EpistemicStatus.ASSISTANT_INTERPRETATION,
        EpistemicStatus.WORKING_HYPOTHESIS,
        EpistemicStatus.DERIVED_SUMMARY,
    }
)


class Temporal(str, Enum):
    """Validity class (§10). HISTORICAL items (e.g. financial snapshots)
    exist as provenance and are excluded from operational retrieval."""

    DURABLE = "durable"
    WINDOWED = "windowed"
    HISTORICAL = "historical"


class SourceArtifact(DudeModel):
    """Immutable seed document (§1). Versions supersede, never overwrite."""

    id: str = Field(default_factory=_new_id)
    user_id: str
    title: str
    source_type: str = "markdown"
    content: str
    content_sha256: str = ""
    created_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _stamp_hash(self) -> "SourceArtifact":
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 and self.content_sha256 != digest:
            raise ValueError("content_sha256 does not match content.")
        object.__setattr__(self, "content_sha256", digest)
        return self


class PomItem(DudeModel):
    """One atomic, provenance-linked, policy-constrained knowledge record
    (§2). No item exists without a source artifact and excerpt."""

    id: str = Field(default_factory=_new_id)
    user_id: str
    source_artifact_id: str
    source_section: str = ""
    source_excerpt: str
    category: PomCategory
    statement: str
    epistemic_status: EpistemicStatus
    confidence_band: ConfidenceBand = ConfidenceBand.UNRESOLVED
    sensitivity: str = "normal"
    temporal: Temporal = Temporal.DURABLE
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    allowed_uses: list[AllowedUse] = Field(default_factory=list)
    case_ref: str | None = None
    user_confirmed: bool = False
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _interpretation_is_never_fact(self) -> "PomItem":
        # §3: never promote assistant language into user fact. Promotion is
        # a superseding record with a NEW status — a confirmed record whose
        # status still says assistant_interpretation is a contradiction.
        if (
            self.epistemic_status in UNCONFIRMED_ON_IMPORT
            and self.user_confirmed
        ):
            raise ValueError(
                f"{self.epistemic_status.value} cannot be user_confirmed; "
                "confirm by superseding with user_confirmed_pattern (§3/§13)."
            )
        return self


class ModelComponent(DudeModel):
    """One component of a working model, with CURRENT evidence on both
    sides — the unit the model-lag check evaluates."""

    name: str
    currently_supporting: list[str] = Field(default_factory=list)
    currently_contradicting: list[str] = Field(default_factory=list)


class WorkingModel(DudeModel):
    """First-class, revisable, falsifiable working model (§7) with the
    model-lag structure: historical basis, when it was adaptive, and
    per-component current evidence."""

    id: str = Field(default_factory=_new_id)
    user_id: str
    name: str
    description: str
    historical_basis: list[str] = Field(default_factory=list)
    adaptive_when: str | None = None
    components: list[ModelComponent] = Field(default_factory=list)
    confidence_band: ConfidenceBand = ConfidenceBand.UNRESOLVED
    user_confirmed: bool = False
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None


class GroundingCoordinate(DudeModel):
    """A grounding phrase with activation contexts (§8). Never deployed
    generically — surfacing requires an allowed context."""

    id: str = Field(default_factory=_new_id)
    user_id: str
    phrase: str
    meaning: str
    activation_contexts: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    user_confirmed: bool = False
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None


class RetrievalRecord(DudeModel):
    """The audit answer to: why did you bring this personal fact into
    this analysis? (§12) Written for EVERY retrieved item."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    pom_item_id: str
    analysis_run_id: str
    retrieval_reason: str
    allowed_use: AllowedUse
    retrieved_at: datetime = Field(default_factory=_now)
