#!/usr/bin/env python3
"""
Module: dude.triggers.contracts
Purpose: Trigger Calibration Engine data contracts (trigger spec v1 §1–§2,
         amended by v1.1 R4/R5/R6/R10).

Shape discipline (R10): TriggerFamily is a SHARED SHAPE — it carries no
status and no confidence. Status and confidence live on
PersonalTriggerProfile only, the single source of truth. The status
vocabulary is Phase-1 capped (R4): there is deliberately NO
strongly_supported member, so nothing in the system can even represent a
status above self_report_supported.

Raw-data discipline (§13): TriggerCalibrationResponse preserves the raw
answer verbatim; the out-of-range flag is COMPUTED and stamped, never
trusted from the caller, and the raw score is never clamped. A response
captured while a crisis flag was active is force-quarantined (R6f).

Provenance discipline (mirrors PomItem._interpretation_is_never_fact):
match-derived evidence sources can never carry user-fact epistemic
status, and a profile whose only evidence is match-derived cannot exceed
candidate status (no closed loop, R4).

Safety Critical: False
Psychologically Critical: True — these contracts are where "the map of
what hurts him" lives; a shape defect here is a weaponizable artifact.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import Field, model_validator

from dude.data.base import DudeModel
from dude.data.enums import ConfidenceBand, TriggerCalibration
from dude.pom.contracts import EpistemicStatus

# Single-tenant Phase-1 identity, matching the POM seed identity used by
# dude.api. Multi-tenant scoping keeps the field mandatory everywhere.
DEFAULT_USER_ID = "joseph"


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TriggerFamilyStatus(str, Enum):
    """Profile status vocabulary (v1 §1, amended by R4).

    provisionally_supported is renamed self_report_supported to carry its
    provenance on its face, and strongly_supported is REMOVED: Phase 1
    caps at self_report_supported structurally — the cap cannot be
    bypassed because the value does not exist."""

    CANDIDATE = "candidate"
    CANDIDATE_WITH_LOW_SUPPORT = "candidate_with_low_support"
    SELF_REPORT_SUPPORTED = "self_report_supported"
    CONTRADICTED = "contradicted"
    RETIRED = "retired"


class FeatureType(str, Enum):
    REQUIRED = "required"
    AMPLIFIER = "amplifier"
    REDUCER = "reducer"
    EXCLUSION = "exclusion"
    CONTEXTUAL = "contextual"


class ProvenanceClass(str, Enum):
    """How a feature's presence is evidenced (R5). Performed legibility
    (a counterparty ACTING transparent) is not verifiable legibility (a
    documented scope, a written appeal path)."""

    INSTITUTIONAL_VERIFIABLE = "institutional_verifiable"
    INTERPERSONAL_PERFORMED = "interpersonal_performed"


class EvidenceSourceType(str, Enum):
    """v1 §1 source vocabulary + R7's case_resolution, R4's in-vivo
    confirmation, and §11's legacy migration marker."""

    DIRECT_USER_REPORT = "direct_user_report"
    CALIBRATION_RESPONSE = "calibration_response"
    MATCHED_PAIR_CONTRAST = "matched_pair_contrast"
    REPEATED_CASE_PATTERN = "repeated_case_pattern"
    ASSISTANT_HYPOTHESIS = "assistant_hypothesis"
    CLINICIAN_INPUT = "clinician_input"
    CASE_RESOLUTION = "case_resolution"
    IN_VIVO_CONFIRMATION = "in_vivo_confirmation"
    LEGACY_MANUAL_TRIGGER = "legacy_manual_trigger"


# Sources that originate in the matcher or the assistant. Excluded from
# ALL status math (R4 — no closed loop: matches can never feed the
# confidence that makes future matches easier).
MATCH_DERIVED_SOURCES = frozenset(
    {EvidenceSourceType.REPEATED_CASE_PATTERN, EvidenceSourceType.ASSISTANT_HYPOTHESIS}
)

