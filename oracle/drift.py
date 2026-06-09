"""
Module: oracle.drift
Purpose: Detect reviewer position drift — critical/high findings abandoned
         between rounds even though the draft text they indicted is unchanged.

This is the sycophancy signature (AUDIT A5): a reviewer converging toward
the majority/coordinator position without new evidence. Detection is
heuristic and REPORT-ONLY — it never gates convergence, because a drift
heuristic that blocks runs would manufacture false dissent.

BoundState AI 2026
Classification: BoundState Proprietary

__safety_critical__: bool = True — informs interpretation of consensus output
"""

from __future__ import annotations

__safety_critical__: bool = True

import re
from dataclasses import dataclass
from typing import Any

# WHY only critical/high: round-3+ reviewer prompts explicitly instruct
# dropping low-risk nitpicks, so a low/medium finding disappearing is
# instructed behavior, not drift. A critical/high finding disappearing
# while the text it indicted is untouched is the signal worth surfacing.
DRIFT_SEVERITIES = ("critical", "high")

# WHY 0.5 Jaccard: titles get reworded between rounds ("X is undefined" ->
# "X is still undefined"). Half the content tokens shared is loose enough
# to track a rephrased finding, tight enough not to merge unrelated ones.
# A false MATCH only hides drift (quieter report); it never creates a
# false accusation — so the threshold errs loose deliberately.
TITLE_MATCH_JACCARD = 0.5

# WHY 12: evidence snippets shorter than this ("the spec", "Section 2")
# appear in almost any draft, which would flag every dropped finding as
# "cited text unchanged". Below this length the evidence check abstains.
MIN_EVIDENCE_CHARS = 12


@dataclass(frozen=True)
class DriftEvent:
    """One abandoned finding with no corresponding draft change."""
    oracle: str
    round_from: int
    round_to: int
    title: str
    severity: str
    reason: str


def _title_tokens(title: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", title.lower()))


def _still_raised(title: str, later_findings: list[dict]) -> bool:
    """True if a finding with this title (or a rephrasing) appears later."""
    tokens = _title_tokens(title)
    if not tokens:
        # Untitled findings cannot be tracked across rounds — never flag.
        return True
    for finding in later_findings:
        other = _title_tokens(str(finding.get("title", "")))
        if not other:
            continue
        if tokens == other:
            return True
        if len(tokens & other) / len(tokens | other) >= TITLE_MATCH_JACCARD:
            return True
    return False


def _drafts_reviewed(session: Any) -> list[str]:
    """The draft text each round's reviewers actually saw, by round index."""
    drafts: list[str] = []
    current = session.original_draft
    for review_round in session.rounds:
        drafts.append(current)
        if review_round.revised_draft:
            current = review_round.revised_draft
    return drafts


def detect_drift(session: Any) -> list[DriftEvent]:
    """Find critical/high findings abandoned without a matching draft change.

    For each consecutive pair of VALID rounds, per oracle: a finding from
    the earlier round with no (re)match in the later round is drift when
      - the draft was not revised at all between the rounds, or
      - the draft was revised but the exact text the finding cited is
        still present in the later draft (the complaint's target survived).
    If the draft changed where the finding pointed, the finding is
    presumed addressed and NOT flagged.
    """
    drafts = _drafts_reviewed(session)
    valid = [(i, r) for i, r in enumerate(session.rounds) if r.valid]

    events: list[DriftEvent] = []
    for (idx_a, round_a), (idx_b, round_b) in zip(valid, valid[1:]):
        draft_a, draft_b = drafts[idx_a], drafts[idx_b]
        for oracle, output_a in round_a.reviewer_outputs.items():
            output_b = round_b.reviewer_outputs.get(oracle, {})
            findings_a = output_a.get("findings", []) if isinstance(output_a, dict) else []
            findings_b = [
                f for f in (output_b.get("findings", []) if isinstance(output_b, dict) else [])
                if isinstance(f, dict)
            ]
            for finding in findings_a:
                if not isinstance(finding, dict):
                    continue
                severity = str(finding.get("severity", "")).lower()
                if severity not in DRIFT_SEVERITIES:
                    continue
                title = str(finding.get("title", ""))
                if _still_raised(title, findings_b):
                    continue

                evidence = str(finding.get("evidence", "")).strip()
                if draft_a == draft_b:
                    reason = (
                        "finding dropped although the draft was not revised "
                        "between rounds"
                    )
                elif len(evidence) >= MIN_EVIDENCE_CHARS and evidence in draft_b:
                    reason = (
                        "finding dropped although the text it cited is "
                        "unchanged in the revised draft"
                    )
                else:
                    continue  # draft changed where cited — presumed addressed

                events.append(DriftEvent(
                    oracle=oracle,
                    round_from=round_a.round_number,
                    round_to=round_b.round_number,
                    title=title or "(untitled)",
                    severity=severity,
                    reason=reason,
                ))
    return events
