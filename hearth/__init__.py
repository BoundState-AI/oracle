#!/usr/bin/env python3
"""
Module: hearth
Purpose: HEARTH — Buyer-Side Real Estate Intelligence Platform.

Every organ of this platform exists to surface a default, cite the evidence
against it, and present a buyer-favorable alternative for the buyer's
licensed human to draft and execute. HEARTH is an analytics and
document-intelligence tool used by a principal on their own behalf; it is
not a brokerage and performs no act defined as brokerage under
C.R.S. 12-10-201.

Phase 1 (spec v0.3 §12) ships exactly four deliverables:
  P1-A  package skeleton + Pydantic data models (§2)
  P1-B  DocScrubber CLI, findings-only, fails CLOSED (§3.3, §12)
  P1-C  CO-Larimer JurisdictionPack skeleton, provisional (§2.2, §12)
  P1-D  BuyerPack boundary-test scaffold (§1.1, §6, §12)

Safety Critical: False
Financially Critical: False (package marker; see per-module headers)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = False

__version__ = "0.1.0"
