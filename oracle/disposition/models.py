#!/usr/bin/env python3
"""
Module: oracle.disposition.models
Purpose: Pydantic v2 data contracts for disposition units, locators, evidence,
         acceptance records, levy manifests, scope, and capability (§7).

All models use extra="forbid". Every record carries schema_version and
rule_version. Acceptance records express append-only semantics via
immutable=True and supersedes chaining.

Safety Critical: advisory-only per spec D-1

__safety_critical__: bool = False  # advisory-only per D-1 (S1 is pure data + state)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from types import MappingProxyType
from typing import Annotated, Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from oracle.disposition.codes import (
    DISPOSITION_CODES,
    DispositionCode,
    OPENSubReason,
    ProposalBand,
    WorkflowStateValue,
)  # WorkflowStateValue is the single source of truth (codes.py)

LOGGER = logging.getLogger("oracle.disposition.models")


# Internal token used ONLY by transition_unit to authorize construction of
# non-"proposed" workflow_state values. Public construction and model_copy
# must never set this; the validator below enforces it.
_ALLOW_TRANSITION_STATE: ContextVar[bool] = ContextVar("_ALLOW_TRANSITION_STATE", default=False)

# Narrow token set ONLY by the release gate (release.py) when it has evaluated
# a unit (or package) against a full ReleaseContext and is about to construct
# the release_approved successor. This is the controlled path for S1a.
# Direct construction and un-audited paths must still raise.
_ALLOW_RELEASED_CONSTRUCTION: ContextVar[bool] = ContextVar("_ALLOW_RELEASED_CONSTRUCTION", default=False)


def _set_release_construction_token() -> Any:
    """Internal: return a token that must be reset. Used only by release.py."""
    return _ALLOW_RELEASED_CONSTRUCTION.set(True)


def _reset_release_construction_token(token: Any) -> None:
    _ALLOW_RELEASED_CONSTRUCTION.reset(token)


def _freeze_value(v: Any) -> Any:
    """Recursively freeze containers for High #2 immutability.

    dict -> MappingProxyType (shallow on keys, recursive on values)
    list/tuple -> tuple of recursively frozen items
    Other values pass through unchanged.
    """
    if isinstance(v, dict):
        return MappingProxyType({k: _freeze_value(vv) for k, vv in v.items()})
    if isinstance(v, (list, tuple)):
        return tuple(_freeze_value(x) for x in v)
    return v


def _require_stripped_nonblank(v: Optional[str], field_name: str) -> Optional[str]:
    """Shared validator: whitespace-only strings are not valid for required text fields.

    Returns the stripped value when non-blank, or None (caller decides if required).
    Raises ValueError for whitespace-only or empty inputs when a value is present.
    """
    if v is None:
        return None
    if not isinstance(v, str):
        v = str(v)
    stripped = v.strip()
    if len(stripped) == 0:
        # whitespace-only or empty is never acceptable for these fields
        raise ValueError(f"{field_name} must be a non-blank string (whitespace-only rejected)")
    return stripped

# ---------------------------------------------------------------------------
# Versioning contract (every persisted record carries these)
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "disposition/v1"
RULE_VERSION: str = "0.5.0"  # Tracks the governing spec version baseline


class VersionedModel(BaseModel):
    """Base for all disposition records that must carry versioning.

    Immutable (frozen) records use frozen=True; mutation is expressed by
    creating successor records linked via supersedes (append-only).

    High #4: model_copy and copy are disallowed on domain records to close
    the construction bypass. Callers must use transition_unit (for workflow_state)
    or construct fresh records (for new proposed units / new acceptance chains).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=SCHEMA_VERSION, min_length=1)
    rule_version: str = Field(default=RULE_VERSION, min_length=1)

    def model_copy(self, *args: Any, **kwargs: Any) -> "VersionedModel":  # type: ignore[override]
        """High #4: forbid public model_copy on domain records.

        Use transition_unit to change workflow_state, or construct a fresh
        record for new data. model_copy would bypass the proposed-only guard
        and the transition authorization path.
        """
        raise TypeError(
            f"{self.__class__.__name__}.model_copy is disallowed on domain records. "
            "Use transition_unit for state changes or construct a new record."
        )

    def copy(self, *args: Any, **kwargs: Any) -> "VersionedModel":  # type: ignore[override]
        """High #4: also block the deprecated .copy() alias."""
        raise TypeError(
            f"{self.__class__.__name__}.copy is disallowed on domain records. "
            "Use transition_unit for state changes or construct a new record."
        )

    @classmethod
    def model_construct(cls, *args: Any, **kwargs: Any) -> "VersionedModel":  # type: ignore[override]
        """High #4: forbid model_construct on domain records.

        model_construct bypasses all validators and the proposed-only guard.
        All construction of DispositionUnit (including successors) must go
        through the normal validated path (DispositionUnit(...) or model_validate).
        The single internal exception is inside transition_unit under the
        authorization token + model_validate.
        """
        raise TypeError(
            f"{cls.__name__}.model_construct is disallowed on domain records. "
            "All construction must be validated. Use transition_unit for state changes."
        )


