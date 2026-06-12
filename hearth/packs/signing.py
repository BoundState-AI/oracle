#!/usr/bin/env python3
"""
Module: hearth.packs.signing
Purpose: Micro-rule signing — Ed25519 per-reviewer signatures plus the P1
         stub signer (spec v0.3 §2.2; §13 P2-B).

Two signature schemes coexist over identical canonical rule bytes:

  ED25519:<key_id>:<sig_hex>  Real authenticity. Public keys live in a
                              committed registry (keys.json next to the
                              pack or at the packs root); private keys
                              never enter the repository.
  STUB1:<hmac_hex>            Drift detection only (HMAC with a public,
                              hard-coded key). Valid ONLY for provisional
                              rules — the loader refuses any rule marked
                              status "reviewed" that carries a stub
                              signature, because a stub cannot attest
                              human review.

CLI:
  python -m hearth.packs.signing keygen --owner "Dr. J. Wilde"
  python -m hearth.packs.signing sign <pack.json> --key-hex <priv> --key-id <id>
  python -m hearth.packs.signing resign-stub <pack.json>
  python -m hearth.packs.signing <pack.json>            # alias: resign-stub

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

import argparse
import hashlib
import hmac
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("hearth.packs.signing")

# Public on purpose: STUB1 signatures detect drift, not forgery (see header).
_STUB_KEY = b"hearth-p1-stub-signing-key--public--not-a-secret"
SIGNATURE_PREFIX = "STUB1:"
ED25519_PREFIX = "ED25519:"

KEY_REGISTRY_FILENAME = "keys.json"


class SigningError(Exception):
    """Key material or registry unusable; caller must fail CLOSED."""


@dataclass(frozen=True)
class KeyRecord:
    """One committed reviewer public key."""

    key_id: str
    owner: str
    public_key_hex: str
    created: str


# ---------------------------------------------------------------------------
# Canonical bytes (shared by both schemes)
# ---------------------------------------------------------------------------


def canonical_rule_bytes(rule: dict[str, Any]) -> bytes:
    """Canonical byte form of a rule, signature field excluded."""
    unsigned = {k: v for k, v in rule.items() if k != "signature"}
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# STUB1 scheme (P1 — drift detection only)
# ---------------------------------------------------------------------------


def sign_rule_dict(rule: dict[str, Any]) -> str:
    """Produce the stub signature for a rule dict."""
    digest = hmac.new(_STUB_KEY, canonical_rule_bytes(rule), hashlib.sha256)
    return SIGNATURE_PREFIX + digest.hexdigest()


def verify_rule_dict(rule: dict[str, Any]) -> bool:
    """True iff the rule carries a valid STUB1 signature."""
    expected = sign_rule_dict(rule)
    return hmac.compare_digest(expected, rule.get("signature", ""))


# ---------------------------------------------------------------------------
# ED25519 scheme (P2 — real per-reviewer authenticity)
# ---------------------------------------------------------------------------


def generate_keypair() -> tuple[str, str]:
    """Return (private_key_hex, public_key_hex) for a new reviewer key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private = Ed25519PrivateKey.generate()
    private_hex = private.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    ).hex()
    public_hex = private.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    ).hex()
    return private_hex, public_hex


def sign_rule_dict_ed25519(
    rule: dict[str, Any], private_key_hex: str, key_id: str
) -> str:
    """Sign a rule with a reviewer's private key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    except ValueError as exc:
        raise SigningError(f"invalid Ed25519 private key material: {exc}") from exc
    signature = private.sign(canonical_rule_bytes(rule))
    return f"{ED25519_PREFIX}{key_id}:{signature.hex()}"


def verify_rule_signature(
    rule: dict[str, Any], registry: dict[str, KeyRecord]
) -> bool:
    """Verify a rule signature under whichever scheme it declares.

    Unknown schemes, unknown key_ids, malformed material, and bad
    signatures are all the same answer: False. The caller fails closed.
    """
    signature = rule.get("signature", "")
    if not isinstance(signature, str):
        return False  # fail closed on malformed material, never crash
    if signature.startswith(SIGNATURE_PREFIX):
        return verify_rule_dict(rule)
    if signature.startswith(ED25519_PREFIX):
        return _verify_ed25519(rule, signature, registry)
    return False


def _verify_ed25519(
    rule: dict[str, Any], signature: str, registry: dict[str, KeyRecord]
) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    parts = signature[len(ED25519_PREFIX):].split(":", 1)
    if len(parts) != 2:
        return False
    key_id, sig_hex = parts
    record = registry.get(key_id)
    if record is None:
        LOGGER.warning("rule signature cites unknown key_id %r", key_id)
        return False
    try:
        public = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(record.public_key_hex)
        )
        public.verify(bytes.fromhex(sig_hex), canonical_rule_bytes(rule))
        return True
    except (ValueError, InvalidSignature):
        return False


# ---------------------------------------------------------------------------
# Key registry
# ---------------------------------------------------------------------------


def load_key_registry(path: Path) -> dict[str, KeyRecord]:
    """Load a keys.json registry; SigningError on malformed content."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = [KeyRecord(**entry) for entry in data["keys"]]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SigningError(f"key registry {path} unusable: {exc}") from exc
    registry = {record.key_id: record for record in records}
    if len(registry) != len(records):
        raise SigningError(f"key registry {path} contains duplicate key_ids")
    return registry


