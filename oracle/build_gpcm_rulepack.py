#!/usr/bin/env python3
"""
Single-entry pipeline for building GPCM rule packs from standards PDFs.

Stage 1: shall_extractor.py logic to pull raw obligation statements from the PDF
Stage 2: gpcm_rulepack_adapter.py logic to enrich and format the final rule pack
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from oracle.gpcm_rulepack_adapter import default_output_json, infer_standard_id, run_adapter
from oracle.shall_extractor import enrich_with_sonnet, extract_pass1, save_results


logger = logging.getLogger(__name__)


def filter_mandatory_only(result) -> None:
    before = len(result.statements)
    result.statements = [
        statement
        for statement in result.statements
        if statement.obligation_type in ("mandatory", "prohibition")
    ]
    result.total_statements = len(result.statements)
    result.by_type = {}
    for statement in result.statements:
        result.by_type[statement.obligation_type] = (
            result.by_type.get(statement.obligation_type, 0) + 1
        )
    logger.info(
        "Filtered to mandatory/prohibition: %d -> %d",
        before,
        result.total_statements,
    )


def run_pipeline(
    pdf_path: Path,
    output_dir: Path,
    *,
    mandatory_only: bool,
    extractor_sonnet: bool,
    adapter_sonnet: bool,
    api_key: str | None,
    dpi: int,
    extractor_max_pages: int,
    adapter_model: str,
    adapter_dpi: int,
) -> dict[str, Path]:
    logger.info("Pipeline start: %s", pdf_path)
    result = extract_pass1(pdf_path)

    if mandatory_only:
        filter_mandatory_only(result)

    extractor_paths = save_results(result, output_dir)
    logger.info("Extractor JSON: %s", extractor_paths["json"])

    if extractor_sonnet:
        result = enrich_with_sonnet(
            result,
            pdf_path,
            api_key=api_key,
            dpi=dpi,
            max_pages=extractor_max_pages,
        )
        extractor_paths = save_results(result, output_dir)
        logger.info("Extractor Sonnet JSON: %s", extractor_paths["json"])

    standard_id = infer_standard_id(pdf_path, extractor_paths["json"])
    if standard_id is None:
        raise ValueError(f"Could not infer standard ID from {pdf_path}")

    rulepack_path = default_output_json(extractor_paths["json"], standard_id)
    run_adapter(
        input_json=extractor_paths["json"],
        source_pdf=pdf_path,
        standard_id=standard_id,
        output_json=rulepack_path,
        use_sonnet_vision=adapter_sonnet,
        vision_model=adapter_model,
        vision_dpi=adapter_dpi,
    )

    logger.info("Rule pack JSON: %s", rulepack_path)
    return {
        "extract_json": extractor_paths["json"],
        "extract_summary": extractor_paths["summary"],
        "rule_pack": rulepack_path,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Build GPCM rule packs from one or more standards PDFs."
    )
    parser.add_argument("pdfs", nargs="+", help="Path(s) to standards PDFs")
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Directory for extractor and rule-pack outputs (default: same as each PDF)",
    )
    parser.add_argument(
        "--all-statements",
        action="store_true",
        help="Keep all extracted statements instead of filtering to mandatory/prohibition",
    )
    parser.add_argument(
        "--extractor-sonnet",
        action="store_true",
        help="Also run Sonnet Vision enrichment during the extractor stage",
    )
    parser.add_argument(
        "--no-adapter-sonnet",
        dest="adapter_sonnet",
        action="store_false",
        help="Disable targeted Sonnet Vision repair in the adapter stage",
    )
    parser.set_defaults(adapter_sonnet=True)
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--extractor-dpi",
        type=int,
        default=150,
        help="DPI for extractor Sonnet page rendering",
    )
    parser.add_argument(
        "--extractor-max-pages",
        type=int,
        default=0,
        help="Cap pages sent to extractor Sonnet enrichment (0 = all)",
    )
    parser.add_argument(
        "--adapter-model",
        type=str,
        default="claude-sonnet-4-5-20250929",
        help="Anthropic model for adapter targeted repair",
    )
    parser.add_argument(
        "--adapter-dpi",
        type=int,
        default=200,
        help="DPI for adapter Sonnet page rendering",
    )
    args = parser.parse_args()

    outputs: list[dict[str, Path]] = []
    for pdf_arg in args.pdfs:
        pdf_path = Path(pdf_arg)
        output_dir = Path(args.output_dir) if args.output_dir else pdf_path.parent
        result = run_pipeline(
            pdf_path=pdf_path,
            output_dir=output_dir,
            mandatory_only=not args.all_statements,
            extractor_sonnet=args.extractor_sonnet,
            adapter_sonnet=args.adapter_sonnet,
            api_key=args.api_key,
            dpi=args.extractor_dpi,
            extractor_max_pages=args.extractor_max_pages,
            adapter_model=args.adapter_model,
            adapter_dpi=args.adapter_dpi,
        )
        outputs.append(result)

    print("\n" + "=" * 60)
    print("GPCM RULE PACK BUILD COMPLETE")
    print("=" * 60)
    for output in outputs:
        print(f"Extract JSON: {output['extract_json']}")
        print(f"Summary:      {output['extract_summary']}")
        print(f"Rule pack:    {output['rule_pack']}")
        print()


if __name__ == "__main__":
    main()
