#!/usr/bin/env python3
"""
Module: hearth.api.app
Purpose: Single-tenant FastAPI surface — health endpoint only in Phase 1
         (spec v0.3 §12 constraints).

The API grows organs in later phases; in P1 it exists so the deployment
shape (local-first, single-tenant, §1.1) is real from day one. No endpoint
here may ever accept or return BuyerPack material in plaintext across the
trust boundary.

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

import logging

from fastapi import FastAPI

from hearth import __version__

LOGGER = logging.getLogger("hearth.api.app")

app = FastAPI(title="HEARTH", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for the single-tenant instance."""
    return {"status": "ok", "service": "hearth", "version": __version__, "phase": "P1"}
