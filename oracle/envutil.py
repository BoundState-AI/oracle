"""
Module: oracle.envutil
Purpose: Shared environment-variable parsing helpers.

WHY a dedicated module: read_env_int is needed by both the chat surface
(chat_engine, server) and the extraction pipeline (rulepack adapters).
Importing chat_engine from the extraction pipeline would be a
wrong-direction dependency, so the helper lives in this leaf module.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import os

LOGGER = logging.getLogger("oracle.envutil")


def read_env_int(name: str, default: int) -> int:
    """Read a positive integer env override, logging and defaulting on garbage.

    WHY log-and-default: a malformed deployment value (e.g. "5;", "unlimited")
    must not crash a compliance answer path, but silently ignoring it would
    hide a misconfiguration — so the rejection is logged in full.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        LOGGER.warning("Ignoring non-integer %s=%r; using default %d", name, raw, default)
        return default
    if value <= 0:
        LOGGER.warning("Ignoring non-positive %s=%r; using default %d", name, raw, default)
        return default
    return value
