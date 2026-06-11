#!/usr/bin/env python3
"""
Module: hearth.__main__
Purpose: `python -m hearth` entry point delegating to the CLI.

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

import sys

from hearth.cli import main

if __name__ == "__main__":
    sys.exit(main())
