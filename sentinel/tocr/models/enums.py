#!/usr/bin/env python3
"""
Module: TOCR Enumerations
Purpose: All enums for the Task Order Compliance Review module.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Sections 4-6

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: True
"""

__version__ = "1.0.0"

from enum import Enum


class ParserConfidence(str, Enum):
    """Parser confidence per Section 3.2."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChangeType(str, Enum):
    """Type of field change detected in structural diff (Section 4.1)."""
    INSERTION = "insertion"
    DELETION = "deletion"
    MODIFICATION = "modification"


class ChangeClassification(str, Enum):
    """Semantic classification of a detected change (Section 4.1)."""
    SCOPE_LANGUAGE = "scope_language"
    FUNDING = "funding"
    SKILLS = "skills"
    DELIVERABLE = "deliverable"
    TEAM = "team"
    QUALITY_PLAN = "quality_plan"
    ADMINISTRATIVE = "administrative"
    FORMATTING = "formatting"


class ComplianceSeverity(str, Enum):
    """Compliance severity axis (Section 6.1)."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReviewPriority(str, Enum):
    """Review priority axis (Section 6.2)."""
    LEGAL = "LEGAL"
    CO = "CO"
    SUPERVISORY = "SUPERVISORY"
    ADVISORY = "ADVISORY"


class ComplianceVerdict(str, Enum):
    """Overall revision compliance verdict (Section 6.3)."""
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"
    FATAL = "FATAL"


class BasisType(str, Enum):
    """Rule authority basis type (Section 5)."""
    INTERNAL_CONTROL = "internal_control"
    REGULATORY = "regulatory"
    CONTRACTUAL = "contractual"
    LOCAL_POLICY = "local_policy"
    HEURISTIC = "heuristic"


class ConfidenceLevel(str, Enum):
    """Confidence method for findings (Section 5)."""
    DETERMINISTIC = "deterministic"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ContractType(str, Enum):
    """Supported contract types (Section 9)."""
    IDIQ = "IDIQ"
    TASK_ORDER = "Task Order"
    BPA = "BPA"
    BOA = "BOA"
    CPAF = "CPAF"
    CPFF = "CPFF"
    FFP = "FFP"
    T_AND_M = "T&M"


class RevisionStatus(str, Enum):
    """Task order revision status (Section 9)."""
    DRAFT = "draft"
    RELEASED = "released"