# ---------------------------------------------------------------------------
# Locator and Evidence
# ---------------------------------------------------------------------------

class Locator(VersionedModel):
    """Precise location of a disposition unit within a levied standard (§7)."""

    standard: str = Field(min_length=1)
    revision: str = Field(min_length=1)  # The LEVIED revision from the levy manifest
    section: str = Field(min_length=1)
    page: int = Field(ge=1)

    @field_validator("standard", "revision", "section", mode="before")
    @classmethod
    def _strip_nonblank_locator_fields(cls, v: Any, info) -> str:
        name = info.field_name
        stripped = _require_stripped_nonblank(v, name)
        if stripped is None or len(stripped) == 0:
            raise ValueError(f"{name} must be a non-blank string (whitespace-only rejected)")
        return stripped


class EvidenceEntry(VersionedModel):
    """One cited artifact supporting a CW or MI disposition (§7)."""

    doc_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    match_score: float = Field(ge=0.0, le=1.0)

    @field_validator("doc_id", "revision", "locator", mode="before")
    @classmethod
    def _strip_nonblank(cls, v: Any, info) -> str:
        name = info.field_name
        stripped = _require_stripped_nonblank(v, name)
        if stripped is None or len(stripped) == 0:
            raise ValueError(f"{name} must be a non-blank string (whitespace-only rejected)")
        return stripped


# ---------------------------------------------------------------------------
# Acceptance (append-only, required for release-eligible MI/EX)
# ---------------------------------------------------------------------------

AcceptanceStatus = Literal["proposed", "accepted", "rejected", "expired"]


class ApprovedScope(VersionedModel):
    """Machine-checkable scope of an acceptance.

    Immutable container types (tuples) enforce append-only semantics.
    Changes are expressed by creating successor AcceptanceRecords via supersedes.
    """

    configurations: tuple[str, ...] = Field(default_factory=tuple)
    part_classes: tuple[str, ...] = Field(default_factory=tuple)
    valid_from: str = Field(min_length=1)
    valid_to: Optional[str] = None


