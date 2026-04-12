#!/usr/bin/env python3
"""
Module: Text Export
Purpose: Export ComplianceReport as readable text summary.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 11
"""

__version__ = "1.0.0"

from pathlib import Path
from typing import Optional

from sentinel.tocr.models.report import ComplianceReport


def _format_header(report: ComplianceReport) -> str:
    """Format report header: ID, revisions, verdict, score."""
    lines = []
    lines.append("=" * 72)
    lines.append("SENTINEL-TOCR COMPLIANCE REPORT")
    lines.append("Every change visible. Every rule enforced.")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"Report ID:         {report.report_id}")
    lines.append(f"Generated:         {report.generated_at}")
    lines.append(f"Prior Revision:    {report.prior_revision}")
    lines.append(f"Proposed Revision: {report.proposed_revision}")
    lines.append(f"Contract Config:   {report.contract_config_summary}")
    lines.append(f"Parser Confidence: {report.parser_confidence.value}")
    if report.input_fingerprint:
        lines.append(f"Input Fingerprint: {report.input_fingerprint}")
    lines.append("")

    # Score summary
    if report.score:
        s = report.score
        lines.append("-" * 72)
        lines.append(f"VERDICT: {s.verdict.value}  |  Score: {s.raw_score}/100")
        lines.append(
            f"  CRITICAL: {s.critical_count}  |  HIGH: {s.high_count}  "
            f"|  MEDIUM: {s.medium_count}  |  LOW: {s.low_count}"
        )
        lines.append("-" * 72)
        lines.append("")

    # Change summary
    lines.append(f"Changes Detected:  {report.total_changes_detected} total, "
                 f"{report.material_changes_detected} material")
    lines.append(f"Disclosure Audit:  {report.disclosed_changes} disclosed, "
                 f"{report.undisclosed_changes} undisclosed")
    lines.append(f"Rules:             {report.rules_evaluated} evaluated, "
                 f"{report.rules_fired} fired, {report.rules_suppressed} suppressed")
    lines.append("")

    return "\n".join(lines)


def _format_findings(report: ComplianceReport) -> str:
    """Format finding details."""
    lines = []

    if report.findings:
        lines.append("=" * 72)
        lines.append("FINDINGS")
        lines.append("=" * 72)
        for i, f in enumerate(report.findings, 1):
            lines.append("")
            lines.append(f"[{i}] {f.rule_id}: {f.rule_title}")
            lines.append(f"    Severity: {f.severity.value}  |  Review: {f.review_priority.value}")
            lines.append(f"    {f.finding_text}")
            if f.evidence:
                lines.append(f"    Field: {f.evidence.field_path}")
                if f.evidence.proposed_text:
                    text = f.evidence.proposed_text[:200]
                    lines.append(f"    Text:  {text}{'...' if len(f.evidence.proposed_text) > 200 else ''}")
            if f.guidance:
                lines.append(f"    Guidance: {f.guidance[:200]}")
            if f.remediation:
                lines.append(f"    Remediation: {f.remediation[:200]}")
    else:
        lines.append("No findings. Revision passes compliance review.")

    return "\n".join(lines)


def _format_remediation(report: ComplianceReport) -> str:
    """Format remediation plan steps."""
    lines = []

    if report.remediation_plan and not report.remediation_plan.is_empty:
        plan = report.remediation_plan
        lines.append("")
        lines.append("=" * 72)
        lines.append("HOW TO FIX — REMEDIATION PLAN")
        lines.append("=" * 72)
        lines.append("")
        if plan.has_blockers:
            lines.append(
                f"*** {plan.critical_steps} CRITICAL fix(es) block release. "
                f"Resolve these first. ***"
            )
            lines.append("")
        lines.append(
            f"Total steps: {plan.total_steps}  "
            f"(CRITICAL: {plan.critical_steps} | HIGH: {plan.high_steps} "
            f"| MEDIUM: {plan.medium_steps} | LOW: {plan.low_steps})"
        )
        if plan.estimated_owners:
            lines.append(f"People who need to act: {'; '.join(plan.estimated_owners)}")
        lines.append("")

        for step in plan.steps:
            severity_tag = step.severity.value
            lines.append(f"  [{step.priority_order}] [{severity_tag}] {step.rule_id}: {step.rule_title}")
            if step.field_path:
                lines.append(f"      Field: {step.field_path}")
            lines.append(f"      Problem:  {step.what_to_fix[:300]}")
            lines.append(f"      Fix:      {step.how_to_fix[:300]}")
            if step.why_it_matters:
                lines.append(f"      Why:      {step.why_it_matters[:300]}")
            if step.owner:
                lines.append(f"      Owner:    {step.owner}")
            if step.authority_basis:
                lines.append(f"      Authority: {', '.join(step.authority_basis)}")
            lines.append("")

    return "\n".join(lines)


def _format_footer(report: ComplianceReport) -> str:
    """Format suppression log, assumptions, and end-of-report marker."""
    lines = []

    # Suppression log
    if report.suppression_log:
        lines.append("")
        lines.append("-" * 72)
        lines.append("RULES NOT APPLIED (suppressed by contract configuration)")
        for entry in report.suppression_log:
            lines.append(f"  - {entry.get('rule_id', '?')}: {entry.get('reason', 'No reason')}")

    # Assumptions
    if report.assumptions:
        lines.append("")
        lines.append("-" * 72)
        lines.append("ASSUMPTIONS")
        for a in report.assumptions:
            lines.append(f"  - {a}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("End of Report")
    lines.append("=" * 72)

    return "\n".join(lines)


def export_text(
    report: ComplianceReport,
    output_path: Optional[Path] = None,
) -> str:
    """
    Export compliance report as human-readable text.

    Args:
        report: The ComplianceReport to export.
        output_path: Optional path to write file.

    Returns:
        Formatted text report.
    """
    text = "\n".join([
        _format_header(report),
        _format_findings(report),
        _format_remediation(report),
        _format_footer(report),
    ])

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)

    return text
