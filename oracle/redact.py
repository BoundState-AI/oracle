"""
Module: oracle.redact
Purpose: Strip API-key-shaped substrings from text before it is persisted
         to round files, session logs, or error artifacts.

WHY this exists: raw provider error bodies and exception strings are
persisted for debuggability (round JSON `raw` fields, per-session server
logs). The SDKs usually sanitize keys from their own messages, but the
httpx layer and arbitrary response bodies make no such promise — one
echo of an Authorization header into a persisted artifact is a credential
leak (AUDIT C5). Redaction is applied at the persistence choke points,
not at capture, so live debugging output is unaffected.

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import os
import re

# WHY these patterns: the shapes of the configured vendors' keys —
# sk-… (OpenAI, and Anthropic's sk-ant-…), AIza… (Google), xai-… (xAI),
# AKIA/ASIA… (AWS access keys — Bedrock is used by sentinel/tocr in this
# repo), ya29.… (Google OAuth), bare JWTs (eyJ….eyJ…. — auth error bodies
# echo them in JSON fields without a "Bearer" prefix) — plus any Bearer
# token. WHY the 16+ tail: real keys are long; requiring 16 key-characters
# avoids mangling prose like "sk-learn" or short IDs. False positives only
# cost a little debuggability; false negatives leak credentials — so
# patterns err toward matching.
_KEY_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{16,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"ya29\.[A-Za-z0-9_\-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{4,}\.eyJ[A-Za-z0-9_\-]{4,}(?:\.[A-Za-z0-9_\-]+)?"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.]{16,}"),
)

REDACTED = "[REDACTED-KEY]"

# WHY value-based redaction on top of shapes: regexes only catch key
# formats we anticipated. The process knows the exact values of every
# secret it actually holds — replacing literal occurrences of those
# values closes the shape-drift gap (new vendor formats, ORACLE_API_KEY's
# arbitrary shape, AWS 40-char secrets) for the credentials that matter
# most: ours. Names are matched by suffix/exact-name so future *_API_KEY
# vars are covered without editing this list.
_SECRET_ENV_SUFFIXES = ("_API_KEY", "_SECRET_ACCESS_KEY", "_SESSION_TOKEN")
_SECRET_ENV_NAMES = frozenset({"ORACLE_API_KEY"})
# WHY 8: values shorter than this are more likely flags/IDs than secrets,
# and replacing them would shred ordinary prose (e.g. a key set to "test").
_MIN_SECRET_LENGTH = 8


def _env_secret_values() -> list[str]:
    """Collect the literal values of secret-bearing env vars, longest first.

    Read per call, not at import: keys can be set or rotated after module
    import (tests, long-lived servers). Longest-first ordering prevents a
    shorter secret that is a substring of a longer one from splitting it.
    """
    values = []
    for key, value in os.environ.items():
        if not value or len(value) < _MIN_SECRET_LENGTH:
            continue
        if key.endswith(_SECRET_ENV_SUFFIXES) or key in _SECRET_ENV_NAMES:
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


def redact_secrets(text: str) -> str:
    """Replace key-shaped substrings and known secret values with a marker."""
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(REDACTED, text)
    for value in _env_secret_values():
        if value in text:
            text = text.replace(value, REDACTED)
    return text
