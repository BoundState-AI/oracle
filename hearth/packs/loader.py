#!/usr/bin/env python3
"""
Module: hearth.packs.loader
Purpose: Load + validate JurisdictionPack files (spec v0.3 §2.2, §12 P1-C).

A pack enters the scrubber only if ALL of this holds: the JSON parses, the
§2.2 schema validates (Pydantic, extra=forbid), every rule's stub
signature verifies, and every executable detection/finding spec compiles.
Any defect raises PackError — the CLI converts that to a refusal with exit
code 2. A defective pack must never silently shrink to "fewer findings".

Safety Critical: False
Financially Critical: True — never-suppress-error pattern applies.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from hearth.core.scrubber.matcher import (
    CLAUSE_REGEX,
    MatchSpecError,
    compile_detection,
    detection_type,
    validate_finding_spec,
)
from hearth.data import JurisdictionPack
from hearth.packs.signing import (
    ED25519_PREFIX,
    SigningError,
    registry_for_pack,
    verify_rule_signature,
)

LOGGER = logging.getLogger("hearth.packs.loader")

BUILTIN_JURISDICTION_DIR = Path(__file__).resolve().parent / "jurisdiction"


class PackError(Exception):
    """Pack unusable; caller must fail CLOSED."""


@dataclass(frozen=True)
class LoadedPack:
    """A validated pack plus the provenance the audit trail needs (§11)."""

    pack: JurisdictionPack
    path: Path
    sha256: str


def resolve_pack_path(ref: str, packs_dir: Path | None = None) -> Path:
    """Resolve a pack name (e.g. 'CO-Larimer') or direct .json path."""
    direct = Path(ref)
    if direct.suffix == ".json":
        if direct.is_file():
            return direct
        raise PackError(f"pack file not found: {direct}")
    base = packs_dir if packs_dir is not None else BUILTIN_JURISDICTION_DIR
    candidate = base / ref / "pack.json"
    if candidate.is_file():
        return candidate
    available = sorted(d.parent.name for d in base.glob("*/pack.json"))
    listing = ", ".join(available) if available else "none installed"
    raise PackError(
        f"unknown jurisdiction pack '{ref}' (searched {base}; available: {listing})"
    )


def load_pack(ref: str, packs_dir: Path | None = None) -> LoadedPack:
    """Load, schema-validate, signature-check and spec-check a pack."""
    path = resolve_pack_path(ref, packs_dir)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PackError(f"cannot read pack file {path}: {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackError(f"pack file {path} is not valid JSON: {exc}") from exc

    try:
        pack = JurisdictionPack.model_validate(data)
    except ValidationError as exc:
        raise PackError(f"pack file {path} fails the §2.2 schema: {exc}") from exc

    _verify_signatures(data, path)
    _validate_executable_specs(pack)

    LOGGER.info("loaded pack %s (%d rules) from %s", pack.pack_id, len(pack.rules), path)
    return LoadedPack(pack=pack, path=path, sha256=hashlib.sha256(raw).hexdigest())


def _verify_signatures(data: dict, path: Path) -> None:
    """Every rule's signature must match its canonical content (§2.2), and
    review status must be backed by a real reviewer signature (§13 P2-B)."""
    try:
        registry = registry_for_pack(path)
    except SigningError as exc:
        raise PackError(str(exc)) from exc

    bad: list[str] = []
    stub_reviewed: list[str] = []
    for index, rule in enumerate(data.get("rules", [])):
        rule_id = rule.get("rule_id", f"#{index}")
        if not verify_rule_signature(rule, registry):
            bad.append(rule_id)
        elif rule.get("status") == "reviewed" and not str(
            rule.get("signature", "")
        ).startswith(ED25519_PREFIX):
            # A stub signature is drift detection, not attestation: it can
            # never carry a human review claim.
            stub_reviewed.append(rule_id)
    if bad:
        raise PackError(
            f"pack {path} has rules failing signature verification: {bad} — "
            "content was altered after signing (re-sign deliberate edits with "
            "python -m hearth.packs.signing)"
        )
    if stub_reviewed:
        raise PackError(
            f"pack {path} has 'reviewed' rules without a reviewer (Ed25519) "
            f"signature: {stub_reviewed} — a stub signature cannot attest review"
        )


def _validate_executable_specs(pack: JurisdictionPack) -> None:
    """Compile every clause_regex rule now so a bad spec can never surface
    mid-scrub as a mysteriously missing finding."""
    known_rule_ids = {rule.rule_id for rule in pack.rules}
    for rule in pack.rules:
        if detection_type(rule) != CLAUSE_REGEX:
            continue
        try:
            compile_detection(rule)
            spec = validate_finding_spec(rule)
        except MatchSpecError as exc:
            raise PackError(f"pack {pack.pack_id}: {exc}") from exc
        # §13 P2-A: a declared exposure dependency must point at a rule
        # that actually exists in this pack — a dangling reference would
        # quietly resurrect the implicit-capture trap.
        exposure = spec.get("exposure") or {}
        origin = exposure.get("capture_from_rule")
        if origin is not None and origin not in known_rule_ids:
            raise PackError(
                f"pack {pack.pack_id}: rule {rule.rule_id} exposure depends on "
                f"capture_from_rule {origin!r}, which is not in this pack"
            )
