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

import re

# WHY these patterns: the shapes of the four configured vendors' keys —
# sk-… (OpenAI, and Anthropic's sk-ant-…), AIza… (Google), xai-… (xAI) —
# plus any Bearer token. WHY the 16+ tail: real keys are long; requiring
# 16 key-characters avoids mangling prose like "sk-learn" or short IDs.
# False positives only cost a little debuggability; false negatives leak
# credentials — so patterns err toward matching.
_KEY_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{16,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.]{16,}"),
)

REDACTED = "[REDACTED-KEY]"


def redact_secrets(text: str) -> str:
    """Replace key-shaped substrings with a fixed marker."""
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text
