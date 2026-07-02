#!/usr/bin/env python3
"""
Module: oracle.build_far_rulepack
Purpose: Builds tiered FAR compliance rule packs from shall-extraction output.

Tier 1 — Summary index: one-liner per FAR Part with requirement counts
Tier 2 — Full requirements for user-specified Parts (--far-parts)

Input:  FAR shall_statements.json from shall_extractor.py
Output: far_rulepack.json in GPCM-compatible format

Usage:
    py scripts/build_far_rulepack.py \
        --input docs/far_shall_extraction/FAR_shall_statements.json \
        --output docs/far_rulepack.json

__safety_critical__: bool = True — builds FAR compliance packs used in review decisions

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import argparse
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("oracle.build_far_rulepack")

# FAR Part titles — official names from acquisition.gov
FAR_PART_TITLES: dict[int, str] = {
    1: "Federal Acquisition Regulations System",
    2: "Definitions of Words and Terms",
    3: "Improper Business Practices and Personal Conflicts of Interest",
    4: "Administrative and Information Matters",
    5: "Publicizing Contract Actions",
    6: "Competition Requirements",
    7: "Acquisition Planning",
    8: "Required Sources of Supplies and Services",
    9: "Contractor Qualifications",
    10: "Market Research",
    11: "Describing Agency Needs",
    12: "Acquisition of Commercial Products and Commercial Services",
    13: "Simplified Acquisition Procedures",
    14: "Sealed Bidding",
    15: "Contracting by Negotiation",
    16: "Types of Contracts",
    17: "Special Contracting Methods",
    18: "Emergency Acquisitions",
    19: "Small Business Programs",
    22: "Application of Labor Laws to Government Acquisitions",
    23: "Environment, Energy and Water Efficiency, Renewable Energy Technologies, Occupational Safety, and Drug-Free Workplace",
    24: "Protection of Privacy and Freedom of Information",
    25: "Foreign Acquisition",
    26: "Other Socioeconomic Programs",
    27: "Patents, Data, and Copyrights",
    28: "Bonds and Insurance",
    29: "Taxes",
    30: "Cost Accounting Standards Administration",
    31: "Contract Cost Principles and Procedures",
    32: "Contract Financing",
    33: "Protests, Disputes, and Appeals",
    34: "Major System Acquisition",
    35: "Research and Development Contracting",
    36: "Construction and Architect-Engineer Contracts",
    37: "Service Contracting",
    38: "Federal Supply Schedule Contracting",
    39: "Acquisition of Information Technology",
    40: "Reserved",
    41: "Acquisition of Utility Services",
    42: "Contract Administration and Audit Services",
    43: "Contract Modifications",
    44: "Subcontracting Policies and Procedures",
    45: "Government Property",
    46: "Quality Assurance",
    47: "Transportation",
    48: "Value Engineering",
    49: "Termination of Contracts",
    50: "Extraordinary Contractual Actions and the Safety Act",
    51: "Use of Government Sources by Contractors",
    52: "Solicitation Provisions and Contract Clauses",
    53: "Forms",
}


def _extract_part_number(section: str) -> int | None:
    """Extract FAR Part number from a section string like '15.304' or '52.212-4'."""
    if not section:
        return None
    part_str = section.split(".")[0].strip()
    if part_str.isdigit():
        return int(part_str)
    return None


def _compress_statement(stmt: dict) -> dict:
    """Compress a single statement to the fields needed for compliance review."""
    return {
        "id": stmt["id"],
        "section": stmt.get("section", ""),
        "page": stmt.get("page", 0),
        "obligation_type": stmt["obligation_type"],
        "obligation_keyword": stmt.get("obligation_keyword", ""),
        "statement_text": stmt["statement_text"],
        "subject": stmt.get("subject", ""),
        "requirement": stmt.get("requirement", ""),
        "keywords": stmt.get("keywords", []),
        "applies_to": stmt.get("applies_to", []),
    }


def _group_by_part(stmts: list[dict]) -> tuple[dict[int, list[dict]], list[dict]]:
    """Group compressed statements by FAR Part; returns (parts, unassigned)."""
    parts: dict[int, list[dict]] = defaultdict(list)
    unassigned: list[dict] = []
    for stmt in stmts:
        part_num = _extract_part_number(stmt.get("section", ""))
        compressed = _compress_statement(stmt)
        if part_num is not None:
            parts[part_num].append(compressed)
        else:
            unassigned.append(compressed)
    LOGGER.info("Grouped into %d Parts + %d unassigned", len(parts), len(unassigned))
    return parts, unassigned


def _build_part_index(parts: dict[int, list[dict]]) -> list[dict]:
    """Build the Tier 1 per-Part summary index."""
    part_index: list[dict] = []
    for part_num in sorted(parts.keys()):
        reqs = parts[part_num]
        mandatory_count = sum(1 for r in reqs if r["obligation_type"] == "mandatory")
        prohibition_count = sum(1 for r in reqs if r["obligation_type"] == "prohibition")
        # WHY implicit_count: mandatory_only keeps implicit obligations, so
        # total_binding must count them too — otherwise
        # total_binding_requirements silently undercounts the pack.
        implicit_count = sum(1 for r in reqs if r["obligation_type"] == "implicit")
        sections = sorted({r["section"] for r in reqs if r["section"]})
        part_index.append({
            "part": part_num,
            "title": FAR_PART_TITLES.get(part_num, f"Part {part_num}"),
            "mandatory_count": mandatory_count,
            "prohibition_count": prohibition_count,
            "implicit_count": implicit_count,
            "total_binding": mandatory_count + prohibition_count + implicit_count,
            "section_count": len(sections),
            "sections_covered": sections[:10],  # sample for index
        })
    return part_index


def build_rulepack(
    input_path: Path,
    *,
    mandatory_only: bool = True,
) -> dict[str, Any]:
    """Build the tiered FAR rule pack.

    Returns a dict with:
        - metadata (schema, source, counts)
        - part_index (Tier 1: summary per Part)
        - parts (Tier 2: full requirements grouped by Part)
        - unassigned (requirements without a detected Part number)
    """
    LOGGER.info("Loading shall extraction: %s", input_path)
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    stmts = data["statements"]
    LOGGER.info("Loaded %d statements", len(stmts))

    # Filter to binding requirements only (including implicit obligations)
    if mandatory_only:
        before = len(stmts)
        stmts = [
            s for s in stmts
            if s["obligation_type"] in ("mandatory", "prohibition", "implicit")
        ]
        LOGGER.info("Filtered to mandatory/prohibition/implicit: %d -> %d", before, len(stmts))

    parts, unassigned = _group_by_part(stmts)

    # Build Tier 1: summary index
    part_index = _build_part_index(parts)

    # Build Tier 2: full requirements per Part
    parts_full: dict[str, list[dict]] = {}
    for part_num in sorted(parts.keys()):
        parts_full[str(part_num)] = parts[part_num]

    total_binding = sum(p["total_binding"] for p in part_index)

    rulepack = {
        "schema_version": "far_rulepack/v1",
        "rule_pack_id": "far-rulepack-complete",
        "standard_id": "FAR",
        "standard_title": "Federal Acquisition Regulation",
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_document": str(input_path),
        # WHY propagated: a pack built from a partial extraction (failed
        # enrichment/implicit chunks) must not masquerade as complete — the
        # registration/promotion gate keys off these fields.
        "extraction_status": data.get("extraction_status", "complete"),
        "failed_page_ranges": data.get("failed_page_ranges", []),
        "chunk_failures": data.get("chunk_failures", []),
        "total_binding_requirements": total_binding,
        "total_unassigned": len(unassigned),
        "parts_count": len(part_index),
        "part_index": part_index,
        "parts": parts_full,
        "unassigned": unassigned,
    }

    return rulepack


def render_tier1_summary(rulepack: dict) -> str:
    """Render the Tier 1 summary index as compact text for prompt injection."""
    lines = [
        f"# FAR Compliance Rule Pack — Summary Index",
        f"Total binding requirements: {rulepack['total_binding_requirements']}",
        f"Parts with requirements: {rulepack['parts_count']}",
        f"Unassigned (no section detected): {rulepack.get('total_unassigned', 0)}",
        "",
        "Part | Title | Mandatory | Prohibitions | Implicit | Total",
        "-----|-------|-----------|--------------|----------|------",
    ]
    for p in rulepack["part_index"]:
        lines.append(
            f"{p['part']:>4} | {p['title'][:50]:<50} | {p.get('mandatory_count', ''):>9} | {p.get('prohibition_count', ''):>12} | {p.get('implicit_count', 0):>8} | {p.get('total_binding', 0):>5}"
        )
    return "\n".join(lines)


def _render_statement_line(r: dict) -> tuple[str, bool]:
    """Render one requirement line, truncating explicitly at 500 chars.

    WHY 500: long statements blow the token budget; the cut must be explicit
    so reviewers can tell a truncated requirement from a complete short one —
    a bare "..." is indistinguishable from prose ellipsis (AUDIT B5).
    """
    kw = r.get("obligation_keyword", "").upper()
    sec = r.get("section") or "??"
    text = r.get("statement_text", "")
    truncated = len(text) > 500
    if truncated:
        text = text[:500] + " [TRUNCATED — see full text in the rule pack]"
    return f"[{kw}] §{sec} p.{r.get('page', 0)}: {text}", truncated


def render_tier2_part(rulepack: dict, part_num: int) -> str:
    """Render full requirements for a specific Part as text for prompt injection."""
    part_key = str(part_num)
    reqs = rulepack.get("parts", {}).get(part_key, [])
    if not reqs:
        return f"# FAR Part {part_num} — No binding requirements found"

    title = FAR_PART_TITLES.get(part_num, f"Part {part_num}")
    lines = [
        f"# FAR Part {part_num}: {title}",
        f"Binding requirements: {len(reqs)}",
        "",
    ]

    truncated = 0
    for r in reqs:
        line, was_truncated = _render_statement_line(r)
        truncated += int(was_truncated)
        lines.append(line)

    if truncated:
        LOGGER.info(
            "FAR Part %s render: %d of %d statements truncated at 500 chars",
            part_num, truncated, len(reqs),
        )

    return "\n".join(lines)


def render_unassigned(rulepack: dict) -> str:
    """Render requirements that could not be mapped to a FAR Part.

    WHY: these are binding requirements; leaving them out of the rendered
    compliance context silently excluded them from every review.
    """
    reqs = rulepack.get("unassigned", [])
    if not reqs:
        return ""
    lines = [
        f"# UNASSIGNED BINDING REQUIREMENTS — no Part number detected ({len(reqs)})",
        "WARNING: the following binding requirements could not be mapped to a "
        "FAR Part and are NOT covered by any Part section above. Review them "
        "explicitly.",
        "",
    ]
    for r in reqs:
        line, _ = _render_statement_line(r)
        lines.append(line)
    return "\n".join(lines)


def render_for_oracle(
    rulepack: dict,
    selected_parts: list[int] | None = None,
) -> str:
    """Build the complete compliance context block for oracle2 prompt injection.

    Always includes Tier 1 summary. If selected_parts is provided,
    includes Tier 2 full text for those Parts.
    """
    sections = [render_tier1_summary(rulepack)]

    if selected_parts:
        sections.append("")
        sections.append(f"## Detailed Requirements for Parts: {', '.join(str(p) for p in selected_parts)}")
        sections.append("")
        for part_num in selected_parts:
            sections.append(render_tier2_part(rulepack, part_num))
            sections.append("")
    else:
        sections.append("")
        sections.append(
            "NOTE: No specific Parts selected. Review document against the "
            "summary index above. Flag any areas where the document fails to "
            "address requirements from relevant Parts."
        )

    unassigned_block = render_unassigned(rulepack)
    if unassigned_block:
        sections.append("")
        sections.append(unassigned_block)

    return "\n".join(sections)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Build FAR rule pack from shall extraction")
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path("docs/far_shall_extraction/FAR_shall_statements.json"),
        help="Path to shall_statements.json",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("docs/far_rulepack.json"),
        help="Output rule pack JSON path",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include permission/recommendation/intent (not just mandatory/prohibition)",
    )
    args = parser.parse_args()

    rulepack = build_rulepack(args.input, mandatory_only=not args.include_all)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(rulepack, f, indent=2, ensure_ascii=False)
    LOGGER.info("Wrote rule pack: %s", args.output)

    # Also write the Tier 1 summary as a standalone text file
    summary_path = args.output.with_suffix(".summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(render_tier1_summary(rulepack))
    LOGGER.info("Wrote summary: %s", summary_path)

    # Stats
    print(f"\n{'='*60}")
    print(f"FAR Rule Pack Generated")
    print(f"{'='*60}")
    print(f"Binding requirements: {rulepack['total_binding_requirements']}")
    print(f"Parts: {rulepack['parts_count']}")
    print(f"Unassigned: {rulepack['total_unassigned']}")
    print(f"JSON: {args.output}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
