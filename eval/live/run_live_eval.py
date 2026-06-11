#!/usr/bin/env python3
"""
Module: eval.live.run_live_eval
Purpose: Release-gate runner — executes seeded-defect and known-sound cases
         against REAL vendors and scores detection, false positives, and
         cross-round retention/drift.

Costs real money (roughly $5-15 per full run at 2 rounds) and is
nondeterministic: it gates RELEASES, not commits, and never runs in CI.

Usage:
    python -m eval.live.run_live_eval                 # all cases
    python -m eval.live.run_live_eval --case seeded_payment_spec
    python -m eval.live.run_live_eval --max-rounds 2 --output-dir eval_runs/r1

Exit code 0 = all gates passed (every seeded defect raised, false-positive
budget respected). Non-zero = a gate failed; see eval_report.md.

BoundState AI 2026
Classification: BoundState Proprietary

__safety_critical__: bool = True — gates release claims about review quality
"""

from __future__ import annotations

__safety_critical__: bool = True

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from eval.live.scoring import (
    collect_raised_issues,
    collect_surfaced_issues,
    score_detection,
    score_false_positives,
    score_retention,
)

CASES_DIR = Path(__file__).parent / "cases"

REQUIRED_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY")
# Gemini accepts either spelling.
GEMINI_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _check_keys() -> list[str]:
    missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
    if not any(os.environ.get(k) for k in GEMINI_KEYS):
        missing.append("GEMINI_API_KEY or GOOGLE_API_KEY")
    return missing


def _list_cases() -> list[str]:
    return sorted(p.stem for p in CASES_DIR.glob("*.md"))


def _run_case(case: str, max_rounds: int, output_dir: Path) -> dict:
    """Run one case live and score it. Returns the case's report dict."""
    from oracle.oracle2 import run_review

    document = (CASES_DIR / f"{case}.md").read_text(encoding="utf-8")
    expected = json.loads(
        (CASES_DIR / f"{case}.expected.json").read_text(encoding="utf-8")
    )

    case_dir = output_dir / case
    case_dir.mkdir(parents=True, exist_ok=True)

    session = run_review(
        draft=document,
        document_path=str(CASES_DIR / f"{case}.md"),
        max_rounds=max_rounds,
        output_dir=case_dir,
    )

    raised = collect_raised_issues(session)
    surfaced = collect_surfaced_issues(session)
    expected_defects = expected.get("expected_defects", [])

    report: dict = {
        "case": case,
        "converged": session.converged,
        "consensus_type": session.consensus_type,
        "convergence_reason": session.convergence_reason,
        "rounds": len(session.rounds),
        # Detection is scored on what reviewers RAISED; surfacing on what
        # survived synthesis. A defect raised but not surfaced is a
        # dissent-fidelity failure, not a detection failure — the split
        # keeps those two problems distinguishable.
        "detection_raised": score_detection(expected_defects, raised),
        "detection_surfaced": score_detection(expected_defects, surfaced),
        "retention": score_retention(session),
    }

    gates: list[bool] = []
    if expected_defects:
        gates.append(report["detection_raised"]["detection_rate"] == 1.0)
    if "max_false_critical_high" in expected:
        report["false_positives"] = score_false_positives(
            surfaced, expected["max_false_critical_high"]
        )
        gates.append(report["false_positives"]["within_budget"])
    report["gates_passed"] = all(gates) if gates else True

    summary_path = case_dir / "session_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        report["usage_totals"] = summary.get("usage_totals", {})

    return report


def _render_markdown(reports: list[dict]) -> str:
    lines = ["# ORACLE Live Eval Report", ""]
    for r in reports:
        status = "PASS" if r["gates_passed"] else "FAIL"
        lines.append(f"## {r['case']} — {status}")
        lines.append("")
        lines.append(f"- Converged: {r['converged']} ({r['consensus_type'] or 'n/a'})")
        raised = r["detection_raised"]
        lines.append(
            f"- Seeded defects raised: {len(raised['detected'])}/"
            f"{len(raised['detected']) + len(raised['missed'])}"
            + (f" — MISSED: {', '.join(raised['missed'])}" if raised["missed"] else "")
        )
        surfaced = r["detection_surfaced"]
        if surfaced["missed"] and not raised["missed"]:
            lines.append(
                f"- Dissent-fidelity gap: raised but lost in synthesis: "
                f"{', '.join(m for m in surfaced['missed'] if m not in raised['missed'])}"
            )
        if "false_positives" in r:
            fp = r["false_positives"]
            lines.append(
                f"- False critical/high on sound spec: {fp['critical_high_count']}"
                f" (budget {fp['budget']})"
            )
        drift = r["retention"]["drift_events"]
        if drift:
            lines.append(f"- Drift events: {len(drift)}")
            for e in drift:
                lines.append(f"  - {e['oracle']}: [{e['severity']}] {e['title']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="ORACLE live release-gate eval")
    parser.add_argument("--case", action="append", help="Case stem (repeatable; default: all)")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    missing = _check_keys()
    if missing:
        print(f"Refusing to run: missing API keys: {', '.join(missing)}")
        print("Live eval spends real money and needs all four vendors.")
        return 2

    cases = args.case or _list_cases()
    output_dir = Path(args.output_dir or f"eval_runs/{datetime.now():%Y%m%d-%H%M%S}")
    output_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    for case in cases:
        print(f"=== Running live case: {case} (max {args.max_rounds} rounds) ===")
        reports.append(_run_case(case, args.max_rounds, output_dir))

    (output_dir / "eval_report.json").write_text(
        json.dumps(reports, indent=2), encoding="utf-8"
    )
    markdown = _render_markdown(reports)
    (output_dir / "eval_report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Reports written to {output_dir}/")

    return 0 if all(r["gates_passed"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
