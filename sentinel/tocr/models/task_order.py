#!/usr/bin/env python3
"""
Module: Task Order Data Model
Purpose: Structured representation of a parsed task order revision.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 4.1
"""

__version__ = "1.0.0"

from typing import Optional

from pydantic import BaseModel, Field

from sentinel.tocr.models.enums import ParserConfidence, RevisionStatus


class SubTask(BaseModel):
    """A sub-task entry within the task order."""

    sub_task_id: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    labor_categories: list[str] = Field(default_factory=list)
    funding: Optional[float] = None
    wbs_code: Optional[str] = None
    charge_code: Optional[str] = None
    participating_team: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)

    # Why extra="allow": Parsers extract fields from diverse document formats
    # (ATOMS JSON, DOCX, PDF) that may include source-specific metadata the
    # engine doesn't consume.  raw_fields captures the full extraction; extras
    # here prevent parser failures when new fields are added to source formats.
    model_config = {"extra": "allow"}


class FundingEntry(BaseModel):
    """A funding table entry."""

    sub_task_id: Optional[str] = None
    clin: Optional[str] = None
    amount: float = 0.0
    wbs_code: Optional[str] = None
    charge_code: Optional[str] = None
    description: str = ""

    # Why extra="allow": Parsers extract fields from diverse document formats
    # (ATOMS JSON, DOCX, PDF) that may include source-specific metadata the
    # engine doesn't consume.  raw_fields captures the full extraction; extras
    # here prevent parser failures when new fields are added to source formats.
    model_config = {"extra": "allow"}


class QualityPlan(BaseModel):
    """Quality plan section."""

    text: str = ""
    qms_required: bool = False
    software_scope: bool = False
    safety_critical: bool = False

    # Why extra="allow": Parsers extract fields from diverse document formats
    # (ATOMS JSON, DOCX, PDF) that may include source-specific metadata the
    # engine doesn't consume.  raw_fields captures the full extraction; extras
    # here prevent parser failures when new fields are added to source formats.
    model_config = {"extra": "allow"}


class TaskOrder(BaseModel):
    """
    Complete structured representation of a task order revision.

    Produced by parsers from ATOMS JSON, DOCX, or PDF input.
    All downstream analysis operates on this model.
    """

    # Identification
    task_order_number: str
    revision_number: str
    revision_status: RevisionStatus = RevisionStatus.DRAFT
    title: str = ""

    # Core content
    task_order_description: str = ""
    scope_text: str = ""
    summary_of_changes: str = ""

    # Structured sub-task table
    sub_tasks: list[SubTask] = Field(default_factory=list)

    # Funding
    funding_table: list[FundingEntry] = Field(default_factory=list)
    total_funding: Optional[float] = None

    # Quality
    quality_plan: Optional[QualityPlan] = None

    # Emergency
    emergency_designation: bool = False
    emergency_justification: str = ""

    # Agency/comments
    agency_comments: str = ""

    # Metadata
    parser_confidence: ParserConfidence = ParserConfidence.HIGH
    source_format: str = "atoms_json"
    raw_fields: dict = Field(default_factory=dict)

    # Why extra="allow": Parsers extract fields from diverse document formats
    # (ATOMS JSON, DOCX, PDF) that may include source-specific metadata the
    # engine doesn't consume.  raw_fields captures the full extraction; extras
    # here prevent parser failures when new fields are added to source formats.
    model_config = {"extra": "allow"}
