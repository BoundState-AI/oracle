#!/usr/bin/env python3
"""
Module: hearth.packs.buyer
Purpose: BuyerPack instances — local-first, E2EE sync only (spec v0.3 §2.1).

No store implementation in Phase 1. Whatever lands here must keep
BuyerPack inside the trust boundary (§1.1): local plaintext or
zero-knowledge E2EE blob, nothing in between.

Safety Critical: False
Financially Critical: False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False