class AcceptanceRecord(VersionedModel):
    """
    Customer acceptance record for MI/EX dispositions.

    Per §7.1: immutable append-only semantics. `immutable` is a literal True
    sentinel. `supersedes` chains to a prior record ID when this replaces one.
    A unit is release-eligible only when status=="accepted", valid window
    covers the run, and approved_scope matches the disposition context.

    The model is frozen; callers obtain a new record (linked via supersedes)
    rather than mutating an existing one.

    Medium #5 (Atlas R2): every acceptance carries a stable `id`. When creating
    a replacement, use create_successor() so that supersedes is forced to the
    prior id and the new id is distinct.
    """

    id: str = Field(min_length=1)
    status: AcceptanceStatus
    customer_authority: str = Field(min_length=1)
    approval_artifact: str = Field(min_length=1)
    approved_scope: ApprovedScope
    supersedes: Optional[str] = None
    immutable: Literal[True] = True

    @field_validator("id", "customer_authority", "approval_artifact", mode="before")
    @classmethod
    def _strip_nonblank_authority_fields(cls, v: Any, info) -> str:
        name = info.field_name
        stripped = _require_stripped_nonblank(v, name)
        if stripped is None or len(stripped) == 0:
            raise ValueError(f"{name} must be a non-blank string (whitespace-only rejected)")
        return stripped

    @model_validator(mode="after")
    def _reject_self_supersedes(self) -> "AcceptanceRecord":
        """Medium #5: an acceptance cannot supersede itself."""
        if self.supersedes is not None and self.supersedes == self.id:
            raise ValueError("AcceptanceRecord.supersedes cannot equal its own id")
        return self

    @classmethod
    def create_successor(
        cls,
        prior: "AcceptanceRecord",
        *,
        status: AcceptanceStatus,
        customer_authority: str,
        approval_artifact: str,
        approved_scope: ApprovedScope,
        schema_version: Optional[str] = None,
        rule_version: Optional[str] = None,
    ) -> "AcceptanceRecord":
        """Medium #5: create a replacement that correctly chains via supersedes.

        Forces supersedes=prior.id and generates a distinct successor id.
        The caller supplies the new content (status, authority, artifact, scope).
        A simple unique suffix strategy is used for the new id.
        """
        if prior is None:
            raise ValueError("create_successor requires a prior AcceptanceRecord")
        # Produce a distinct id that is still traceable
        new_id = f"{prior.id}:succ"
        # If that collides in some caller reuse pattern, append a tiny nonce.
        # For deterministic tests we keep it simple and stable.
        return cls(
            id=new_id,
            status=status,
            customer_authority=customer_authority,
            approval_artifact=approval_artifact,
            approved_scope=approved_scope,
            supersedes=prior.id,
            schema_version=schema_version or prior.schema_version,
            rule_version=rule_version or prior.rule_version,
        )


# ---------------------------------------------------------------------------
# Scope and Capability (intake)
# ---------------------------------------------------------------------------

ScopeType = Literal["policy", "physical_impossibility", "derived"]


class CapabilityModelEntry(VersionedModel):
    """One declared physical capability with evidence basis (§3.1)."""

    id: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    physically_possible: bool
    basis: str = Field(min_length=1)
    basis_evidence: Optional[str] = None  # pointer to process spec / prior run


class ScopeDeclaration(VersionedModel):
    """
    A scope declaration that can render units NA (§3).

    - policy: business/qualification choice (can still be MI via zero-limit)
    - physical_impossibility: must cite capability_ref with physically_possible=false
      and that capability must carry basis_evidence (else fails closed to human)
    - derived: minted by §11.1 propagation from accepted exceptions
    """

    id: str = Field(min_length=1)
    declaration: str = Field(min_length=1)
    type: ScopeType
    capability_ref: Optional[str] = None  # REQUIRED for physical_impossibility
    dependency: Optional[str] = None
    source: str = Field(min_length=1)

    # Medium #6 (Atlas R2): derived declarations MUST record the provenance
    # of the accepted exception/case that produced them (§3.1).
    # Required when type == "derived".
    derived_from_acceptance_artifact: Optional[str] = None
    derived_from_unit_id: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_physical_impossibility_capability_ref(self) -> "ScopeDeclaration":
        """Medium #4 (model level): physical_impossibility requires nonblank capability_ref.

        The cross-check that the referenced CapabilityModelEntry has
        physically_possible=False and a non-empty basis_evidence is performed
        by validate_physical_impossibility_declaration (intake/aggregate validator)
        because it requires the capability catalog.
        """
        if self.type == "physical_impossibility":
            if not self.capability_ref or not self.capability_ref.strip():
                raise ValueError(
                    "physical_impossibility scope declarations require a nonblank capability_ref (§3.1)"
                )
        return self

    @model_validator(mode="after")
    def _enforce_derived_provenance(self) -> "ScopeDeclaration":
        """Medium #6 (Atlas R2): derived declarations require provenance.

        Per §3.1, a derived scope declaration is minted from an accepted
        exception. The caller must supply either the acceptance artifact id
        or the unit_id of the originating exception.
        """
        if self.type == "derived":
            has_art = bool(self.derived_from_acceptance_artifact and self.derived_from_acceptance_artifact.strip())
            has_unit = bool(self.derived_from_unit_id and self.derived_from_unit_id.strip())
            if not (has_art or has_unit):
                raise ValueError(
                    "derived scope declarations require derived_from_acceptance_artifact "
                    "or derived_from_unit_id (§3.1)"
                )
        return self


