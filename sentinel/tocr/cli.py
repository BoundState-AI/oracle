#!/usr/bin/env python3
"""
SENTINEL-TOCR — Standalone CLI
Task Order Compliance Review

Usage:
    # Review two revisions (prior → proposed):
    python -m sentinel.tocr.cli review prior.docx proposed.docx

    # Review a chain of revisions (oldest → newest):
    python -m sentinel.tocr.cli review rev35.docx rev36.docx rev37.docx

    # Standalone scan (single TO):
    python -m sentinel.tocr.cli scan task_order.docx

    # With Sonnet-enriched remediation (requires Bedrock or ANTHROPIC_API_KEY):
    python -m sentinel.tocr.cli review --sonnet prior.docx proposed.docx

    # Export to file:
    python -m sentinel.tocr.cli review prior.docx proposed.docx -o report.txt
    python -m sentinel.tocr.cli review prior.docx proposed.docx -o report.json

BoundState AI 2026
Classification: BoundState Proprietary
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.exports.json_export import export_json
from sentinel.tocr.exports.text_export import export_text
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import ContractType, RevisionStatus
from sentinel.tocr.parsers.essca_parser import ESSCAParser


def _parse_file(path: Path) -> "TaskOrder":
    """Parse a DOCX file into a TaskOrder."""
    if not path.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    suffix = path.suffix.lower()
    if suffix == ".docx":
        parser = ESSCAParser()
        to = parser.parse(path)
        return to
    elif suffix == ".json":
        from sentinel.tocr.parsers.atoms_parser import ATOMSParser
        parser = ATOMSParser()
        to = parser.parse(path)
        return to
    else:
        print(f"ERROR: Unsupported file type: {suffix} (use .docx or .json)", file=sys.stderr)
        sys.exit(1)


def _build_config(args) -> ContractConfig:
    """Build contract config from CLI args."""
    contract_types = [ContractType.IDIQ, ContractType.TASK_ORDER]

    return ContractConfig(
        contract_type=contract_types,
        agency=args.agency,
        center=args.center,
        vehicle=args.vehicle,
        local_policy_pack=args.pack,
        revision_status=RevisionStatus.RELEASED,
    )


def _output_report(report, output_path=None):
    """Output report to stdout or file."""
    if output_path:
        p = Path(output_path)
        if p.suffix.lower() == ".json":
            content = export_json(report)
            p.write_text(content, encoding="utf-8")
            print(f"JSON report written to: {p}")
        else:
            content = export_text(report)
            p.write_text(content, encoding="utf-8")
            print(f"Text report written to: {p}")
    else:
        print(export_text(report))


def cmd_review(args):
    """Run pairwise compliance review."""
    files = [Path(f) for f in args.files]
    if len(files) < 2:
        print("ERROR: review requires at least 2 files (prior and proposed)", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {len(files)} task order revision(s)...", file=sys.stderr)
    revisions = []
    for f in files:
        to = _parse_file(f)
        delivs = sum(len(st.deliverables) for st in to.sub_tasks)
        print(f"  {f.name}: Rev {to.revision_number} | "
              f"{len(to.sub_tasks)} sub-tasks | {delivs} deliverables | "
              f"Emergency: {to.emergency_designation}", file=sys.stderr)
        revisions.append(to)

    config = _build_config(args)
    conductor = TOCRConductor(config=config)

    if args.sonnet:
        print("\nRunning with Sonnet-enriched remediation...", file=sys.stderr)
        async def _run():
            reports = []
            for i in range(len(revisions) - 1):
                prior, proposed = revisions[i], revisions[i + 1]
                print(f"\nReviewing: {prior.revision_number} → {proposed.revision_number}", file=sys.stderr)
                report = await conductor.review_with_sonnet(prior, proposed)
                reports.append(report)
            return reports
        reports = asyncio.run(_run())
    else:
        reports = []
        for i in range(len(revisions) - 1):
            prior, proposed = revisions[i], revisions[i + 1]
            print(f"\nReviewing: {prior.revision_number} → {proposed.revision_number}", file=sys.stderr)
            report = conductor.review(prior, proposed)
            reports.append(report)

    print("", file=sys.stderr)
    for i, report in enumerate(reports):
        if len(reports) > 1:
            print(f"\n{'='*80}")
            print(f"REVIEW {i+1} of {len(reports)}: "
                  f"{report.prior_revision} → {report.proposed_revision}")
            print(f"{'='*80}\n")
        _output_report(report, args.output if len(reports) == 1 else None)

    # If multiple reports and output requested, write each
    if len(reports) > 1 and args.output:
        p = Path(args.output)
        for i, report in enumerate(reports):
            suffix = p.suffix
            out = p.with_name(f"{p.stem}_{i+1}{suffix}")
            _output_report(report, str(out))


def cmd_scan(args):
    """Run standalone compliance scan."""
    files = [Path(f) for f in args.files]
    if len(files) < 1:
        print("ERROR: scan requires at least 1 file", file=sys.stderr)
        sys.exit(1)

    config = _build_config(args)
    conductor = TOCRConductor(config=config)

    for f in files:
        to = _parse_file(f)
        delivs = sum(len(st.deliverables) for st in to.sub_tasks)
        print(f"Scanning: {f.name} | Rev {to.revision_number} | "
              f"{len(to.sub_tasks)} sub-tasks | {delivs} deliverables", file=sys.stderr)

        if args.sonnet:
            report = asyncio.run(conductor.scan_with_sonnet(to))
        else:
            report = conductor.scan(to)

        print("", file=sys.stderr)
        _output_report(report, args.output)


def main():
    parser = argparse.ArgumentParser(
        prog="sentinel-tocr",
        description="SENTINEL-TOCR: Task Order Compliance Review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s review prior.docx proposed.docx
  %(prog)s review rev35.docx rev36.docx rev37.docx
  %(prog)s review --sonnet prior.docx proposed.docx
  %(prog)s scan task_order.docx
  %(prog)s review prior.docx proposed.docx -o report.txt
  %(prog)s review prior.docx proposed.docx -o report.json
        """,
    )

    # Common args
    parser.add_argument("--agency", default="NASA", help="Agency (default: NASA)")
    parser.add_argument("--center", default="MSFC", help="Center (default: MSFC)")
    parser.add_argument("--vehicle", default="ESSCA", help="Contract vehicle (default: ESSCA)")
    parser.add_argument("--pack", default="ESSCA-MSFC", help="Local policy pack (default: ESSCA-MSFC)")
    parser.add_argument("-o", "--output", help="Output file path (.txt or .json)")
    parser.add_argument("--sonnet", action="store_true",
                        help="Enrich remediation with Bedrock Sonnet (requires AWS credentials or ANTHROPIC_API_KEY)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # review subcommand
    review_parser = subparsers.add_parser("review", help="Compare two or more TO revisions")
    review_parser.add_argument("files", nargs="+", help="DOCX files in order (oldest → newest)")

    # scan subcommand
    scan_parser = subparsers.add_parser("scan", help="Standalone compliance scan of a single TO")
    scan_parser.add_argument("files", nargs="+", help="DOCX file(s) to scan")

    args = parser.parse_args()

    if args.command == "review":
        cmd_review(args)
    elif args.command == "scan":
        cmd_scan(args)


if __name__ == "__main__":
    main()
