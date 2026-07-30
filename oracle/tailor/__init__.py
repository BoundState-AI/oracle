"""Lightweight interactive helper for tailoring a standard, one shall at a time.

Reads a rule pack, serves requirements in order, proposes a disposition with
its reasoning, and records what the human decides. The advisor proposes; the
engineer disposes.

BoundState AI 2026
Classification: BoundState Proprietary
"""

from oracle.tailor.session import Decision, Requirement, TailorError, TailorSession

__all__ = ["Decision", "Requirement", "TailorError", "TailorSession"]