def validate_physical_impossibility_declaration(
    decl: ScopeDeclaration,
    capabilities: dict[str, CapabilityModelEntry],
) -> None:
    """
    Medium #4: Intake/aggregate validator for physical_impossibility.

    Requires that decl.capability_ref points to a capability that:
      - has physically_possible == False
      - has a non-empty basis_evidence

    If the referenced capability is missing, physically_possible=True, or lacks
    basis_evidence, raises ValueError (fails closed to human adjudication per §3.1).
    Non-physical_impossibility declarations are no-ops.
    """
    if decl.type != "physical_impossibility":
        return

    ref = (decl.capability_ref or "").strip()
    if not ref:
        # Model validator already guards this, but belt-and-suspenders:
        raise ValueError("physical_impossibility requires capability_ref")

    cap = capabilities.get(ref)
    if cap is None:
        raise ValueError(
            f"physical_impossibility capability_ref {ref!r} not found in capability catalog"
        )
    if cap.physically_possible is not False:
        raise ValueError(
            f"physical_impossibility requires referenced capability {ref!r} "
            f"with physically_possible=False; got {cap.physically_possible}"
        )
    if not cap.basis_evidence or not str(cap.basis_evidence).strip():
        raise ValueError(
            f"physical_impossibility capability {ref!r} lacks basis_evidence (§3.1); "
            "fails closed to human adjudication"
        )


# ---------------------------------------------------------------------------
# Levy manifest (immutable run pin)
# ---------------------------------------------------------------------------

class LevyManifestEntry(VersionedModel):
    """One document captured in the levy manifest.

    Immutable (frozen via VersionedModel). Changes are expressed by
    creating a successor LevyManifest linked via a new run or superseding
    record rather than mutation.

    Medium #4 / Atlas R2: every entry must be complete (effective_date required)
    so the run has a usable immutable pin of the exact levied revision.
    """

    doc_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    effective_date: str = Field(min_length=1)  # REQUIRED for a usable levy pin
    source: str = Field(min_length=1)
    overlay_precedence: Optional[int] = None

    @field_validator("doc_id", "revision", "effective_date", "source", mode="before")
    @classmethod
    def _strip_nonblank_levy_entry(cls, v: Any, info) -> str:
        """Medium #4: levy entries are provenance-critical; whitespace-only is rejected."""
        name = info.field_name
        stripped = _require_stripped_nonblank(v, name)
        if stripped is None or len(stripped) == 0:
            raise ValueError(f"{name} must be a non-blank string (whitespace-only rejected)")
        return stripped


class LevyManifest(VersionedModel):
    """Immutable pin of exactly what was levied for a run (§1.1, §7.1).

    The documents container is an immutable tuple. Mutation is represented
    by creating a new LevyManifest (new run_id/levied_at) rather than editing.

    Medium #4: at least one complete document entry is required. A run with
    an empty manifest cannot establish that dispositions were computed
    against the levied revisions.
    """

    run_id: str = Field(min_length=1)
    levied_at: str = Field(min_length=1)
    documents: tuple[LevyManifestEntry, ...] = Field(min_length=1)  # at least one entry

    @field_validator("run_id", "levied_at", mode="before")
    @classmethod
    def _strip_nonblank_levy_manifest(cls, v: Any, info) -> str:
        """Medium #4: run_id/levied_at are provenance-critical; whitespace-only is rejected."""
        name = info.field_name
        stripped = _require_stripped_nonblank(v, name)
        if stripped is None or len(stripped) == 0:
            raise ValueError(f"{name} must be a non-blank string (whitespace-only rejected)")
        return stripped


def validate_locator_covered_by_manifest(locator: Locator, manifest: LevyManifest) -> None:
    """Medium #4 / Atlas R2: pure validation that a unit's locator is covered by the run manifest.

    The locator's (standard, revision) must match one of the levied documents exactly.
    This is a structural pin check at the aggregate/run boundary; it does not
    perform section-level resolution.

    Raises ValueError if no matching document entry is found.
    """
    for d in manifest.documents:
        if d.doc_id == locator.standard and d.revision == locator.revision:
            return
    raise ValueError(
        f"Locator standard={locator.standard!r} revision={locator.revision!r} "
        f"is not covered by the levy manifest (run_id={manifest.run_id})"
    )


