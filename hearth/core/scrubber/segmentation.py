#!/usr/bin/env python3
"""
Module: hearth.core.scrubber.segmentation
Purpose: Deterministic clause segmentation for the DocScrubber (spec v0.3 §3.3).

Standard-form contracts (CREC family) number their clauses; segmentation
keys on those section numbers so every finding can cite a clause_ref a
human can locate ("§7.3"). Documents without numbered sections fall back
to blank-line paragraphs ("¶2"). A non-empty document that somehow yields
zero clauses raises SegmentationError — fail closed, never silence.

Safety Critical: False
Financially Critical: True — a clause the segmenter drops is a clause the
  matcher never sees; never-suppress-error pattern applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
import re
from dataclasses import dataclass

LOGGER = logging.getLogger("hearth.core.scrubber.segmentation")

# A section heading line: "7. COMPENSATION ..." or "7.3 IF SELLER ...".
# Lookahead requires an uppercase/quote start so amounts mid-sentence
# ("3% of...") and dates never open a phantom clause.
_SECTION_START = re.compile(r"^\s*(?P<num>\d{1,2}(?:\.\d{1,2})*)\.?\s+(?=[\"'(A-Z])")


class SegmentationError(Exception):
    """Text could not be segmented; caller must fail CLOSED."""


@dataclass(frozen=True)
class Clause:
    """One contiguous clause with a human-locatable reference."""

    index: int
    ref: str
    text: str


def segment_clauses(text: str) -> list[Clause]:
    """Split document text into clauses. Raises SegmentationError on zero."""
    if not text.strip():
        raise SegmentationError("empty text reached the segmenter")

    clauses = _segment_numbered(text)
    if not clauses:
        clauses = _segment_paragraphs(text)
    if not clauses:
        raise SegmentationError("document yielded zero clauses")
    LOGGER.debug("segmented %d clauses", len(clauses))
    return clauses


def _segment_numbered(text: str) -> list[Clause]:
    """Segment on numbered section headings; [] if the document has none."""
    sections: list[tuple[str, list[str]]] = []
    preamble: list[str] = []
    current: list[str] | None = None

    for line in text.splitlines():
        started = _SECTION_START.match(line)
        if started:
            current = [line.strip()]
            sections.append((f"§{started.group('num')}", current))
        elif current is not None:
            current.append(line.strip())
        elif line.strip():
            preamble.append(line.strip())

    if not sections:
        return []

    clauses = []
    if preamble:
        clauses.append(Clause(index=0, ref="preamble", text=" ".join(preamble)))
    for ref, lines in sections:
        body = " ".join(part for part in lines if part)
        clauses.append(Clause(index=len(clauses), ref=ref, text=body))
    return clauses


def _segment_paragraphs(text: str) -> list[Clause]:
    """Fallback: blank-line-separated paragraphs, refs ¶1..¶n."""
    clauses = []
    for block in re.split(r"\n\s*\n", text):
        body = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if body:
            clauses.append(Clause(index=len(clauses), ref=f"¶{len(clauses) + 1}", text=body))
    return clauses
