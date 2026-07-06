#!/usr/bin/env python3
"""
Module: dude
Purpose: DUDE — evidence-aware decision support for humans under uncertainty.

Phase-1 production core (spec v0.2). Three sibling systems now cohabit this
repo: ORACLE (adversarial document review), HEARTH (buyer-side real-estate
intelligence), and DUDE (decision support under uncertainty).

Constitution (spec v0.1 §3, machinery per v0.2 §1): observation is not
inference; the safety floor runs before every gate; engine copy describes
evidence state, never the user's psychology; no hidden priors; the system
holds no favored model.

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