# WorkflowStateValue is the single source of truth imported from codes.py.
# (Consolidated per Low #5 to eliminate duplicate definition and late import.)


# ---------------------------------------------------------------------------
# The Disposition Unit (the atomic record)
# ---------------------------------------------------------------------------

ControlClass = Literal["integral", "disclosed"]
AuthorityClassification = Literal["scan_confirmed", "human_reviewed", "pending_review"]


class DispositionUnit(VersionedModel):
    """
    One disposition unit (requirement clause/subparagraph) per spec §7.

    - Parent rows (is_rollup=True) carry composition_vector and NO code.
    - A parent is never a disposition target and is excluded from counts.
    - OPEN requires exactly one open_sub_reason from the closed vocabulary.
    - NA requires a scope_citation.
    - MI/EX require intent_statement + alternative_control + control_class.
    - Evidence is required for CW/MI before release eligibility.
    - Acceptance is required for MI/EX before release eligibility.
    - workflow_state transitions are governed by state.py (machine may only propose).

    Non-proposed states are expected to be produced only via transition_unit,
    which enforces §7.1 through apply_transition. This is a GUARDRAIL, NOT A
    SECURITY BOUNDARY — Python cannot prevent an in-process caller from
    constructing a model directly. Enforcement of release authority belongs
    to the S1a persistence/event-log layer, where transitions are recorded in
    an append-only hash-chained log with authenticated actor identity.
    """

    # Identity and extraction
    unit_id: str = Field(min_length=1)  # e.g. "AMR-51(e)"
    parent_id: Optional[str] = None
    is_rollup: bool = False
    # Medium #3: use StrictInt so bool (True/False) is rejected at the type boundary.
    # The validator below adds an explicit `type(v) is int` guard for defense-in-depth.
    composition_vector: Optional[dict[str, StrictInt]] = None  # only for rollups

    requirement_text: str = Field(min_length=1)
    requirement_payload: Optional[dict] = None
    unit_boundary_confirmed_by: Optional[str] = None
    applicability_clause: Optional[str] = None

    locator: Locator

    # Disposition
    code: Optional[DispositionCode] = None  # None for rollups
    workflow_state: WorkflowStateValue = "proposed"

    # OPEN-specific
    open_sub_reason: Optional[OPENSubReason] = None

    # NA-specific
    scope_citation: Optional[str] = None

    # Authority
    authority_dependent: bool = False
    authority_classification: AuthorityClassification = "pending_review"

    # MI/EX required fields
    intent_statement: Optional[str] = None
    alternative_control: Optional[str] = None
    control_class: Optional[ControlClass] = None

    @field_validator("unit_id", "requirement_text", "proposer", mode="before")
    @classmethod
    def _strip_nonblank_core_identity(cls, v: Any, info) -> str:
        """Medium #4: required identity/provenance strings must be stripped non-blank.

        Covers unit_id, requirement_text, and proposer (foundational traceability fields).
        """
        name = info.field_name
        stripped = _require_stripped_nonblank(v, name)
        if stripped is None or len(stripped) == 0:
            raise ValueError(f"{name} must be a non-blank string (whitespace-only rejected)")
        return stripped

    @field_validator(
        "scope_citation",
        "intent_statement",
        "alternative_control",
        "unit_boundary_confirmed_by",
        "applicability_clause",
        "confirmed_by",
        mode="before",
    )
    @classmethod
    def _strip_nonblank_disposition_strings(cls, v: Any, info) -> Optional[str]:
        """Medium #4: strip and reject whitespace-only for these provenance/conditional fields.

        Optional fields are allowed to be absent (return None). If present,
        whitespace-only is rejected.
        """
        name = info.field_name
        return _require_stripped_nonblank(v, name)

    # Evidence and acceptance
    evidence: tuple[EvidenceEntry, ...] = Field(default_factory=tuple)
    acceptance: Optional[AcceptanceRecord] = None

    # Provenance and proposal triage.
    #
    # WHY a band and not a float (§8): §8 defines three qualitative bands with
    # structural bases and contains no calibration data. The prior
    # `confidence: float` advertised a precision the system cannot produce, in
    # a document that also carries A-basis/B-basis allowables — where
    # "confidence" has a defined coverage probability. Internal triage only:
    # never aggregated to a package score, never rendered to a customer.
    proposal_band: Optional[ProposalBand] = None
    band_basis: Optional[str] = None  # the structural reason for the band
    proposer: str = Field(min_length=1)
    confirmed_by: Optional[str] = None
    confirmed_date: Optional[str] = None

    # NOTE: Per §7.1, parent roll-ups never carry an independent code or acceptance.

    @model_validator(mode="after")
    def _enforce_frozen_containers(self) -> "DispositionUnit":
        """High #2: Recursively freeze nested mutable sources of truth.

        composition_vector and requirement_payload are stored as immutable
        MappingProxyType / tuple after validation. In-place mutation is
        impossible; any mutation attempt raises. The original values passed
        to the constructor may be plain dicts; they are converted here.
        """
        # We must use object.__setattr__ because the model is frozen.
        if self.composition_vector is not None and not isinstance(
            self.composition_vector, MappingProxyType
        ):
            frozen_vec = _freeze_value(self.composition_vector)
            object.__setattr__(self, "composition_vector", frozen_vec)
        if self.requirement_payload is not None and not isinstance(
            self.requirement_payload, MappingProxyType
        ):
            frozen_payload = _freeze_value(self.requirement_payload)
            object.__setattr__(self, "requirement_payload", frozen_payload)
        # Also ensure evidence remains a tuple (already typed as such)
        if not isinstance(self.evidence, tuple):
            object.__setattr__(self, "evidence", tuple(self.evidence))
        return self

    @model_validator(mode="after")
    def _enforce_proposed_only_public_construction(self) -> "DispositionUnit":
        """High #1 (Atlas) + High #4: Public construction accepts ONLY workflow_state="proposed".

        Per §7.1 and §1.2: machine actors set only "proposed"; every other
        transition requires a named human actor via the state machine.
        Non-proposed states are produced exclusively by transition_unit
        (which validates via apply_transition and then promotes the state
        on a fully-validated successor via the internal authorization token).

        The internal token (_ALLOW_TRANSITION_STATE) is set ONLY inside
        transition_unit for the single controlled re-validation of an
        authorized successor. Public callers and model_copy cannot set it.

        Roll-up parents are never transition targets and must remain "proposed".
        """
        # S1a: release_approved is allowed ONLY via the narrow controlled token
        # set by the audited release path in release.py (after full context
        # evaluation against an explicit ReleaseContext, actor authorization,
        # and package-level all-or-nothing decision). Direct construction and
        # un-audited paths must still raise.
        if self.workflow_state == "release_approved":
            if not (_ALLOW_TRANSITION_STATE.get() or _ALLOW_RELEASED_CONSTRUCTION.get()):
                raise ValueError(
                    "workflow_state='release_approved' cannot be constructed directly. "
                    "Release eligibility requires package-level ReleaseContext evaluation, "
                    "actor authorization, and atomic store application (§7.1). "
                    "Use release.mark_package_release_approved or the controlled "
                    "transition_unit path."
                )
        if self.workflow_state != "proposed":
            # Internal authorized paths (transition_unit or the release gate) are the
            # only ways to construct non-proposed states. For release_approved the
            # dedicated release construction token is also accepted.
            allowed = _ALLOW_TRANSITION_STATE.get() or _ALLOW_RELEASED_CONSTRUCTION.get()
            if not allowed:
                raise ValueError(
                    f"Public DispositionUnit construction accepts only workflow_state='proposed'; "
                    f"got {self.workflow_state!r}. Use transition_unit for state changes."
                )
        if self.is_rollup and self.workflow_state != "proposed":
            # Belt-and-suspenders; the above already covers it, but explicit.
            raise ValueError("Roll-up parent rows must remain in workflow_state='proposed' (§1.1)")
        return self

    @model_validator(mode="after")
    def _enforce_rollup_invariants(self) -> "DispositionUnit":
        """Low #5 (split): focused validator for roll-up parent restrictions (§1.1)."""
        if not self.is_rollup:
            return self
        if self.code is not None:
            raise ValueError("Roll-up rows must not carry a code (composition_vector only)")
        if self.composition_vector is None:
            raise ValueError("Roll-up rows require a composition_vector")
        # Medium #4 (Atlas R3 #4): parents are never disposition targets.
        if self.acceptance is not None:
            raise ValueError(
                "Roll-up parent rows must not carry an acceptance record (§1.1: parent is never a disposition target)"
            )
        if self.evidence:
            raise ValueError(
                "Roll-up parent rows must not carry evidence entries (§1.1: parent is never a disposition target)"
            )
        if self.open_sub_reason is not None:
            raise ValueError("Roll-up parent rows must not carry open_sub_reason")
        return self

    @model_validator(mode="after")
    def _enforce_boundary_confirmation(self) -> "DispositionUnit":
        """Low #5 (split): focused validator for §7.3 boundary confirmation.

        Every non-rollup unit that carries a code must have a non-blank
        unit_boundary_confirmed_by at construction time.
        """
        if self.is_rollup:
            return self
        if self.code is None:
            # Code presence is checked in the per-code validator; do not duplicate.
            return self
        if not self.unit_boundary_confirmed_by or not str(self.unit_boundary_confirmed_by).strip():
            raise ValueError(
                "unit_boundary_confirmed_by is required for every non-rollup disposition unit "
                "that carries a code (§7.3)"
            )
        return self

    @model_validator(mode="after")
    def _enforce_code_specific_requirements(self) -> "DispositionUnit":
        """Low #5 (split): focused validator for per-code required-field rules (§7)."""
        if self.is_rollup:
            return self
        if self.code is None:
            raise ValueError("Non-rollup disposition units require a code")

        code = self.code

        if code == DispositionCode.OPEN:
            if not self.open_sub_reason:
                raise ValueError("OPEN units require exactly one open_sub_reason (§2.3)")
            if self.scope_citation or self.intent_statement or self.alternative_control:
                LOGGER.debug("OPEN unit carries extraneous fields; allowed but not required")

        elif code == DispositionCode.NA:
            if not self.scope_citation:
                raise ValueError("NA units require scope_citation (§3.2)")

        elif code in (DispositionCode.MI, DispositionCode.EX):
            if not (self.intent_statement and self.alternative_control and self.control_class):
                raise ValueError(
                    f"{code} units require intent_statement, alternative_control, and control_class"
                )

        # Evidence is strongly recommended for CW/MI before release eligibility,
        # but the model does not hard-fail here (release gate is separate).
        return self

    @model_validator(mode="after")
    def _enforce_alternative_control_requires_class(self) -> "DispositionUnit":
        """Medium #5: control_class is required whenever alternative_control is supplied.

        This is independent of code; the contract in §7 states control_class is
        required whenever alternative_control is present.
        """
        if self.alternative_control is not None and self.control_class is None:
            raise ValueError(
                "control_class is required whenever alternative_control is supplied (§7)"
            )
        return self

    @model_validator(mode="after")
    def _enforce_composition_vector_validity(self) -> "DispositionUnit":
        """Medium #3: composition vectors accept only known codes and non-negative counts.

        Invalid vectors must be rejected at the source of truth (DispositionUnit)
        so that roll-up badge derivation cannot silently derive a false CW (or any badge).

        Uses StrictInt in the field type + explicit `type(v) is int` to reject bool
        (Python bool is subclass of int and would otherwise be accepted).
        """
        if self.composition_vector is not None:
            for k, v in self.composition_vector.items():
                if k not in DISPOSITION_CODES:
                    raise ValueError(
                        f"composition_vector contains unknown code key: {k!r}; "
                        f"allowed: {sorted(DISPOSITION_CODES)}"
                    )
                # bool is a subclass of int; require exact int (not bool, not subclass)
                if type(v) is not int or v < 0:
                    raise ValueError(
                        f"composition_vector count for {k!r} must be a non-negative int, got {v!r}"
                    )
        return self

