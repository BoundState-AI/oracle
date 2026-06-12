#!/usr/bin/env python3
"""
Module: hearth.utils.render
Purpose: Plain-text rendering of scrub results — table, detail blocks, and
         the mandatory banners (spec v0.3 §8, §12 P1-C).

Banner policy is law here, not decoration: every report carries the
not-legal-advice / not-a-brokerage banner (§8), and any finding that cites
a rule without licensee/attorney review renders under the PROVISIONAL
banner (§2.2). Refusals render unmissably.

Safety Critical: False
Financially Critical: True — this is the surface the buyer actually reads;
  dropping a banner or a finding here is dropping it, period.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
import textwrap

from hearth.core.scrubber.engine import ScrubRun
from hearth.data import JurisdictionPack, MicroRule, ScrubFinding

LOGGER = logging.getLogger("hearth.utils.render")

WIDTH = 74
RULE_BAR = "=" * WIDTH
THIN_BAR = "-" * WIDTH

LEGAL_BANNER = (
    "NOT LEGAL ADVICE. NOT A LICENSED BROKERAGE. HEARTH is an analytics "
    "and document-intelligence tool used by the buyer on their own behalf "
    "(C.R.S. 12-10-201). Every finding requires review by your own "
    "licensee or attorney before any action."
)

PROVISIONAL_BANNER_TEMPLATE = (
    "PROVISIONAL BASIS: {provisional} of {total} findings cite rules that "
    "have NOT yet had licensee/attorney review (status: provisional). "
    "Treat them as leads to verify with your licensed human, not as "
    "conclusions (spec §2.2/§8)."
)


def render_report(run: ScrubRun, pack: JurisdictionPack | None) -> str:
    """Render the full findings report for one scrub run."""
    rules_by_id = {rule.rule_id: rule for rule in pack.rules} if pack else {}
    lines: list[str] = [RULE_BAR, " HEARTH DocScrubber — findings-only (Phase 1)", RULE_BAR]
    lines.extend(_wrap(LEGAL_BANNER, prefix=" "))
    lines.append(THIN_BAR)
    lines.extend(_summary_lines(run))

    if run.refused:
        lines.append(THIN_BAR)
        lines.extend(_refusal_lines(run))

    provisional_banner = _provisional_banner(run.findings, rules_by_id)
    if provisional_banner:
        lines.append(THIN_BAR)
        lines.extend(provisional_banner)

    if run.findings:
        lines.append(THIN_BAR)
        lines.extend(_table_lines(run.findings, rules_by_id))
        lines.append(THIN_BAR)
        lines.extend(_detail_lines(run.findings, rules_by_id))
    else:
        lines.append(THIN_BAR)
        lines.append(" No findings. This is NOT a clean bill of health: only the")
        lines.append(" pack's known defaults were checked (deterministic stage only).")

    lines.append(RULE_BAR)
    return "\n".join(lines)


def _summary_lines(run: ScrubRun) -> list[str]:
    target = f"${run.target_price_usd:,}" if run.target_price_usd else "(not set)"
    return [
        f" Document     : {run.document_name}",
        f" Pack         : {run.pack_id or '(unavailable)'}",
        f" Run date     : {run.run_date.isoformat()}    Target price: {target}",
        f" Findings     : {len(run.findings)}",
    ]


def _refusal_lines(run: ScrubRun) -> list[str]:
    lines = [" *** SCRUB REFUSED — FAILING CLOSED (exit code 2) ***"]
    lines.extend(_wrap(run.refusal_reason or "unspecified reason", prefix="     "))
    lines.extend(
        _wrap(
            "No clause-level analysis was performed; this document has NOT "
            "been reviewed.",
            prefix=" ",
        )
    )
    return lines


def _provisional_banner(
    findings: list[ScrubFinding], rules_by_id: dict[str, MicroRule]
) -> list[str]:
    provisional = sum(
        1 for f in findings if _is_provisional(f, rules_by_id)
    )
    if provisional == 0:
        return []
    text = PROVISIONAL_BANNER_TEMPLATE.format(
        provisional=provisional, total=len(findings)
    )
    return [" !! " + line for line in textwrap.wrap(text, WIDTH - 5)]


def _is_provisional(finding: ScrubFinding, rules_by_id: dict[str, MicroRule]) -> bool:
    rule = rules_by_id.get(finding.jurisdiction_basis)
    return rule is not None and rule.status == "provisional"


def _table_lines(
    findings: list[ScrubFinding], rules_by_id: dict[str, MicroRule]
) -> list[str]:
    header = f"  {'#':>2}  {'SEV':<6} {'CATEGORY':<13} {'CLAUSE':<9} {'RULE':<28} {'EXPOSURE':>10}"
    lines = [header]
    for number, finding in enumerate(findings, start=1):
        rule_label = finding.jurisdiction_basis
        if _is_provisional(finding, rules_by_id):
            rule_label += " [P]"
        exposure = f"${finding.exposure_usd:,}" if finding.exposure_usd is not None else "-"
        lines.append(
            f"  {number:>2}  {finding.severity:<6} {finding.category:<13} "
            f"{finding.clause_ref:<9} {rule_label:<28} {exposure:>10}"
        )
    return lines


def _detail_lines(
    findings: list[ScrubFinding], rules_by_id: dict[str, MicroRule]
) -> list[str]:
    lines: list[str] = []
    for number, finding in enumerate(findings, start=1):
        rule = rules_by_id.get(finding.jurisdiction_basis)
        status = " (PROVISIONAL)" if _is_provisional(finding, rules_by_id) else ""
        lines.append(
            f" [{number}] {finding.severity.upper()} {finding.category} @ "
            f"{finding.clause_ref} — rule {finding.jurisdiction_basis}{status}"
        )
        if rule is not None:
            lines.extend(_wrap(f"source: {rule.source}", prefix="     "))
        lines.extend(_wrap(f'found: "{_clip(finding.found)}"', prefix="     "))
        lines.extend(_wrap(f"default analysis: {finding.default_analysis}", prefix="     "))
        if finding.exposure_usd is not None:
            lines.append(f"     exposure: ${finding.exposure_usd:,}")
        lines.append("     requires human review: yes")
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def render_pack_status(pack: JurisdictionPack, pack_path, freshness) -> str:
    """Render governance posture for one pack (§13 P2-B: hearth pack-status)."""
    by_status: dict[str, int] = {}
    schemes: dict[str, int] = {}
    for rule in pack.rules:
        by_status[rule.status] = by_status.get(rule.status, 0) + 1
        scheme = rule.signature.split(":", 1)[0]
        schemes[scheme] = schemes.get(scheme, 0) + 1

    lines = [RULE_BAR, " HEARTH JurisdictionPack status", RULE_BAR]
    lines.append(f" Pack         : {pack.pack_id}")
    lines.append(f" File         : {pack_path}")
    lines.append(f" Owner        : {pack.governance.owner}")
    lines.append(
        f" Governance   : {pack.governance.status}    update SLA: "
        f"{pack.governance.update_sla_days} days"
    )
    lines.append(
        f" Rules        : {len(pack.rules)} ("
        + ", ".join(f"{count} {status}" for status, count in sorted(by_status.items()))
        + ")"
    )
    lines.append(
        " Signatures   : "
        + ", ".join(f"{count} {scheme}" for scheme, count in sorted(schemes.items()))
        + "  (STUB1 = drift detection only, not review attestation)"
    )
    lines.append(THIN_BAR)
    lines.append(f" Source freshness (checked {freshness.checked_on.isoformat()}):")
    if not freshness.issues:
        lines.append("   all monitored sources snapshotted, hashed, and within SLA")
    for issue in freshness.issues:
        lines.extend(_wrap(f"[{issue.kind}] {issue.source} — {issue.detail}", prefix="   "))
    if not freshness.fresh:
        lines.append(THIN_BAR)
        lines.extend(
            _wrap(
                "STALE BASIS: one or more monitored sources is missing or past "
                "SLA. Findings from this pack may rest on a changed legal "
                "reality — re-verify sources and re-snapshot (§2.2).",
                prefix=" !! ",
            )
        )
    provisional = by_status.get("provisional", 0)
    if provisional:
        lines.append(THIN_BAR)
        lines.extend(
            _wrap(
                f"{provisional} of {len(pack.rules)} rules are provisional "
                "(pending licensee/attorney review) and render under the "
                "PROVISIONAL banner in all outputs (§2.2/§8).",
                prefix=" !! ",
            )
        )
    lines.append(RULE_BAR)
    return "\n".join(lines)


def _clip(text: str, limit: int = 600) -> str:
    """The verbatim clause lives in the JSON/audit output; the rendered
    report clips pathological clause lengths for readability."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "… [clipped; full text in JSON output]"


def _wrap(text: str, prefix: str) -> list[str]:
    return [
        prefix + line for line in textwrap.wrap(text, WIDTH - len(prefix) - 1)
    ] or [prefix.rstrip()]
