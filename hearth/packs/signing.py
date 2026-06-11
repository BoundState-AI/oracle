#!/usr/bin/env python3
"""
Module: hearth.packs.signing
Purpose: Micro-rule signing — Phase-1 STUB signer (spec v0.3 §2.2, §12 P1-C).

Every micro-rule carries a signature over its canonical JSON so that
accidental edits and transport corruption are detectable. THIS IS NOT
CRYPTOGRAPHIC AUTHENTICITY: the P1 signer is an HMAC with a public,
hard-coded key (signatures are prefixed "STUB1:" so nobody mistakes them
for real provenance). Real key management and per-reviewer signatures are
a pre-production requirement tracked in BUILD_NOTES.md.

Run `python -m hearth.packs.signing <pack.json>` to (re)sign every rule in
a pack file after editing it.

Safety Critical: False
Financially Critical: True — a silently altered rule would alter findings;
  never-suppress-error pattern applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import hashlib
import hmac
import json
import logging
import sys
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("hearth.packs.signing")

# Public on purpose: P1 signatures detect drift, not forgery (see header).
_STUB_KEY = b"hearth-p1-stub-signing-key--public--not-a-secret"
SIGNATURE_PREFIX = "STUB1:"


def canonical_rule_bytes(rule: dict[str, Any]) -> bytes:
    """Canonical byte form of a rule, signature field excluded."""
    unsigned = {k: v for k, v in rule.items() if k != "signature"}
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")


def sign_rule_dict(rule: dict[str, Any]) -> str:
    """Produce the P1 stub signature for a rule dict."""
    digest = hmac.new(_STUB_KEY, canonical_rule_bytes(rule), hashlib.sha256)
    return SIGNATURE_PREFIX + digest.hexdigest()


def verify_rule_dict(rule: dict[str, Any]) -> bool:
    """True iff the rule's signature matches its canonical content."""
    expected = sign_rule_dict(rule)
    actual = rule.get("signature", "")
    return hmac.compare_digest(expected, actual)


def resign_pack_file(path: Path) -> int:
    """Dev utility: re-sign every rule in a pack JSON in place."""
    content = json.loads(path.read_text(encoding="utf-8"))
    rules = content.get("rules", [])
    for rule in rules:
        rule["signature"] = sign_rule_dict(rule)
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", "utf-8")
    LOGGER.info("re-signed %d rules in %s", len(rules), path)
    return len(rules)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("usage: python -m hearth.packs.signing <pack.json>\n")
        return 64
    count = resign_pack_file(Path(args[0]))
    sys.stdout.write(f"re-signed {count} rules (STUB signer — drift detection only)\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - dev utility entry
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
