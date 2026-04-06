#!/usr/bin/env python3
"""
Module: ATOMS JSON Parser
Purpose: Parse ATOMS JSON export into TaskOrder model.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 3.1, 14.1
"""

__version__ = "1.0.0"

import json
from pathlib import Path
from typing import Union

from sentinel.tocr.models.enums import ParserConfidence, RevisionStatus
from sentinel.tocr.models.task_order import (
    FundingEntry,
    QualityPlan,
    SubTask,
    TaskOrder,
)


class ATOMSParser:
    """
    ATOMS JSON parser — deterministic parse, high confidence.

    Ingests native ATOMS JSON export and produces a fully structured
    TaskOrder model.
    """

    def parse(self, source: Union[str, Path, dict]) -> TaskOrder:
        """
        Parse ATOMS JSON into TaskOrder.

        Args:
            source: Path to JSON file, JSON string, or pre-parsed dict.

        Returns:
            Parsed TaskOrder with parser_confidence=HIGH.
        """
        if isinstance(source, dict):
            data = source
        elif isinstance(source, Path):
            with open(source) as f:
                data = json.load(f)
        else:
            data = json.loads(source)

        return self._build_task_order(data)

    def _build_task_order(self, data: dict) -> TaskOrder:
        """Build TaskOrder from ATOMS JSON structure."""
        sub_tasks = [
            self._build_sub_task(st) for st in data.get("sub_tasks", [])
        ]

        funding_table = [
            self._build_funding_entry(fe) for fe in data.get("funding_table", [])
        ]

        quality_plan = None
        if "quality_plan" in data:
            qp = data["quality_plan"]
            quality_plan = QualityPlan(
                text=qp.get("text", ""),
                qms_required=qp.get("qms_required", False),
                software_scope=qp.get("software_scope", False),
                safety_critical=qp.get("safety_critical", False),
            )

        status_str = data.get("revision_status", "draft").lower()
        status = RevisionStatus.DRAFT if status_str == "draft" else RevisionStatus.RELEASED

        return TaskOrder(
            task_order_number=data.get("task_order_number", ""),
            revision_number=data.get("revision_number", ""),
            revision_status=status,
            title=data.get("title", ""),
            task_order_description=data.get("task_order_description", ""),
            scope_text=data.get("scope_text", data.get("task_order_description", "")),
            summary_of_changes=data.get("summary_of_changes", ""),
            sub_tasks=sub_tasks,
            funding_table=funding_table,
            total_funding=data.get("total_funding"),
            quality_plan=quality_plan,
            emergency_designation=data.get("emergency_designation", False),
            emergency_justification=data.get("emergency_justification", ""),
            agency_comments=data.get("agency_comments", ""),
            parser_confidence=ParserConfidence.HIGH,
            source_format="atoms_json",
            raw_fields=data,
        )

    def _build_sub_task(self, data: dict) -> SubTask:
        """Build SubTask from ATOMS sub-task data."""
        return SubTask(
            sub_task_id=data.get("sub_task_id", data.get("id", "")),
            description=data.get("description", ""),
            skills=data.get("skills", []),
            labor_categories=data.get("labor_categories", []),
            funding=data.get("funding"),
            wbs_code=data.get("wbs_code"),
            charge_code=data.get("charge_code"),
            participating_team=data.get("participating_team", []),
            deliverables=data.get("deliverables", []),
        )

    def _build_funding_entry(self, data: dict) -> FundingEntry:
        """Build FundingEntry from ATOMS funding data."""
        return FundingEntry(
            sub_task_id=data.get("sub_task_id"),
            clin=data.get("clin"),
            amount=data.get("amount", 0.0),
            wbs_code=data.get("wbs_code"),
            charge_code=data.get("charge_code"),
            description=data.get("description", ""),
        )
