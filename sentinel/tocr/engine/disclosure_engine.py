#!/usr/bin/env python3
"""
Module: Disclosure Audit Engine
Purpose: Pass 2 — Check every material change against the Summary of Changes.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Spec: BS-SPEC-TOCR-001-REV1, Section 4.2
"""

__safety_critical__: bool = True
__version__ = "1.0.0"

import re
from difflib import SequenceMatcher

from sentinel.tocr.engine.shared import ENGLISH_STOPWORDS
from sentinel.tocr.models.diff import FieldChange, StructuralDiff
from sentinel.tocr.models.enums import ChangeClassification, ConfidenceLevel
from sentinel.tocr.models.report import DisclosureResult


# Minimum similarity threshold for considering a change disclosed.
# 0.55 requires genuine semantic overlap, not just shared common English.
# Previous 0.35 caused systematic false-positive disclosures, suppressing
# TOCR-001 (CRITICAL) for changes that were NOT actually disclosed.
_SIMILARITY_THRESHOLD = 0.55

# Keywords that indicate the Summary of Changes acknowledges a field
_FIELD_KEYWORDS = {
    ChangeClassification.SCOPE_LANGUAGE: [
        "scope", "task", "work", "develop", "design", "support", "capability",
        "software", "integration", "AI", "added", "new", "expanded",
    ],
    ChangeClassification.FUNDING: [
        "fund", "cost", "budget", "wbs", "charge", "obligat", "amount", "dollar",
        "increas", "decreas", "reallocat",
    ],
    ChangeClassification.SKILLS: [
        "skill", "labor", "categor", "personnel", "qualif", "expertise",
    ],
    ChangeClassification.DELIVERABLE: [
        "deliverable", "milestone", "report", "submittal", "artifact", "due date",
    ],
    ChangeClassification.TEAM: [
        "team", "participat", "subcontract", "partner", "vendor",
    ],
    ChangeClassification.QUALITY_PLAN: [
        "quality", "qms", "inspection", "assurance", "plan",
    ],
}


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _extract_key_phrases(change: FieldChange) -> list[str]:
    """Extract key phrases from a change for matching against summary."""
    phrases = []
    # Use the proposed text (or prior for deletions)
    text = change.proposed_text or change.prior_text
    if not text:
        return phrases

    # Split into sentences and take meaningful ones
    sentences = re.split(r"[.;]\s+", text)
    for sentence in sentences:
        cleaned = sentence.strip()
        if len(cleaned) > 10:
            phrases.append(cleaned)

    # Also extract the field path as a reference
    field_parts = change.field_path.replace(".", " ").replace("_", " ")
    phrases.append(field_parts)

    return phrases


