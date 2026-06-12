#!/usr/bin/env python3
"""
Module: hearth.core.scrubber.engine
Purpose: DocScrubber orchestration — parse → segment → deterministic rule
         match → findings (spec v0.3 §3.3, §12 P1-B).

FAILS CLOSED. Every failure anywhere in the pipeline — extraction,
segmentation, a malformed rule, an exploding analyzer, a bug in this very
module — converges to a single `refuse` finding (category "integrity",
basis hearth.fail_closed) and refused=True. The full traceback is logged
before conversion; nothing is suppressed, and nothing unparseable ever
looks like a clean pass (never-suppress-error pattern, §1.1).

Phase 1 is findings-only (§8, §12): the engine verifies no finding carries
suggested_template before returning. The LLM stage is the stubbed
ClauseAnalyzer protocol — no model calls exist in P1.

Safety Critical: False
Financially Critical: True — the cardinal failure mode is failing OPEN.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from hearth.core.scrubber.analyzer import ClauseAnalyzer, NullClauseAnalyzer
from hearth.core.scrubber.extraction import MAX_DOCUMENT_BYTES, extract_text
from hearth.core.scrubber.matcher import (
    RuleMatch,
    collect_document_captures,
    executable_rules,
    match_rules,
    validate_finding_spec,
)
from hearth.core.scrubber.segmentation import segment_clauses
from hearth.data import FAIL_CLOSED_BASIS, JurisdictionPack, ScrubFinding

LOGGER = logging.getLogger("hearth.core.scrubber.engine")

# §8/§12: findings-only mode is a Phase-1 invariant, not a CLI flag. The
# generative-template path stays closed until the §9 #3 counsel opinion.
FINDINGS_ONLY = True


class ScrubberError(Exception):
    """Pipeline-level defect; converges to a refusal (fail CLOSED)."""


@dataclass(frozen=True)
class ScrubRun:
    """Outcome of one scrub run, refusals included."""

    document_name: str
    document_sha256: str | None
    findings: list[ScrubFinding]
    refused: bool
    pack_id: str | None
    contributing_rule_ids: list[str]
    target_price_usd: int | None
    run_date: date
    refusal_reason: str | None = field(default=None)


def scrub_document(
    path: Path | str,
    pack: JurisdictionPack,
    *,
    target_price_usd: int | None = None,
    analyzer: ClauseAnalyzer | None = None,
    run_date: date | None = None,
) -> ScrubRun:
    """Scrub one document against one pack. Never raises: failures refuse."""
    path = Path(path)
    effective_date = run_date or date.today()
    document_sha = _file_sha256_or_none(path)
    try:
        findings, rule_ids = _scrub_or_raise(
            path, pack, target_price_usd, analyzer, effective_date
        )
        return ScrubRun(
            document_name=path.name,
            document_sha256=document_sha,
            findings=findings,
            refused=False,
            pack_id=pack.pack_id,
            contributing_rule_ids=rule_ids,
            target_price_usd=target_price_usd,
            run_date=effective_date,
        )
    except Exception as exc:
        # Boundary of the never-suppress-error pattern: the full traceback
        # is logged, then the failure is SURFACED as a refusal with exit
        # code 2 downstream — the opposite of swallowing it.
        LOGGER.exception("scrub failed closed for %s", path.name)
        return refusal_run(
            path.name,
            reason=str(exc) or exc.__class__.__name__,
            pack=pack,
            document_sha256=document_sha,
            target_price_usd=target_price_usd,
            run_date=effective_date,
        )


def refusal_run(
    document_name: str,
    *,
    reason: str,
    pack: JurisdictionPack | None = None,
    document_sha256: str | None = None,
    target_price_usd: int | None = None,
    run_date: date | None = None,
) -> ScrubRun:
    """Canonical fail-closed outcome: exactly one refuse finding (§12 P1-B)."""
    finding = ScrubFinding(
        document=document_name,
        clause_ref="document",
        category="integrity",
        severity="refuse",
        found="(document was not analyzed)",
        default_analysis=(
            f"Scrub REFUSED — failing closed: {reason} "
            "No clause-level analysis was performed. Do not treat this "
            "document as reviewed; fix the input or the pack and re-run."
        ),
        exposure_usd=None,
        suggested_template=None,
        jurisdiction_basis=FAIL_CLOSED_BASIS,
    )
    return ScrubRun(
        document_name=document_name,
        document_sha256=document_sha256,
        findings=[finding],
        refused=True,
        pack_id=pack.pack_id if pack is not None else None,
        contributing_rule_ids=[],
        target_price_usd=target_price_usd,
        run_date=run_date or date.today(),
        refusal_reason=reason,
    )


def _scrub_or_raise(
    path: Path,
    pack: JurisdictionPack,
    target_price_usd: int | None,
    analyzer: ClauseAnalyzer | None,
    run_date: date,
) -> tuple[list[ScrubFinding], list[str]]:
    text = extract_text(path)
    clauses = segment_clauses(text)

    effective = [rule for rule in pack.rules if rule.is_effective_on(run_date)]
    runnable = executable_rules(effective)
    if not runnable:
        raise ScrubberError(
            f"pack {pack.pack_id} has no executable detection rules effective "
            f"on {run_date.isoformat()} — nothing can be asserted about this document."
        )

    matches = match_rules(clauses, runnable)
    captures = collect_document_captures(matches)
    findings = [
        _build_finding(match, captures, path.name, target_price_usd)
        for match in matches
    ]

    stage = analyzer if analyzer is not None else NullClauseAnalyzer()
    findings.extend(stage.analyze(clauses, pack))

    _enforce_findings_only(findings)
    rule_ids = list(dict.fromkeys(f.jurisdiction_basis for f in findings))
    return findings, rule_ids


def _build_finding(
    match: RuleMatch,
    document_captures: dict[str, str],
    document_name: str,
    target_price_usd: int | None,
) -> ScrubFinding:
    spec = validate_finding_spec(match.rule)
    exposure = _compute_exposure(
        spec.get("exposure"), document_captures, target_price_usd, match.rule.rule_id
    )
    return ScrubFinding(
        document=document_name,
        clause_ref=match.clause.ref,
        category=spec["category"],
        severity=spec["severity"],
        found=match.clause.text,
        default_analysis=spec["default_analysis"],
        exposure_usd=exposure,
        suggested_template=None,
        jurisdiction_basis=match.rule.rule_id,
    )


def _compute_exposure(
    spec: dict[str, Any] | None,
    captures: dict[str, str],
    target_price_usd: int | None,
    rule_id: str,
) -> int | None:
    if spec is None:
        return None
    # validate_finding_spec guarantees the method is known.
    pct_raw = captures.get(str(spec.get("pct_capture", "")))
    if target_price_usd is None:
        LOGGER.info("rule %s: exposure skipped (no --target-price)", rule_id)
        return None
    if pct_raw is None:
        # Cross-clause dependency: the capture comes from a DIFFERENT rule
        # firing elsewhere in the document. Its absence with a target price
        # configured is a signal worth shouting about, not an info line.
        LOGGER.warning(
            "rule %s: exposure omitted — capture %r was not produced by any "
            "rule on this document; the dollar figure is missing, not zero",
            rule_id,
            spec.get("pct_capture"),
        )
        return None
    return round(target_price_usd * float(pct_raw) / 100.0)


def _enforce_findings_only(findings: list[ScrubFinding]) -> None:
    """§8 blocking gate: no generative legal language leaves Phase 1."""
    if not FINDINGS_ONLY:  # pragma: no cover - constant in P1
        return
    for finding in findings:
        if finding.suggested_template is not None:
            raise ScrubberError(
                f"findings-only violation: rule {finding.jurisdiction_basis} "
                "produced suggested_template in Phase 1"
            )


def _file_sha256_or_none(path: Path) -> str | None:
    """Hash the input for the audit trail; None when unreadable/oversized."""
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            return None  # extract_text refuses it moments later
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        # Not suppression: the unreadable file fails the scrub via
        # extract_text moments later; the audit row just records "unknown".
        return None
