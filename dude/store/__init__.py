#!/usr/bin/env python3
"""
Module: dude.store
Purpose: Append-only persistence for DUDE (spec v0.2 I11).

Safety Critical: False
Psychologically Critical: False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = False

from dude.store.jsonl import CaseBundle, CaseStore, StoreError

__all__ = ["CaseBundle", "CaseStore", "StoreError"]