class DisclosureEngine:
    """
    Pass 2: Disclosure Audit Engine.

    For every material change detected in Pass 1 (excluding formatting
    and administrative), checks whether the change is listed in the
    Summary of Changes.
    """

    def __init__(self, similarity_threshold: float = _SIMILARITY_THRESHOLD):
        self.similarity_threshold = similarity_threshold

    def run(
        self,
        diff: StructuralDiff,
        summary_of_changes: str,
    ) -> list[DisclosureResult]:
        """
        Audit all material changes against the Summary of Changes.

        Args:
            diff: Structural diff from Pass 1.
            summary_of_changes: The Summary of Changes text from the proposed revision.

        Returns:
            List of DisclosureResult for each material change.
        """
        results: list[DisclosureResult] = []
        normalized_summary = _normalize(summary_of_changes)

        for change in diff.field_changes:
            # Skip formatting and administrative changes
            if not change.is_material:
                continue

            result = self._check_disclosure(change, summary_of_changes, normalized_summary)
            results.append(result)

        return results

    def _check_disclosure(
        self,
        change: FieldChange,
        raw_summary: str,
        normalized_summary: str,
    ) -> DisclosureResult:
        """Check if a single change is disclosed in the Summary of Changes."""
        if not normalized_summary:
            return DisclosureResult(
                field_path=change.field_path,
                change_summary=self._summarize_change(change),
                disclosed=False,
                matching_summary_text="",
                confidence=ConfidenceLevel.DETERMINISTIC,
            )

        # Strategy 1: Check if field-specific keywords appear in summary
        keyword_match = self._keyword_match(change, normalized_summary)

        # Strategy 2: Check text similarity between change content and summary
        similarity_match, best_match_text = self._similarity_match(change, raw_summary)

        # Strategy 3: Check if sub-task ID is mentioned for sub-task changes
        subtask_match = self._subtask_id_match(change, normalized_summary)

        disclosed = keyword_match or similarity_match or subtask_match

        # Why confidence ranking: subtask ID match is deterministic (exact string),
        # similarity match is high (SequenceMatcher threshold), keyword match is medium
        # (heuristic word overlap).
        confidence = (
            ConfidenceLevel.DETERMINISTIC if subtask_match
            else ConfidenceLevel.HIGH if similarity_match
            else ConfidenceLevel.MEDIUM
        )

        return DisclosureResult(
            field_path=change.field_path,
            change_summary=self._summarize_change(change),
            disclosed=disclosed,
            matching_summary_text=best_match_text if disclosed else "",
            confidence=confidence,
        )

    def _keyword_match(self, change: FieldChange, normalized_summary: str) -> bool:
        """Check if classification-specific keywords appear in summary near relevant context.

        Conservative: requires strong evidence of disclosure.  A loose check
        here suppresses TOCR-001 (CRITICAL), so false-positive "disclosed"
        marks are far worse than false negatives.
        """
        keywords = _FIELD_KEYWORDS.get(change.classification, [])
        if not keywords:
            return False

        # Need at least 3 relevant keywords in the summary (was 2 — too loose)
        matches = sum(1 for kw in keywords if kw.lower() in normalized_summary)
        if matches < 3:
            return False

        # Also check that meaningful content from the change appears
        change_text = _normalize(change.proposed_text or change.prior_text)
        if not change_text:
            return False

        # English-only stopwords (not contract boilerplate) — we want to detect
        # whether a change summary actually describes THIS change's content words.
        # See engine/shared.py for the two-tier stopword rationale.
        change_words = set(change_text.split()) - ENGLISH_STOPWORDS
        summary_words = set(normalized_summary.split()) - ENGLISH_STOPWORDS
        overlap = change_words & summary_words

        # Require 3+ non-stopword content words AND they must comprise at
        # least 15% of the change's meaningful words to ensure real overlap
        if len(overlap) < 3:
            return False
        if change_words and len(overlap) / len(change_words) < 0.15:
            return False
        return True

    def _similarity_match(
        self, change: FieldChange, raw_summary: str
    ) -> tuple[bool, str]:
        """Check text similarity between change and summary sentences."""
        phrases = _extract_key_phrases(change)
        if not phrases:
            return False, ""

        summary_sentences = re.split(r"[.\n;]\s*", raw_summary)
        best_ratio = 0.0
        best_text = ""

        for phrase in phrases:
            normalized_phrase = _normalize(phrase)
            for sentence in summary_sentences:
                normalized_sentence = _normalize(sentence)
                if not normalized_sentence:
                    continue
                ratio = SequenceMatcher(None, normalized_phrase, normalized_sentence).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_text = sentence.strip()

        return best_ratio >= self.similarity_threshold, best_text

    def _subtask_id_match(self, change: FieldChange, normalized_summary: str) -> bool:
        """Check if the sub-task ID from the field path appears in summary."""
        # Extract sub-task ID from field path like "sub_tasks.ST-001.description"
        match = re.search(r"sub_tasks\.([^.]+)", change.field_path)
        if not match:
            return False
        st_id = match.group(1).lower()
        return st_id in normalized_summary

    def _summarize_change(self, change: FieldChange) -> str:
        """Create a human-readable summary of the change."""
        parts = [f"{change.change_type.value} in {change.field_path}"]
        if change.classification != ChangeClassification.ADMINISTRATIVE:
            parts.append(f"({change.classification.value})")
        if change.word_count_delta:
            parts.append(f"[{change.word_count_delta:+d} words]")
        return " ".join(parts)
