#!/usr/bin/env python3
"""
Module: JSON Export
Purpose: Export ComplianceReport to JSON for integration with contract management systems.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 11.2

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: False
"""

__version__ = "1.0.0"

import json
from pathlib import Path
from typing import Optional

from sentinel.tocr.models.report import ComplianceReport


def export_json(
    report: ComplianceReport,
    output_path: Optional[Path] = None,
    indent: int = 2,
) -> str:
    """
    Export compliance report as JSON.

    Args:
        report: The ComplianceReport to export.
        output_path: Optional path to write file. If None, returns string only.
        indent: JSON indentation level.

    Returns:
        JSON string of the report.
    """
    data = report.model_dump(mode="json")
    json_str = json.dumps(data, indent=indent, default=str)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_str)

    return json_str