# ---------------------------------------------------------------------------
# Controlled transition (thin validating wrapper per S1 R4)
# ---------------------------------------------------------------------------




def transition_unit(
    unit: DispositionUnit,
    target: WorkflowStateValue,
    actor: "Actor",
    *,
    release_context: Optional["ReleaseContext"] = None,
) -> "DispositionUnit":
    """
    Produce a successor DispositionUnit in `target` state.

    For all states except release_approved: delegates to apply_transition
    (state.py) and rebuilds via normal validated constructor.

    For release_approved (S1a): delegates the full eligibility decision to
    release.py (is_unit_release_eligible against the supplied ReleaseContext).
    The ReleaseContext carries the package-level run date, target scope
    dimensions, and evidence threshold. Eligibility is whole — a unit-local
    view that ignores package context is deliberately not provided.

    The successor is constructed under the narrow internal token so the
    public-construction guard permits release_approved, but only this path
    can set the token for that state. Direct construction still raises.

    Actor authorization for release paths is enforced by the identity layer
    inside release.py when the full package gate is used. For the unit-level
    transition_unit path we still require a non-machine actor and run the
    eligibility checks.

    A released unit produced here is only a validated in-memory successor.
    Persistent recording, event chaining, and atomic package marking live
    in the store + release.mark_package_release_approved.
    """
    from oracle.disposition.state import apply_transition as _apply_transition

    if unit.is_rollup:
        raise ValueError("Roll-up parent rows are never disposition targets (§1.1)")

    if target == "release_approved":
        # Delegate the complete gate to release.py
        from oracle.disposition.release import (
            is_unit_release_eligible,
            ReleaseContext as _RC,
            _build_released_successor,  # uses the narrow token internally
        )

        # Safety: in-memory transition_unit path still requires the source unit
        # to already be human_confirmed. Direct proposed -> release_approved is blocked.
        if unit.workflow_state != "human_confirmed":
            raise ValueError(
                f"release_approved via transition_unit requires the unit to be in 'human_confirmed' first "
                f"(got {unit.workflow_state}). Use mark_package_release_approved for full audited package release."
            )

        if release_context is None:
            raise ValueError(
                "release_approved transition requires a ReleaseContext "
                "(effective_date, configurations, part_classes, evidence_threshold)"
            )

        if not isinstance(release_context, _RC):
            rc = _RC(
                effective_date=getattr(release_context, "effective_date", None) or release_context.get("effective_date"),  # type: ignore[attr-defined]
                configurations=tuple(getattr(release_context, "configurations", ()) or release_context.get("configurations", ())),
                part_classes=tuple(getattr(release_context, "part_classes", ()) or release_context.get("part_classes", ())),
                evidence_threshold=float(getattr(release_context, "evidence_threshold", 0.0) or release_context.get("evidence_threshold", 0.0)),
            )
        else:
            rc = release_context

        ok, why = is_unit_release_eligible(unit, rc)
        if not ok:
            raise ValueError(f"Unit {unit.unit_id} is not release-eligible: {why}")

        if getattr(actor, "is_machine", False):
            raise ValueError("Machine actor may not produce release_approved")

        return _build_released_successor(unit, getattr(actor, "name", "unknown"))

    # Non-release path — original S1 behavior
    new_state = _apply_transition(unit.workflow_state, target, actor)

    data = unit.model_dump()
    data["workflow_state"] = new_state
    if not getattr(actor, "is_machine", False):
        data["confirmed_by"] = getattr(actor, "name", None)

    # Re-hydrate
    if data.get("locator") and not isinstance(data.get("locator"), Locator):
        data["locator"] = Locator.model_validate(data["locator"])
    if data.get("evidence"):
        data["evidence"] = tuple(
            e if isinstance(e, EvidenceEntry) else EvidenceEntry.model_validate(e)
            for e in data["evidence"]
        )
    else:
        data["evidence"] = ()
    if data.get("acceptance") and not isinstance(data.get("acceptance"), AcceptanceRecord):
        data["acceptance"] = AcceptanceRecord.model_validate(data["acceptance"])

    token = _ALLOW_TRANSITION_STATE.set(True)
    try:
        successor = DispositionUnit.model_validate(data)
    finally:
        _ALLOW_TRANSITION_STATE.reset(token)

    return successor

