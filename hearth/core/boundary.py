#!/usr/bin/env python3
"""
Module: hearth.core.boundary
Purpose: The testable definition of BuyerPack exfiltration (spec v0.3
         §1.1, §6, §12 P1-D).

"BuyerPack never crosses the trust boundary in plaintext" is enforced, not
suggested. This module turns a BuyerPack into a set of canary strings and
checks arbitrary text for them. The P1-D boundary tests use it against log
capture, the mocked network layer, and every file a run writes; later
phases reuse find_leaks() as the §3.4 disclosure leak check that generated
external text must pass before display.

Discrimination note: schema vocabulary (enum values like "conventional")
appears in any pack and cannot prove provenance, so it is excluded; the
canary test fixture therefore uses globally unique sentinel values for
every identifying field (tests/fixtures/buyerpack_canary.json, fixture #2).

Safety Critical: False
Financially Critical: True — a leak this module misses is a leak shipped.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import logging
from typing import Any

from hearth.data import BuyerPack

LOGGER = logging.getLogger("hearth.core.boundary")

# Enum values defined by the §2.1 schema itself — present in every pack,
# useless for proving that a specific household's data moved.
SCHEMA_VOCAB = frozenset(
    {"conventional", "cash", "hybrid", "standard", "tight",
     "waive_with_evidence", "reveal_nothing"}
)

# Strings shorter than this are too low-entropy to discriminate
# (e.g. "Weld"); identifying fixture values must be ≥ this length.
MIN_CANARY_LENGTH = 6

# Integers below this (commute minutes, flexibility days) collide with
# ordinary numbers in any report; dollar amounts clear it easily.
MIN_CANARY_INT = 10_000


def collect_canaries(pack: BuyerPack) -> frozenset[str]:
    """Every string/number in the pack that could prove a leak."""
    found: set[str] = set()
    _walk(pack.to_json_dict(), found)
    return frozenset(found)


def find_leaks(
    text: str, canaries: frozenset[str], allow: frozenset[str] = frozenset()
) -> list[str]:
    """Canaries present in `text` (case-insensitive), minus `allow`.

    `allow` exists for values the caller proves arrived from a non-BuyerPack
    source in the same run; using it to silence a real leak is a review
    failure, so every use must carry a WHY comment at the call site.
    """
    haystack = text.lower()
    leaked = sorted(
        canary
        for canary in canaries - allow
        if canary.lower() in haystack
    )
    if leaked:
        LOGGER.error("BuyerPack canary values found in output: %s", leaked)
    return leaked


def _walk(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)
    elif isinstance(node, bool):
        return  # bool before int: True/False discriminate nothing
    elif isinstance(node, str):
        if len(node) >= MIN_CANARY_LENGTH and node.lower() not in SCHEMA_VOCAB:
            found.add(node)
    elif isinstance(node, int):
        if abs(node) >= MIN_CANARY_INT:
            found.add(str(node))
            found.add(f"{node:,}")  # catch "$7,654,321" renderings too
