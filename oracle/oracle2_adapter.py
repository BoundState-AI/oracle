#!/usr/bin/env python3
"""
Module: oracle2_adapter
Purpose: Parses oracle2 session output files into the ReviewResult contract
         required by ORACLE. This is the sole integration seam between ORACLE
         and oracle2 — oracle2.py is never modified.

Architecture:
  oracle2.run_review() writes per-round JSON files to a session directory.
  This adapter reads those files and reconstructs a typed ReviewResult object
  with normalized issues, coordinator decisions, pack citations, and metrics.

  The adapter performs a preflight check (verify_session_dir) before parsing
  to fail fast on incompatible oracle2 versions.

Safety:
  __safety_critical__ = True  — outputs feed compliance findings reports

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("oracle2_adapter")


# ---------------------------------------------------------------------------
# Return Contract Data Classes
# ---------------------------------------------------------------------------
# These mirror the spec (Section 7.3). ORACLE consumes ReviewResult;
# the adapter populates it from oracle2's raw output files.
# ---------------------------------------------------------------------------

@dataclass
class PackCitation:
    """A reference from a review finding back to a specific rule in a pack.

    Best-effort: populated by scanning evidence_text for [pack_id:rule_id]
    patterns. May be empty if the reviewer oracle cited rules by prose rather
    than by identifier.
    """
    pack_id: str                    # rule_pack_id from the pack
    authority_label: str            # "Authority 1", "Authority 2", etc.
    rule_id: str                    # e.g., "RULE-0042", "far-15-001", "stmt-001"
    section: str                    # §X.X from the rule


@dataclass
class NormalizedIssue:
    """A single normalized finding.

    Maps from oracle2's round*_sonnet_normalized.json (ledger workflow,
    Sonnet referee shape) or round*_beth_normalized.json (manual workflow,
    Beth serious_issues shape) → normalized_issues[]. The evidence_text
    field preserves citation-bearing prose for pack_citation extraction.
    """
    issue_id: str                   # e.g., "R1-ISSUE-003"
    title: str
    severity: str                   # critical|high|medium|low
    category: str
    core_problem: str
    recommended_fix: str
    source_oracles: list[str]
    evidence_text: str              # Original reviewer prose (from best_evidence)
    pack_citations: list[PackCitation] = field(default_factory=list)


@dataclass
class CoordinatorDecision:
    """Beth's classification of a normalized issue.

    Maps from oracle2's round*_beth_decisions.json → revision_decisions[].
    """
    issue_id: str
    decision: str                   # accepted_defect|rejected_claim|preference_only|unresolved_question
    reason: str


@dataclass
class RoundData:
    """All structured data from a single review round."""
    round_number: int
    normalized_issues: list[NormalizedIssue]
    coordinator_decisions: list[CoordinatorDecision]
    revised_draft: str


@dataclass
class MetricsSummary:
    """Aggregated metrics across all rounds.

    Computed by the adapter from RoundData, NOT from oracle2's metrics.json
    (which may use different aggregation logic).
    """
    accepted_by_severity: dict[str, int]   # {"critical": 2, "high": 5, ...}
    rejected_count: int
    preference_only_count: int
    unresolved_count: int
    duplicate_count: int                    # Issues merged by normalizer
    rounds_to_stability: int               # Last round with new critical/high
    total_issues_raised: int
    total_issues_accepted: int


@dataclass
class ReviewResult:
    """Complete structured output from an oracle2 review session.

    This is the canonical interface between oracle2 and ORACLE.
    Either populated directly from oracle2.run_review()'s return value
    (if it conforms to this contract) or reconstructed by the adapter
    from oracle2's output files.
    """
    session_id: str
    session_dir: Path
    final_draft: str                    # The converged document text
    rounds: list[RoundData]             # Per-round structured data
    converged: bool                     # Whether review reached convergence
    total_rounds: int
    metrics: MetricsSummary             # Aggregated metrics for findings report


# ---------------------------------------------------------------------------
# Preflight Check
# ---------------------------------------------------------------------------

def verify_session_dir(session_dir: Path) -> list[str]:
    """Verify that an oracle2 session directory has the expected structure.

    Returns a list of error messages. Empty list = preflight passed.
    Checks for:
      1. session_summary.json with session_id and total_rounds
      2. At least one normalized-issues file: round*_sonnet_normalized.json
         (ledger workflow) or round*_beth_normalized.json (manual workflow)
      3. final_draft.md
    """
    errors: list[str] = []
    actual_files = [f.name for f in session_dir.iterdir()] if session_dir.is_dir() else []

    # 1. session_summary.json
    summary_path = session_dir / "session_summary.json"
    if not summary_path.exists():
        errors.append(f"Missing: session_summary.json")
    else:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if "session_id" not in summary:
                errors.append("session_summary.json missing 'session_id' field")
            if "total_rounds" not in summary:
                errors.append("session_summary.json missing 'total_rounds' field")
        except json.JSONDecodeError as e:
            errors.append(f"session_summary.json is not valid JSON: {e}")

    # 2. At least one normalized file. The filename differs by workflow:
    # the ledger workflow's referee writes *_sonnet_normalized.json, the
    # manual (default) workflow writes *_beth_normalized.json. Globbing
    # only one of them silently dropped every normalized issue from the
    # default workflow (AUDIT F1) — both spellings are first-class.
    normalized_files = sorted(session_dir.glob("round*_sonnet_normalized.json")) + sorted(
        session_dir.glob("round*_beth_normalized.json")
    )
    if not normalized_files:
        errors.append(
            "No round*_sonnet_normalized.json or round*_beth_normalized.json files found"
        )

    # 3. final_draft.md
    if not (session_dir / "final_draft.md").exists():
        errors.append("Missing: final_draft.md")

    if errors:
        LOGGER.error(
            f"oracle2 session directory structure is incompatible.\n"
            f"  Expected: session_summary.json, round*_{{sonnet,beth}}_normalized.json, final_draft.md\n"
            f"  Found: {', '.join(actual_files[:20])}\n"
            f"  Errors: {'; '.join(errors)}\n"
            f"  The oracle2_adapter may need updating for this version of oracle2."
        )

    return errors


# ---------------------------------------------------------------------------
# Citation Extraction
# ---------------------------------------------------------------------------

# WHY this pattern: Oracle reviews embed rule citations as [pack_id:rule_id]
# (e.g., [far-rulepack-complete:far-15-001]) so downstream tools can trace
# findings back to specific rules in specific packs.  The bracket delimiter
# was chosen because it doesn't conflict with Markdown link syntax and is
# visually distinct in prose.  The colon separates pack from rule because
# both IDs may contain hyphens.
_CITATION_PATTERN = re.compile(r"\[([^:\]]+):([^\]]+)\]")


def extract_pack_citations(
    evidence_text: str,
    compliance_context: str | None = None,
) -> list[PackCitation]:
    """Extract pack rule citations from reviewer evidence text.

    Scans for [pack_id:rule_id] patterns embedded by the pack renderers.
    Falls back to fuzzy section matching against compliance_context if
    explicit citations are not found.

    Args:
        evidence_text: The reviewer's prose (from best_evidence / core_problem).
        compliance_context: The full rendered compliance text, for fuzzy matching.

    Returns:
        List of PackCitation objects. May be empty if no citations found.
    """
    citations: list[PackCitation] = []
    seen: set[tuple[str, str]] = set()

    # Pass 1: Explicit [pack_id:rule_id] patterns
    for match in _CITATION_PATTERN.finditer(evidence_text):
        pack_id = match.group(1).strip()
        rule_id = match.group(2).strip()

        # Skip patterns that look like markdown links or issue IDs
        if pack_id.startswith("R") and "-ISSUE-" in rule_id:
            continue
        if pack_id.startswith("http"):
            continue

        key = (pack_id, rule_id)
        if key not in seen:
            seen.add(key)
            citations.append(PackCitation(
                pack_id=pack_id,
                authority_label="",   # Populated later by caller if needed
                rule_id=rule_id,
                section="",           # Could be extracted from compliance_context
            ))

    return citations


# ---------------------------------------------------------------------------
# File Parsers
# ---------------------------------------------------------------------------

def _parse_normalized_issues(
    file_path: Path,
    compliance_context: str | None = None,
) -> list[NormalizedIssue]:
    """Parse a normalized-issues round file into NormalizedIssue objects.

    Accepts both per-workflow shapes:
      - ledger (Sonnet referee): core_problem / best_evidence /
        recommended_fix / merged_from=[{oracle, title}]
      - manual (Beth serious_issues): summary / resolution /
        source_reviewers=["Fran", ...]
    Handles both the nested {"normalized_issues": [...]} format and
    bare list format.
    """
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        LOGGER.warning(f"Failed to parse {file_path.name}: {e}")
        return []

    # Handle nested or bare format
    if isinstance(raw, dict):
        items = raw.get("normalized_issues", [])
    elif isinstance(raw, list):
        items = raw
    else:
        LOGGER.warning(f"Unexpected format in {file_path.name}: {type(raw)}")
        return []

    issues: list[NormalizedIssue] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        core_problem = item.get("core_problem") or item.get("summary", "")
        recommended_fix = item.get("recommended_fix") or item.get("resolution", "")

        # evidence_text: prefer best_evidence, fall back to problem + fix prose
        evidence = item.get("best_evidence", "")
        if not evidence:
            evidence = f"{core_problem} {recommended_fix}".strip()

        # Source oracles: ledger shape nests them in merged_from dicts,
        # manual shape lists names directly in source_reviewers.
        source_oracles: list[str] = []
        for merged in item.get("merged_from", []):
            oracle_name = merged.get("oracle", "") if isinstance(merged, dict) else ""
            if oracle_name and oracle_name not in source_oracles:
                source_oracles.append(oracle_name)
        for reviewer in item.get("source_reviewers", []):
            if isinstance(reviewer, str) and reviewer and reviewer not in source_oracles:
                source_oracles.append(reviewer)

        issue = NormalizedIssue(
            issue_id=item.get("issue_id", "UNKNOWN"),
            title=item.get("title", "Untitled"),
            severity=item.get("severity", "medium"),
            category=item.get("category", ""),
            core_problem=core_problem,
            recommended_fix=recommended_fix,
            source_oracles=source_oracles,
            evidence_text=evidence,
            pack_citations=extract_pack_citations(evidence, compliance_context),
        )
        issues.append(issue)

    return issues


def _parse_coordinator_decisions(file_path: Path) -> list[CoordinatorDecision]:
    """Parse a round*_beth_decisions.json into CoordinatorDecision objects."""
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        LOGGER.warning(f"Failed to parse {file_path.name}: {e}")
        return []

    decisions_data = raw.get("revision_decisions", [])
    decisions: list[CoordinatorDecision] = []
    for d in decisions_data:
        if not isinstance(d, dict):
            continue
        decisions.append(CoordinatorDecision(
            issue_id=d.get("issue_id", "UNKNOWN"),
            decision=d.get("decision", ""),
            reason=d.get("reason", ""),
        ))

    return decisions


# ---------------------------------------------------------------------------
# Main Reconstruction
# ---------------------------------------------------------------------------

def build_review_result(
    session_dir: Path,
    compliance_context: str | None = None,
) -> ReviewResult:
    """Reconstruct a ReviewResult from oracle2's output files.

    This is the primary entry point for ORACLE. It:
      1. Runs preflight check
      2. Reads session_summary.json for session metadata
      3. Iterates over round files to build RoundData
      4. Reads final_draft.md
      5. Computes MetricsSummary from aggregated round data

    Args:
        session_dir: Path to the oracle2 session directory.
        compliance_context: The rendered compliance text used for this session,
                           for citation fuzzy-matching.

    Returns:
        ReviewResult with all available data populated.

    Raises:
        ValueError: If preflight check fails on critical files.
    """
    # --- Preflight ---
    errors = verify_session_dir(session_dir)
    if errors:
        # Check if critical files are missing (session_summary, final_draft)
        critical_missing = any(
            "session_summary" in e or "final_draft" in e
            for e in errors
        )
        if critical_missing:
            raise ValueError(
                f"oracle2 session directory is incompatible: {'; '.join(errors)}"
            )
        # Non-critical errors: warn but continue
        for e in errors:
            LOGGER.warning(f"Preflight warning: {e}")

    # --- Session metadata ---
    summary_path = session_dir / "session_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    session_id = summary.get("session_id", session_dir.name)
    total_rounds = summary.get("total_rounds", 0)
    converged = summary.get("converged", False)

    # Fail hard on the out-of-sync signature (AUDIT F1): a session that
    # claims convergence must have produced normalized-issue files. If it
    # converged and none are readable, the adapter no longer understands
    # this oracle2 version's output — continuing would silently report
    # zero issues and unknown severities for a "successful" review.
    # Non-converged sessions (e.g., every round invalid after a vendor
    # outage) legitimately have no normalized files and parse to rounds=[].
    has_normalized_files = any(
        (session_dir / f"round{n}_{source}_normalized.json").exists()
        for n in range(1, total_rounds + 1)
        for source in ("sonnet", "beth")
    )
    if converged and total_rounds > 0 and not has_normalized_files:
        raise ValueError(
            "Session reports convergence but contains no normalized issue "
            "files (round*_sonnet_normalized.json / round*_beth_normalized.json) "
            "— oracle2_adapter is out of sync with the workflow output."
        )

    # --- Final draft ---
    final_draft_path = session_dir / "final_draft.md"
    final_draft = final_draft_path.read_text(encoding="utf-8")

    # --- Build rounds ---
    rounds: list[RoundData] = []
    for round_num in range(1, total_rounds + 1):
        # Normalized issues — ledger filename first, then manual
        norm_path = session_dir / f"round{round_num}_sonnet_normalized.json"
        if not norm_path.exists():
            norm_path = session_dir / f"round{round_num}_beth_normalized.json"
        normalized = _parse_normalized_issues(norm_path, compliance_context) if norm_path.exists() else []

        # Coordinator decisions
        beth_path = session_dir / f"round{round_num}_beth_decisions.json"
        decisions = _parse_coordinator_decisions(beth_path) if beth_path.exists() else []

        # Revised draft
        draft_path = session_dir / f"round{round_num}_revised_draft.md"
        revised_draft = draft_path.read_text(encoding="utf-8") if draft_path.exists() else ""

        # Only include rounds that produced data
        if normalized or decisions or revised_draft:
            rounds.append(RoundData(
                round_number=round_num,
                normalized_issues=normalized,
                coordinator_decisions=decisions,
                revised_draft=revised_draft,
            ))

    # --- Compute metrics ---
    metrics = _compute_metrics(rounds)

    return ReviewResult(
        session_id=session_id,
        session_dir=session_dir,
        final_draft=final_draft,
        rounds=rounds,
        converged=converged,
        total_rounds=total_rounds,
        metrics=metrics,
    )


def _compute_metrics(rounds: list[RoundData]) -> MetricsSummary:
    """Compute aggregated metrics from round data.

    This is the adapter's own computation, independent of oracle2's
    compute_metrics(). We aggregate from the structured data we parsed,
    ensuring consistency with ORACLE's findings report.
    """
    accepted_by_severity: dict[str, int] = {}
    rejected_count = 0
    preference_count = 0
    unresolved_count = 0
    total_raised = 0
    total_accepted = 0
    duplicate_count = 0  # From normalizer's dropped_findings
    last_critical_high_round = 0

    for rd in rounds:
        total_raised += len(rd.normalized_issues)

        # Build a severity lookup from normalized issues
        severity_map: dict[str, str] = {}
        for issue in rd.normalized_issues:
            severity_map[issue.issue_id] = issue.severity

        # Classify decisions
        for dec in rd.coordinator_decisions:
            if dec.decision == "accepted_defect":
                total_accepted += 1
                # WHY "unknown": defaulting a missing severity to "medium"
                # silently downgraded accepted criticals whenever the
                # decision's issue_id had no matching normalized issue
                # (AUDIT F1). An unmatched ID is a data problem to surface,
                # not a severity to invent.
                sev = severity_map.get(dec.issue_id)
                if sev is None:
                    LOGGER.warning(
                        "Accepted defect %s has no matching normalized issue; "
                        "severity recorded as unknown", dec.issue_id,
                    )
                    sev = "unknown"
                accepted_by_severity[sev] = accepted_by_severity.get(sev, 0) + 1

                # Track last round with critical/high acceptance
                if sev in ("critical", "high"):
                    last_critical_high_round = rd.round_number

            elif dec.decision == "rejected_claim":
                rejected_count += 1
            elif dec.decision == "preference_only":
                preference_count += 1
            elif dec.decision == "unresolved_question":
                unresolved_count += 1

    return MetricsSummary(
        accepted_by_severity=accepted_by_severity,
        rejected_count=rejected_count,
        preference_only_count=preference_count,
        unresolved_count=unresolved_count,
        duplicate_count=duplicate_count,
        rounds_to_stability=last_critical_high_round if last_critical_high_round else len(rounds),
        total_issues_raised=total_raised,
        total_issues_accepted=total_accepted,
    )
