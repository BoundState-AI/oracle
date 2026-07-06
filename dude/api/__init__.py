#!/usr/bin/env python3
"""
Module: dude.api
Purpose: FastAPI surface for DUDE — REST case operations plus the
         two-way voice websocket.

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

from dude.api.app import create_app, create_router

__all__ = ["create_app", "create_router"]