def registry_for_pack(pack_path: Path) -> dict[str, KeyRecord]:
    """The registry governing a pack lives at the PACKS-LIBRARY ROOT
    (pack_path's grandparent: <packs_root>/<name>/pack.json), which the
    operator controls — NEVER inside the pack's own directory. A pack that
    ships its own keys.json could otherwise self-attest 'reviewed' with a
    key it minted (forged human review).

    No registry is a valid state (stub-only packs); reviewed rules then
    fail verification, which is exactly the fail-closed intent.
    """
    inside_pack = pack_path.parent / KEY_REGISTRY_FILENAME
    if inside_pack.is_file():
        LOGGER.warning(
            "ignoring %s: key registries inside a pack directory are "
            "untrusted (self-attestation risk)",
            inside_pack,
        )
    trusted = pack_path.parent.parent / KEY_REGISTRY_FILENAME
    if trusted.is_file():
        return load_key_registry(trusted)
    return {}


# ---------------------------------------------------------------------------
# Pack-file operations + CLI
# ---------------------------------------------------------------------------


def resign_pack_file(path: Path) -> int:
    """Dev utility: re-sign every rule in a pack JSON with the STUB scheme."""
    content = json.loads(path.read_text(encoding="utf-8"))
    rules = content.get("rules", [])
    for rule in rules:
        rule["signature"] = sign_rule_dict(rule)
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", "utf-8")
    LOGGER.info("re-signed %d rules in %s (STUB scheme)", len(rules), path)
    return len(rules)


def sign_pack_file_ed25519(
    path: Path,
    private_key_hex: str,
    key_id: str,
    rule_ids: list[str] | None = None,
) -> int:
    """Sign rules (all, or the listed rule_ids) with a reviewer key."""
    content = json.loads(path.read_text(encoding="utf-8"))
    signed = 0
    for rule in content.get("rules", []):
        if rule_ids is not None and rule.get("rule_id") not in rule_ids:
            continue
        rule["signature"] = sign_rule_dict_ed25519(rule, private_key_hex, key_id)
        signed += 1
    if rule_ids is not None and signed != len(rule_ids):
        raise SigningError(
            f"asked to sign {len(rule_ids)} rules but matched {signed} in {path}"
        )
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", "utf-8")
    LOGGER.info("signed %d rules in %s with key %s", signed, path, key_id)
    return signed


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # Back-compat: `python -m hearth.packs.signing <pack.json>` re-stubs.
    if len(args) == 1 and args[0].endswith(".json"):
        args = ["resign-stub", args[0]]

    parser = argparse.ArgumentParser(prog="hearth.packs.signing")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="generate a reviewer keypair")
    keygen.add_argument("--owner", required=True)

    resign = sub.add_parser("resign-stub", help="re-sign all rules (STUB scheme)")
    resign.add_argument("pack", type=Path)

    sign = sub.add_parser("sign", help="sign rules with a reviewer key")
    sign.add_argument("pack", type=Path)
    sign.add_argument("--key-hex", required=True, help="Ed25519 private key (hex)")
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--rules", help="comma-separated rule_ids (default: all)")

    options = parser.parse_args(args)
    if options.command == "keygen":
        private_hex, public_hex = generate_keypair()
        key_id = f"{options.owner.split()[0].lower()}-{public_hex[:8]}"
        sys.stdout.write(
            json.dumps(
                {
                    "key_id": key_id,
                    "owner": options.owner,
                    "public_key_hex": public_hex,
                    "private_key_hex_DO_NOT_COMMIT": private_hex,
                },
                indent=2,
            )
            + "\n"
        )
        return 0
    if options.command == "resign-stub":
        count = resign_pack_file(options.pack)
        sys.stdout.write(f"re-signed {count} rules (STUB scheme — drift detection only)\n")
        return 0
    rule_ids = options.rules.split(",") if options.rules else None
    count = sign_pack_file_ed25519(options.pack, options.key_hex, options.key_id, rule_ids)
    sys.stdout.write(f"signed {count} rules with key {options.key_id}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - dev utility entry
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
