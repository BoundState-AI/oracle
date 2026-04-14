#!/usr/bin/env python3
"""
Module: Contract Configuration
Purpose: Contract configuration model for rule applicability (Section 3.3, 9).

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary
"""

__version__ = "1.0.0"

from typing import Optional

from pydantic import BaseModel, Field

from sentinel.tocr.models.enums import ContractType, RevisionStatus


class ContractConfig(BaseModel):
    """
    Contract configuration for rule applicability.

    Determines which rules fire based on contract type, agency,
    vehicle, clause presence, and local policy pack.

    Analysis thresholds are documented here so they can be audited,
    justified, and overridden without code changes.
    """

    contract_type: list[ContractType] = Field(
        default_factory=lambda: [ContractType.IDIQ, ContractType.TASK_ORDER]
    )
    agency: str = "NASA"
    center: Optional[str] = None
    vehicle: Optional[str] = None
    local_policy_pack: Optional[str] = None
    clauses_present: list[str] = Field(default_factory=list)
    revision_status: RevisionStatus = RevisionStatus.DRAFT

    # --- Analysis thresholds ---
    # These are documented, configurable, and auditable.
    # Each has a documented rationale below.

    disclosure_similarity_threshold: float = Field(
        default=0.55,
        description=(
            "Minimum SequenceMatcher ratio to consider a change disclosed "
            "in the Summary of Changes. 0.55 requires genuine semantic overlap "
            "— the summary must actually describe the change. Previous 0.35 "
            "caused false-positive disclosures that suppressed TOCR-001 "
            "(CRITICAL). Conservative bias: flag more, not less. Range: 0.0-1.0."
        ),
    )

    cost_overlap_word_threshold: int = Field(
        default=8,
        description=(
            "Minimum number of shared non-stopword tokens between two sub-task "
            "descriptions to flag cost misallocation risk. 8 words requires "
            "substantial topical overlap, not just shared jargon. "
            "Validated against NASA ESSCA sub-task structures."
        ),
    )

    emergency_justification_word_threshold: int = Field(
        default=2,
        description=(
            "Minimum number of shared content words between a scope change "
            "and the emergency justification to consider the change covered. "
            "2 words requires at least one topical word match beyond articles. "
            "Validated against FAR 16.505(b)(4) justification patterns."
        ),
    )

    # Why extra="allow": ContractConfig is user-facing configuration that may
    # carry agency-specific or vehicle-specific fields the engine doesn't consume
    # yet (e.g., ESSCA-specific metadata).  Forbidding extras would break forward
    # compatibility when new config fields are added to rule packs before the
    # engine is updated to consume them.
    model_config = {"extra": "allow"}

    def has_clause(self, clause: str) -> bool:
        """Check if a specific clause is present in the contract."""
        return clause in self.clauses_present

    def matches_agency(self, agency: Optional[str]) -> bool:
        """Check if config matches a required agency (None = any)."""
        if agency is None:
            return True
        return self.agency.upper() == agency.upper()

    def matches_contract_type(self, required_types: Optional[list[str]]) -> bool:
        """Check if config matches any of the required contract types."""
        if not required_types:
            return True
        config_types = {ct.value for ct in self.contract_type}
        return bool(config_types & set(required_types))

    def matches_local_pack(self, required_pack: Optional[str]) -> bool:
        """Check if config matches a required local policy pack."""
        if required_pack is None:
            return True
        if self.local_policy_pack is None:
            return False
        return self.local_policy_pack.upper() == required_pack.upper()

    def matches_revision_status(self, required_statuses: Optional[list[str]]) -> bool:
        """Check if config matches any of the required revision statuses."""
        if not required_statuses:
            return True
        return self.revision_status.value in required_statuses
