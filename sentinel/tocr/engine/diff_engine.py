#!/usr/bin/env python3
"""
Module: Structural Diff Engine
Purpose: Pass 1 — Ingest both revisions and produce field-by-field diff.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 4.1
"""

__safety_critical__: bool = True
__version__ = "1.0.0"

import difflib
import re
from typing import Optional

from sentinel.tocr.models.enums import (
    ChangeClassification,
    ChangeType,
    ConfidenceLevel,
    ParserConfidence,
)
from sentinel.tocr.models.diff import FieldChange, StructuralDiff, SubTaskChange
from sentinel.tocr.models.task_order import TaskOrder


# Patterns for deterministic classification
_FUNDING_PATTERNS = re.compile(
    r"\b(fund|budget|cost|dollar|amount|\$|wbs|charge.?code|clin|obligat)\b", re.IGNORECASE
)
_SKILLS_PATTERNS = re.compile(
    r"\b(skill|labor.?categor|qualification|expertise|competenc|personnel)\b", re.IGNORECASE
)
_DELIVERABLE_PATTERNS = re.compile(
    r"\b(deliverable|milestone|due.?date|submittal|report|artifact)\b", re.IGNORECASE
)
_TEAM_PATTERNS = re.compile(
    r"\b(team|participat|subcontract|partner|teaming|vendor)\b", re.IGNORECASE
)
_QUALITY_PATTERNS = re.compile(
    r"\b(quality|qms|iso.?9001|inspection|audit|assurance|nasa.?std.?8739)\b", re.IGNORECASE
)
_SCOPE_PATTERNS = re.compile(
    r"\b(scope|develop|design|engineer|analys|integrat|test|software|hardware|"
    r"support|maintain|implement|build|system|capability|AI|machine.?learn)\b",
    re.IGNORECASE,
)
_FORMATTING_ONLY = re.compile(r"^[\s\n\r\t]+$")


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace for comparison."""
    return re.sub(r"\s+", " ", text.strip())


def _is_formatting_change(prior: str, proposed: str) -> bool:
    """Check if change is formatting-only (Section 4.1.1)."""
    return _normalize_whitespace(prior) == _normalize_whitespace(proposed)


def _classify_change(
    prior_text: str, proposed_text: str, field_path: str
) -> tuple[ChangeClassification, ConfidenceLevel, str]:
    """
    Classify a change deterministically based on field path and content patterns.

    Returns (classification, confidence, reason).
    """
    combined = f"{prior_text} {proposed_text}"

    # Field path hints
    path_lower = field_path.lower()
    if "funding" in path_lower or "wbs" in path_lower or "charge_code" in path_lower:
        return ChangeClassification.FUNDING, ConfidenceLevel.DETERMINISTIC, f"Field path: {field_path}"
    if "skill" in path_lower or "labor" in path_lower:
        return ChangeClassification.SKILLS, ConfidenceLevel.DETERMINISTIC, f"Field path: {field_path}"
    if "deliverable" in path_lower:
        return ChangeClassification.DELIVERABLE, ConfidenceLevel.DETERMINISTIC, f"Field path: {field_path}"
    if "team" in path_lower or "participat" in path_lower:
        return ChangeClassification.TEAM, ConfidenceLevel.DETERMINISTIC, f"Field path: {field_path}"
    if "quality" in path_lower or "qms" in path_lower:
        return ChangeClassification.QUALITY_PLAN, ConfidenceLevel.DETERMINISTIC, f"Field path: {field_path}"

    # Content-based classification — SCOPE FIRST.
    # Conservative ordering: scope patterns are checked before funding so that
    # scope changes mentioning cost-adjacent words ("cost analysis", "amount of
    # testing") are classified as SCOPE, not FUNDING.  Under-reporting scope
    # violations is the worst failure mode for a compliance tool.
    if _SCOPE_PATTERNS.search(combined):
        return ChangeClassification.SCOPE_LANGUAGE, ConfidenceLevel.HIGH, "Scope language detected"
    if _FUNDING_PATTERNS.search(combined):
        return ChangeClassification.FUNDING, ConfidenceLevel.HIGH, "Funding keywords detected"
    if _SKILLS_PATTERNS.search(combined):
        return ChangeClassification.SKILLS, ConfidenceLevel.HIGH, "Skills keywords detected"
    if _DELIVERABLE_PATTERNS.search(combined):
        return ChangeClassification.DELIVERABLE, ConfidenceLevel.HIGH, "Deliverable keywords detected"
    if _TEAM_PATTERNS.search(combined):
        return ChangeClassification.TEAM, ConfidenceLevel.HIGH, "Team keywords detected"
    if _QUALITY_PATTERNS.search(combined):
        return ChangeClassification.QUALITY_PLAN, ConfidenceLevel.HIGH, "Quality keywords detected"

    return ChangeClassification.ADMINISTRATIVE, ConfidenceLevel.MEDIUM, "No scope keywords detected"


class DiffEngine:
    """
    Pass 1: Structural Diff Engine.

    Ingests both revisions and produces a field-by-field diff.
    Classification of each change as: scope_language, funding, skills,
    deliverable, team, quality_plan, administrative, formatting.
    """

    def run(self, prior: TaskOrder, proposed: TaskOrder) -> StructuralDiff:
        """
        Execute structural diff between prior and proposed revisions.

        Returns a StructuralDiff with all detected changes.
        """
        field_changes: list[FieldChange] = []

        # Compare top-level text fields.
        # If scope_text is identical to task_order_description (common in
        # ESSCA-parsed documents), skip scope_text to avoid duplicate findings.
        skip_scope_text = (
            prior.scope_text == prior.task_order_description
            and proposed.scope_text == proposed.task_order_description
        )
        text_fields = [
            ("task_order_description.scope", prior.task_order_description, proposed.task_order_description),
        ]
        if not skip_scope_text:
            text_fields.append(("scope_text", prior.scope_text, proposed.scope_text))
        text_fields.extend([
            ("summary_of_changes", prior.summary_of_changes, proposed.summary_of_changes),
            ("emergency_justification", prior.emergency_justification, proposed.emergency_justification),
            ("agency_comments", prior.agency_comments, proposed.agency_comments),
            ("title", prior.title, proposed.title),
        ])

        for field_path, prior_text, proposed_text in text_fields:
            change = self._compare_text(field_path, prior_text, proposed_text)
            if change:
                field_changes.append(change)

        # Compare emergency designation
        if prior.emergency_designation != proposed.emergency_designation:
            field_changes.append(FieldChange(
                field_path="emergency_designation",
                change_type=ChangeType.MODIFICATION,
                prior_text=str(prior.emergency_designation),
                proposed_text=str(proposed.emergency_designation),
                classification=ChangeClassification.ADMINISTRATIVE,
                classification_confidence=ConfidenceLevel.DETERMINISTIC,
                classification_reason="Emergency designation flag changed",
                is_material=True,
            ))

        # Compare quality plans
        qp_change = self._compare_quality_plans(prior, proposed)
        if qp_change:
            field_changes.append(qp_change)

        # Compare funding
        funding_changes = self._compare_funding(prior, proposed)
        field_changes.extend(funding_changes)

        # Compare sub-tasks
        sub_task_changes, new_subs, removed_subs, sub_field_changes = self._compare_sub_tasks(
            prior, proposed
        )
        field_changes.extend(sub_field_changes)

        # Compute summary stats
        material = [c for c in field_changes if c.is_material]
        formatting = [c for c in field_changes if c.is_formatting_only]

        parser_conf = min(
            prior.parser_confidence, proposed.parser_confidence,
            key=lambda x: ["high", "medium", "low"].index(x.value)
        )

        return StructuralDiff(
            prior_revision=prior.revision_number,
            proposed_revision=proposed.revision_number,
            total_changes=len(field_changes),
            material_changes=len(material),
            formatting_changes=len(formatting),
            field_changes=field_changes,
            sub_task_changes=sub_task_changes,
            new_sub_tasks=new_subs,
            removed_sub_tasks=removed_subs,
            parser_confidence=parser_conf,
        )

    def _compare_text(
        self, field_path: str, prior: str, proposed: str
    ) -> Optional[FieldChange]:
        """Compare two text fields and return a FieldChange if different."""
        if prior == proposed:
            return None

        if _is_formatting_change(prior, proposed):
            return FieldChange(
                field_path=field_path,
                change_type=ChangeType.MODIFICATION,
                prior_text=prior,
                proposed_text=proposed,
                classification=ChangeClassification.FORMATTING,
                classification_confidence=ConfidenceLevel.DETERMINISTIC,
                classification_reason="Whitespace/formatting only",
                is_material=False,
            )

        if not prior and proposed:
            change_type = ChangeType.INSERTION
        elif prior and not proposed:
            change_type = ChangeType.DELETION
        else:
            change_type = ChangeType.MODIFICATION

        classification, confidence, reason = _classify_change(prior, proposed, field_path)
        is_material = classification not in {
            ChangeClassification.FORMATTING,
            ChangeClassification.ADMINISTRATIVE,
        }

        word_delta = len(proposed.split()) - len(prior.split())

        return FieldChange(
            field_path=field_path,
            change_type=change_type,
            prior_text=prior,
            proposed_text=proposed,
            classification=classification,
            classification_confidence=confidence,
            classification_reason=reason,
            is_material=is_material,
            word_count_delta=word_delta,
        )

    def _compare_quality_plans(
        self, prior: TaskOrder, proposed: TaskOrder
    ) -> Optional[FieldChange]:
        """Compare quality plans between revisions."""
        prior_text = prior.quality_plan.text if prior.quality_plan else ""
        proposed_text = proposed.quality_plan.text if proposed.quality_plan else ""
        if prior_text == proposed_text:
            return None
        return self._compare_text("quality_plan.text", prior_text, proposed_text)

    def _compare_funding(
        self, prior: TaskOrder, proposed: TaskOrder
    ) -> list[FieldChange]:
        """Compare funding tables."""
        changes: list[FieldChange] = []

        if prior.total_funding != proposed.total_funding:
            changes.append(FieldChange(
                field_path="funding.total",
                change_type=ChangeType.MODIFICATION,
                prior_text=str(prior.total_funding or 0),
                proposed_text=str(proposed.total_funding or 0),
                classification=ChangeClassification.FUNDING,
                classification_confidence=ConfidenceLevel.DETERMINISTIC,
                classification_reason="Total funding changed",
                is_material=True,
            ))

        prior_funding = {e.sub_task_id: e for e in prior.funding_table if e.sub_task_id}
        proposed_funding = {e.sub_task_id: e for e in proposed.funding_table if e.sub_task_id}

        for st_id in set(prior_funding) | set(proposed_funding):
            p = prior_funding.get(st_id)
            n = proposed_funding.get(st_id)
            if p and n and p.amount != n.amount:
                changes.append(FieldChange(
                    field_path=f"funding.{st_id}.amount",
                    change_type=ChangeType.MODIFICATION,
                    prior_text=str(p.amount),
                    proposed_text=str(n.amount),
                    classification=ChangeClassification.FUNDING,
                    classification_confidence=ConfidenceLevel.DETERMINISTIC,
                    classification_reason=f"Sub-task {st_id} funding changed",
                    is_material=True,
                ))
            elif not p and n:
                changes.append(FieldChange(
                    field_path=f"funding.{st_id}.amount",
                    change_type=ChangeType.INSERTION,
                    prior_text="",
                    proposed_text=str(n.amount),
                    classification=ChangeClassification.FUNDING,
                    classification_confidence=ConfidenceLevel.DETERMINISTIC,
                    classification_reason=f"New funding for sub-task {st_id}",
                    is_material=True,
                ))
            elif p and not n:
                changes.append(FieldChange(
                    field_path=f"funding.{st_id}.amount",
                    change_type=ChangeType.DELETION,
                    prior_text=str(p.amount),
                    proposed_text="",
                    classification=ChangeClassification.FUNDING,
                    classification_confidence=ConfidenceLevel.DETERMINISTIC,
                    classification_reason=f"Funding removed for sub-task {st_id}",
                    is_material=True,
                ))

        return changes

    def _compare_sub_tasks(
        self, prior: TaskOrder, proposed: TaskOrder
    ) -> tuple[list[SubTaskChange], list[str], list[str], list[FieldChange]]:
        """Compare sub-task tables between revisions."""
        sub_task_changes: list[SubTaskChange] = []
        new_subs: list[str] = []
        removed_subs: list[str] = []
        field_changes: list[FieldChange] = []

        prior_map = {st.sub_task_id: st for st in prior.sub_tasks}
        proposed_map = {st.sub_task_id: st for st in proposed.sub_tasks}

        all_ids = set(prior_map) | set(proposed_map)

        for st_id in sorted(all_ids):
            p = prior_map.get(st_id)
            n = proposed_map.get(st_id)

            if not p and n:
                # New sub-task
                new_subs.append(st_id)
                fc = FieldChange(
                    field_path=f"sub_tasks.{st_id}",
                    change_type=ChangeType.INSERTION,
                    prior_text="",
                    proposed_text=n.description,
                    classification=ChangeClassification.SCOPE_LANGUAGE,
                    classification_confidence=ConfidenceLevel.DETERMINISTIC,
                    classification_reason=f"New sub-task {st_id} added",
                    is_material=True,
                )
                field_changes.append(fc)
                sub_task_changes.append(SubTaskChange(
                    sub_task_id=st_id,
                    change_type=ChangeType.INSERTION,
                    field_changes=[fc],
                    is_new_sub_task=True,
                ))
            elif p and not n:
                # Removed sub-task
                removed_subs.append(st_id)
                fc = FieldChange(
                    field_path=f"sub_tasks.{st_id}",
                    change_type=ChangeType.DELETION,
                    prior_text=p.description,
                    proposed_text="",
                    classification=ChangeClassification.SCOPE_LANGUAGE,
                    classification_confidence=ConfidenceLevel.DETERMINISTIC,
                    classification_reason=f"Sub-task {st_id} removed",
                    is_material=True,
                )
                field_changes.append(fc)
                sub_task_changes.append(SubTaskChange(
                    sub_task_id=st_id,
                    change_type=ChangeType.DELETION,
                    field_changes=[fc],
                    is_removed_sub_task=True,
                ))
            elif p and n:
                # Compare existing sub-task fields
                st_changes = self._compare_sub_task_fields(st_id, p, n)
                if st_changes:
                    field_changes.extend(st_changes)
                    sub_task_changes.append(SubTaskChange(
                        sub_task_id=st_id,
                        change_type=ChangeType.MODIFICATION,
                        field_changes=st_changes,
                    ))

        return sub_task_changes, new_subs, removed_subs, field_changes

    def _compare_sub_task_fields(
        self, st_id: str, prior, proposed
    ) -> list[FieldChange]:
        """Compare fields within a single sub-task."""
        changes: list[FieldChange] = []

        # Description
        desc_change = self._compare_text(
            f"sub_tasks.{st_id}.description",
            prior.description, proposed.description
        )
        if desc_change:
            changes.append(desc_change)

        # Skills
        if set(prior.skills) != set(proposed.skills):
            changes.append(FieldChange(
                field_path=f"sub_tasks.{st_id}.skills",
                change_type=ChangeType.MODIFICATION,
                prior_text=", ".join(prior.skills),
                proposed_text=", ".join(proposed.skills),
                classification=ChangeClassification.SKILLS,
                classification_confidence=ConfidenceLevel.DETERMINISTIC,
                classification_reason=f"Skills changed for sub-task {st_id}",
                is_material=True,
            ))

        # Deliverables
        if set(prior.deliverables) != set(proposed.deliverables):
            changes.append(FieldChange(
                field_path=f"sub_tasks.{st_id}.deliverables",
                change_type=ChangeType.MODIFICATION,
                prior_text=", ".join(prior.deliverables),
                proposed_text=", ".join(proposed.deliverables),
                classification=ChangeClassification.DELIVERABLE,
                classification_confidence=ConfidenceLevel.DETERMINISTIC,
                classification_reason=f"Deliverables changed for sub-task {st_id}",
                is_material=True,
            ))

        # Team
        if set(prior.participating_team) != set(proposed.participating_team):
            changes.append(FieldChange(
                field_path=f"sub_tasks.{st_id}.participating_team",
                change_type=ChangeType.MODIFICATION,
                prior_text=", ".join(prior.participating_team),
                proposed_text=", ".join(proposed.participating_team),
                classification=ChangeClassification.TEAM,
                classification_confidence=ConfidenceLevel.DETERMINISTIC,
                classification_reason=f"Team changed for sub-task {st_id}",
                is_material=True,
            ))

        # Funding
        if prior.funding != proposed.funding:
            changes.append(FieldChange(
                field_path=f"sub_tasks.{st_id}.funding",
                change_type=ChangeType.MODIFICATION,
                prior_text=str(prior.funding or 0),
                proposed_text=str(proposed.funding or 0),
                classification=ChangeClassification.FUNDING,
                classification_confidence=ConfidenceLevel.DETERMINISTIC,
                classification_reason=f"Funding changed for sub-task {st_id}",
                is_material=True,
            ))

        return changes
