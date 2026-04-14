#!/usr/bin/env python3
"""
Module: Structural Diff Model
Purpose: Field-level change tracking between task order revisions.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 4.1
"""

__version__ = "1.0.0"

from typing import Optional

from pydantic import BaseModel, Field

from sentinel.tocr.models.enums import (
    ChangeClassification,
    ChangeType,
    ConfidenceLevel,
    ParserConfidence,
)


class FieldChange(BaseModel):
    """
    A single detected change between prior and proposed revision.

    Every insertion, deletion, and modification is tagged with
    field path and location per Section 4.1.
    """

    field_path: str
    change_type: ChangeType
    prior_text: str = ""
    proposed_text: str = ""
    classification: ChangeClassification = ChangeClassification.ADMINISTRATIVE
    classification_confidence: ConfidenceLevel = ConfidenceLevel.DETERMINISTIC
    classification_reason: str = ""
    parser_confidence: ParserConfidence = ParserConfidence.HIGH
    is_material: bool = False
    word_count_delta: int = 0

    model_config = {"extra": "forbid"}

    @property
    def is_formatting_only(self) -> bool:
        return self.classification == ChangeClassification.FORMATTING

    @property
    def is_scope_related(self) -> bool:
        return self.classification in {
            ChangeClassification.SCOPE_LANGUAGE,
            ChangeClassification.FUNDING,
            ChangeClassification.SKILLS,
            ChangeClassification.DELIVERABLE,
        }


class SubTaskChange(BaseModel):
    """Change to a specific sub-task."""

    model_config = {"extra": "forbid"}

    sub_task_id: str
    change_type: ChangeType
    field_changes: list[FieldChange] = Field(default_factory=list)
    is_new_sub_task: bool = False
    is_removed_sub_task: bool = False


class StructuralDiff(BaseModel):
    """
    Complete structural diff between two task order revisions.

    Produced by Pass 1 of the three-pass pipeline.
    """

    prior_revision: str
    proposed_revision: str
    total_changes: int = 0
    material_changes: int = 0
    formatting_changes: int = 0

    field_changes: list[FieldChange] = Field(default_factory=list)
    sub_task_changes: list[SubTaskChange] = Field(default_factory=list)

    new_sub_tasks: list[str] = Field(default_factory=list)
    removed_sub_tasks: list[str] = Field(default_factory=list)

    parser_confidence: ParserConfidence = ParserConfidence.HIGH

    model_config = {"extra": "forbid"}

    def get_material_changes(self) -> list[FieldChange]:
        """Return only material (non-formatting, non-administrative) changes."""
        return [c for c in self.field_changes if c.is_material]

    def get_scope_changes(self) -> list[FieldChange]:
        """Return only scope-related changes."""
        return [c for c in self.field_changes if c.is_scope_related]

    def get_changes_by_classification(
        self, classification: ChangeClassification
    ) -> list[FieldChange]:
        return [c for c in self.field_changes if c.classification == classification]
