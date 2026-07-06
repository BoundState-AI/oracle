#!/usr/bin/env python3
"""
Module: dude.core
Purpose: Deterministic engines — safety floor, fingerprint/gate, state
         machine, conduct accrual, trigger adjustment, action scoring,
         loop messaging.

Everything in this package is deterministic code. Anything that is a
model inference lives behind the pass protocols in dude.pipeline and is
labeled as inference (spec v0.2; review revision 16 — no determinism
costumes).

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
