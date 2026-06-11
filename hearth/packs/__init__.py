#!/usr/bin/env python3
"""
Module: hearth.packs
Purpose: Pack storage: BuyerPack instances + JurisdictionPack library (spec v0.3 §1).

jurisdiction/ holds the versioned, signed micro-rule library;
buyer/ holds local-first BuyerPack instances (never synced in
plaintext, §2.1).

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