# Epistemic statuses that assert user-vouched truth. A match-derived
# source carrying one of these is provenance collapse (v1 §1: "never
# convert an assistant interpretation into a user fact").
_USER_VOUCHED = frozenset(
    {
        EpistemicStatus.USER_STATED_FACT,
        EpistemicStatus.USER_REPORTED_EVENT,
        EpistemicStatus.USER_CONFIRMED_PATTERN,
    }
)


class SupportDirection(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    AMBIGUOUS = "ambiguous"


class EvidenceStrength(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class OverlapLevel(str, Enum):
    """R8: overlap levels are defined over CONFIRMED family matches only."""

    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class CalibrationDimension(str, Enum):
    """The matched-pair contrast dimensions (v1 §2)."""

    POWER = "power"
    RULES_LEGIBILITY = "rules_legibility"
    EXIT_CONSTRAINT = "exit_constraint"
    SCOPE_CLARITY = "scope_clarity"
    PAST_VS_IDENTITY = "past_vs_identity"
    VISIBILITY = "visibility"
    PROTECTIVE_ACCESS = "protective_access"
    TIMELINE_OPACITY = "timeline_opacity"


# De-identification floor (R6a): family labels/descriptions carry NO
# real-world anchors. Machine-checked for the anchors named in the spec;
# raw quotes live only in calibration response records.
REAL_WORLD_ANCHOR_TOKENS = ("nasa", "akashic", "1994", "mira")


class TriggerFeature(DudeModel):
    """One feature of a family shape (v1 §1). provenance_class is
    mandatory (R5): reducer handling depends on it."""

    id: str = Field(default_factory=_new_id)
    feature_slug: str
    description: str
    feature_type: FeatureType
    provenance_class: ProvenanceClass
    weight_hint: float | None = None


class TriggerFamily(DudeModel):
    """A shared trigger SHAPE (R10): slug, label, description, features.
    Deliberately no status and no confidence — those live on
    PersonalTriggerProfile only. prefilter_cues drive the deterministic
    pre-filter that decides candidate families before any LLM sees
    anything (R6b)."""

    id: str = Field(default_factory=_new_id)
    slug: str
    label: str
    description: str
    features: list[TriggerFeature] = Field(default_factory=list)
    prefilter_cues: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None

    @model_validator(mode="after")
    def _no_real_world_anchors(self) -> "TriggerFamily":
        text = f"{self.slug} {self.label} {self.description}".lower()
        hits = [t for t in REAL_WORLD_ANCHOR_TOKENS if t in text]
        if hits:
            raise ValueError(
                f"Family shape contains real-world anchors {hits} (R6a); "
                "anchors live only in calibration response records."
            )
        return self

    def feature_by_slug(self, slug: str) -> TriggerFeature | None:
        for feature in self.features:
            if feature.feature_slug == slug:
                return feature
        return None


class PersonalTriggerProfile(DudeModel):
    """THE single source of truth for status + confidence (R10). Carries
    the WIDEN/ATTEND calibration tag so a historically-accurate domain
    keeps attending after migration (R7)."""

    id: str = Field(default_factory=_new_id)
    user_id: str
    trigger_family_id: str
    family_slug: str
    status: TriggerFamilyStatus = TriggerFamilyStatus.CANDIDATE
    confidence_band: ConfidenceBand = ConfidenceBand.UNRESOLVED
    calibration: TriggerCalibration = TriggerCalibration.NEUTRAL
    evidence_source_types: list[EvidenceSourceType] = Field(default_factory=list)
    status_reason: str = ""
    notes: str = ""
    first_observed_at: datetime = Field(default_factory=_now)
    last_calibrated_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None

    @model_validator(mode="after")
    def _match_derived_caps_at_candidate(self) -> "PersonalTriggerProfile":
        # R4 no-closed-loop: a profile whose ONLY evidence is what the
        # matcher/assistant produced can never exceed candidate.
        sources = set(self.evidence_source_types)
        if (
            sources
            and sources <= MATCH_DERIVED_SOURCES
            and self.status is TriggerFamilyStatus.SELF_REPORT_SUPPORTED
        ):
            raise ValueError(
                "A profile supported only by repeated_case_pattern/"
                "assistant_hypothesis evidence cannot exceed candidate "
                "status (R4 — no closed loop)."
            )
        return self


class CaptureState(DudeModel):
    """State stamped on every calibration capture (R6f)."""

    crisis_flag_active: bool = False
    self_reported_state: str = ""


class CalibrationContext(DudeModel):
    """Structured capture context (v1 §1 'context', R6f)."""

    who_present: str = ""
    solicited_by: str = ""
    location: str = ""


class TriggerCalibrationResponse(DudeModel):
    """One raw calibration answer (v1 §1/§13). The raw answer is evidence;
    normalization is a derived transformation that never overwrites it."""

    id: str = Field(default_factory=_new_id)
    user_id: str
    prompt_id: str
    session_id: str
    raw_score: int
    declared_scale_min: int
    declared_scale_max: int
    out_of_range: bool = False
    raw_response_text: str
    clarification: str = ""
    context: CalibrationContext = Field(default_factory=CalibrationContext)
    state_at_capture: CaptureState = Field(default_factory=CaptureState)
    quarantined: bool = False
    quarantine_reason: str = ""
    revoked: bool = False
    revocation_reason: str = ""
    provenance: str = "direct_user_report"
    timestamp: datetime = Field(default_factory=_now)
    supersedes: str | None = None

    @model_validator(mode="after")
    def _stamp_range_and_quarantine(self) -> "TriggerCalibrationResponse":
        if self.declared_scale_min > self.declared_scale_max:
            raise ValueError("declared_scale_min exceeds declared_scale_max.")
        # §13: out_of_range is COMPUTED — stamped, never trusted, and the
        # raw score itself is preserved verbatim (never clamped).
        computed = not (
            self.declared_scale_min <= self.raw_score <= self.declared_scale_max
        )
        object.__setattr__(self, "out_of_range", computed)
        # R6f: crisis-time calibration is quarantined by construction —
        # the flag cannot be talked out of by the caller.
        if self.state_at_capture.crisis_flag_active and not self.quarantined:
            object.__setattr__(self, "quarantined", True)
            object.__setattr__(
                self,
                "quarantine_reason",
                "Captured while a crisis flag was active; provisional "
                "pending reconfirmation (R6f).",
            )
        return self

    def effective_score(self) -> int:
        """Derived, clamped view for MATH ONLY (§13: out-of-range raw
        scores never count at face value; the raw field is untouched)."""
        return min(max(self.raw_score, self.declared_scale_min), self.declared_scale_max)


class TriggerEvidence(DudeModel):
    """One provenance-typed evidence record for a family (v1 §1)."""

    id: str = Field(default_factory=_new_id)
    user_id: str
    trigger_family_id: str
    family_slug: str
    source_type: EvidenceSourceType
    epistemic_status: EpistemicStatus
    support_direction: SupportDirection
    strength: EvidenceStrength = EvidenceStrength.WEAK
    source_reference: str = ""
    timestamp: datetime = Field(default_factory=_now)
    supersedes: str | None = None

    @model_validator(mode="after")
    def _match_derived_is_never_user_fact(self) -> "TriggerEvidence":
        # Mirror of PomItem._interpretation_is_never_fact: the matcher and
        # the assistant cannot author user-vouched truth (v1 §1).
        if (
            self.source_type in MATCH_DERIVED_SOURCES
            and self.epistemic_status in _USER_VOUCHED
        ):
            raise ValueError(
                f"{self.source_type.value} evidence cannot carry "
                f"{self.epistemic_status.value}; assistant/matcher output "
                "is never a user fact (v1 §1)."
            )
        return self


class FeatureCitation(DudeModel):
    """One feature match with its exact case-text span (R5: the matcher
    cites the current case, never the calibration record)."""

    feature_slug: str
    span: str

    @model_validator(mode="after")
    def _span_required(self) -> "FeatureCitation":
        if not self.span.strip():
            raise ValueError("A feature citation requires a case-text span (R5).")
        return self


class SuspendedReducer(DudeModel):
    """A reducer the model proposed but policy suspended, with the visible
    reason (R5)."""

    feature_slug: str
    reason: str


class CaseTriggerAssessment(DudeModel):
    """A PROPOSAL that a case overlaps a family (R5): the matcher
    proposes, the user disposes. Calibration material is referenced by ID
    only — this contract has NO field that could carry calibration text
    or scores (R4/R6b), and the canary test enforces it end to end."""

    id: str = Field(default_factory=_new_id)
    case_id: str
    user_id: str
    trigger_family_id: str
    family_slug: str
    matched_features: list[FeatureCitation] = Field(default_factory=list)
    missing_features: list[str] = Field(default_factory=list)
    amplifiers_present: list[FeatureCitation] = Field(default_factory=list)
    reducers_present: list[FeatureCitation] = Field(default_factory=list)
    suspended_reducers: list[SuspendedReducer] = Field(default_factory=list)
    confidence_band: ConfidenceBand = ConfidenceBand.UNRESOLVED
    explanation: str = ""
    calibration_evidence_ids: list[str] = Field(default_factory=list)
    user_confirmed: bool = False
    user_denied: bool = False
    model_run_id: str
    created_at: datetime = Field(default_factory=_now)
    supersedes: str | None = None

    @model_validator(mode="after")
    def _one_disposition(self) -> "CaseTriggerAssessment":
        if self.user_confirmed and self.user_denied:
            raise ValueError("An assessment cannot be both confirmed and denied.")
        return self


class CalibrationPrompt(DudeModel):
    """One calibration scenario prompt (v1 §2). Negative controls are the
    low arm of a matched pair — a scenario expected to score low."""

    id: str = Field(default_factory=_new_id)
    prompt_slug: str
    text: str
    family_slug: str
    feature_slug: str | None = None
    dimension: CalibrationDimension | None = None
    is_negative_control: bool = False
    pair_id: str | None = None
    created_at: datetime = Field(default_factory=_now)


class CalibrationPair(DudeModel):
    """A matched pair varying exactly one dimension (v1 §2)."""

    id: str = Field(default_factory=_new_id)
    family_slug: str
    dimension: CalibrationDimension
    high_arm_prompt_id: str
    low_arm_prompt_id: str
    created_at: datetime = Field(default_factory=_now)


class PairContrastResult(DudeModel):
    """The derived contrast over one pair (v1 §2). Paired answers are
    never averaged; a latent mechanism is inferred ONLY when the contrast
    supports it, and always as a working hypothesis."""

    id: str = Field(default_factory=_new_id)
    pair_id: str
    family_slug: str
    high_response_id: str
    low_response_id: str
    high_effective: int
    low_effective: int
    contrast_supported: bool
    inferred_mechanism_slug: str | None = None
    epistemic_status: EpistemicStatus = EpistemicStatus.WORKING_HYPOTHESIS
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _mechanism_needs_contrast(self) -> "PairContrastResult":
        if self.inferred_mechanism_slug and not self.contrast_supported:
            raise ValueError(
                "A latent mechanism may be inferred only when the contrast "
                "supports it (v1 §2 — no blind averaging)."
            )
        if self.epistemic_status in _USER_VOUCHED:
            raise ValueError(
                "A pair contrast is a derived inference; it is never a "
                "user-vouched fact (v1 §2)."
            )
        return self


class LegacyTriggerLink(DudeModel):
    """Migration record for one legacy TriggerPattern (v1 §11, R9). A
    superseded legacy trigger is inert whenever its family is assessed;
    legacy historical matches stay audit-only, never TriggerEvidence."""

    id: str = Field(default_factory=_new_id)
    legacy_trigger_id: str
    legacy_name: str
    superseded_by_family_id: str
    superseded_by_family_slug: str
    legacy_recorded_at: datetime
    migrated_at: datetime = Field(default_factory=_now)
    note: str = ""
