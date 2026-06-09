#!/usr/bin/env python3
"""
Module: ORACLE — Orchestrated Review And Compliance Liaison Engine
Purpose: Unified CLI for multi-oracle adversarial review with extensible
         rule packs. Wraps oracle2 as the review engine and delegates to
         existing extraction pipelines (shall_extractor, build_gpcm_rulepack,
         build_far_rulepack) for pack generation.

Version: 1.3.0 (oracle-reviewed)

Architecture:
  oracle.py (this file)
    ├── oracle2.py         — review engine (UNCHANGED, black-box)
    ├── oracle2_adapter.py — parses oracle2 output into ReviewResult contract
    ├── pack_validator.py  — JSON Schema validation for all pack types
    ├── shall_extractor.py — obligation extraction (UNCHANGED)
    ├── build_gpcm_rulepack.py — GPCM pipeline (UNCHANGED)
    ├── build_far_rulepack.py  — FAR pipeline (UNCHANGED)
    └── Pack Library ($ORACLE_PACK_DIR or ~/.oracle/packs/)

Commands:
  review          Review a document against selected rule packs
  generate-pack   Generate a rule pack from a regulatory PDF
  list-packs      List all packs in the library
  add-pack        Import an existing rule pack JSON into the library
  remove-pack     Remove a pack from the library
  show-pack       Display pack contents and stats
  promote-pack    Mark a draft pack as reviewed/promoted

Usage:
  oracle generate-pack NASA-STD-6016C.pdf
  oracle generate-pack regs/DFARS_252.pdf --name dfars_252
  oracle review proposal.md --packs nasa_std_6016c dfars_252
  oracle review proposal.md --packs far --pack-parts far=15,19,52
  oracle promote-pack nasa_std_6016c --reviewer "Dr. Joseph Wilde"
  oracle list-packs

Safety:
  __safety_critical__ = True  — outputs drive compliance review decisions.
  The system SHALL NOT infer new regulatory interpretations. All outputs
  are draft artifacts pending responsible human review.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

LOGGER = logging.getLogger("oracle")

DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

BUILTIN_PACK_SPECS: tuple[dict[str, str], ...] = (
    {
        "filename": "far_rulepack_enriched.json",
        "name": "FAR",
        "description": "Bundled FAR starter pack",
    },
    {
        "filename": "nfs_rulepack.json",
        "name": "NFS",
        "description": "Bundled NASA FAR Supplement starter pack",
    },
    {
        "filename": "essca_j21_rulepack.json",
        "name": "ESSCA J-21",
        "description": "Bundled ESSCA task order content requirements pack",
    },
    {
        "filename": "nasa_std_6030_rulepack.json",
        "name": "NASA-STD-6030",
        "description": "Bundled NASA additive manufacturing requirements pack",
    },
)

# ---------------------------------------------------------------------------
# Pack Library Location Resolution
# Precedence: --pack-dir CLI flag > ORACLE_PACK_DIR env var > ~/.oracle/packs/
# ---------------------------------------------------------------------------

def _resolve_pack_dir(cli_override: str | None = None) -> Path:
    """Resolve the pack library directory.

    Precedence:
      1. --pack-dir CLI flag (per-command override)
      2. ORACLE_PACK_DIR environment variable
      3. Default: ~/.oracle/packs/

    The directory is created if it doesn't exist.
    """
    if cli_override:
        pack_dir = Path(cli_override)
    elif os.environ.get("ORACLE_PACK_DIR"):
        pack_dir = Path(os.environ["ORACLE_PACK_DIR"])
    else:
        pack_dir = Path.home() / ".oracle" / "packs"

    pack_dir.mkdir(parents=True, exist_ok=True)
    _bootstrap_builtin_packs(pack_dir)
    return pack_dir


def _builtin_pack_dir() -> Path:
    """Return the repository-shipped builtin pack directory."""
    return Path(__file__).resolve().parent / "builtin_packs"


def _bootstrap_builtin_packs(pack_dir: Path) -> None:
    """Seed bundled starter packs into a new library and add missing builtins."""
    if os.environ.get("ORACLE_DISABLE_BOOTSTRAP_PACKS", "").lower() in {"1", "true", "yes"}:
        return

    builtin_dir = _builtin_pack_dir()
    if not builtin_dir.exists():
        return

    manifest_exists = _manifest_path(pack_dir).exists()
    existing_pack_files = [
        p for p in pack_dir.glob("*.json") if p.name != "manifest.json"
    ]
    if not manifest_exists and existing_pack_files:
        return

    manifest = _load_manifest(pack_dir) if manifest_exists else {"packs": {}}

    for spec in BUILTIN_PACK_SPECS:
        slug = _slugify(spec["name"])
        if slug in manifest.get("packs", {}):
            continue
        src = builtin_dir / spec["filename"]
        if not src.exists():
            LOGGER.warning("Builtin pack missing: %s", src)
            continue
        try:
            register_pack(
                src,
                pack_dir,
                name=spec["name"],
                description=spec["description"],
                overwrite=True,
            )
        except Exception as exc:
            LOGGER.warning("Failed to bootstrap builtin pack %s: %s", src.name, exc)


# ---------------------------------------------------------------------------
# Model Context-Window Table (Section 10.2)
# Used by token budget calculation to determine effective context budget.
# Updated when models change. Override with ORACLE_MAX_CONTEXT_TOKENS.
# ---------------------------------------------------------------------------

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4-8": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "gpt-5.4": 128_000,
    "gpt-5.4-mini": 128_000,
    "grok-4.20": 131_072,
    "grok-4": 131_072,
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
}


# ---------------------------------------------------------------------------
# Pack Library Operations
# ---------------------------------------------------------------------------

def _manifest_path(pack_dir: Path) -> Path:
    """Return the manifest.json path for the given pack directory."""
    return pack_dir / "manifest.json"


def _load_manifest(pack_dir: Path) -> dict:
    """Load the pack library manifest, creating it if missing."""
    mp = _manifest_path(pack_dir)
    if not mp.exists():
        manifest = {
            "schema_version": "oracle_packs/v1",
            "description": "ORACLE Rule Pack Library — BoundState AI",
            "packs": {},
        }
        mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Corrupt manifest — attempt rebuild from pack files (Section 13.5)
        LOGGER.warning("manifest.json is corrupt — attempting rebuild from pack files")
        return _rebuild_manifest(pack_dir)


def _save_manifest(manifest: dict, pack_dir: Path) -> None:
    """Write the manifest to disk."""
    mp = _manifest_path(pack_dir)
    mp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _rebuild_manifest(pack_dir: Path) -> dict:
    """Rebuild manifest from oracle_metadata in pack files.

    Called when manifest.json is corrupt (Section 13.5 Error Recovery).
    Backs up the corrupt file, scans pack directory, validates each pack,
    and reconstructs manifest entries from oracle_metadata blocks.
    """
    mp = _manifest_path(pack_dir)

    # Back up corrupt manifest
    if mp.exists():
        backup = mp.with_suffix(f".corrupt.{int(time.time())}")
        shutil.copy2(mp, backup)
        LOGGER.info(f"Backed up corrupt manifest to {backup}")

    manifest = {
        "schema_version": "oracle_packs/v1",
        "description": "ORACLE Rule Pack Library — BoundState AI (REBUILT)",
        "packs": {},
    }

    # Scan pack files and rebuild from oracle_metadata
    for pack_file in sorted(pack_dir.glob("*.json")):
        if pack_file.name == "manifest.json":
            continue
        try:
            pack_data = json.loads(pack_file.read_text(encoding="utf-8"))
            meta = pack_data.get("oracle_metadata", {})
            slug = meta.get("slug", pack_file.stem)

            # Compute content hash from pack file
            content_hash = _compute_content_hash(pack_file)

            manifest["packs"][slug] = {
                "name": meta.get("name", slug),
                "slug": slug,
                "file": pack_file.name,
                "schema": _detect_pack_schema(pack_data),
                "standard_id": pack_data.get("standard_id", ""),
                "description": meta.get("description", ""),
                "rule_count": _count_rules(pack_data),
                "version": pack_data.get("version", "1.0.0"),
                "status": meta.get("status", "draft"),
                "extraction_status": pack_data.get("extraction_status", "complete"),
                "content_hash": content_hash,
                "added_at": meta.get("added_at", ""),
                "promoted_at": meta.get("promoted_at"),
                "promoted_by": meta.get("promoted_by"),
                "source_document": pack_data.get("source_document", ""),
                "source_document_hash": meta.get("source_document_hash"),
            }
            LOGGER.info(f"  Rebuilt entry: {slug} ({_count_rules(pack_data)} rules)")
        except (json.JSONDecodeError, OSError) as e:
            LOGGER.warning(f"  Skipping invalid pack file {pack_file.name}: {e}")

    _save_manifest(manifest, pack_dir)
    LOGGER.info(f"Manifest rebuilt with {len(manifest['packs'])} pack(s)")
    return manifest


def _slugify(name: str) -> str:
    """Convert a name to a filesystem-safe slug (lowercase, underscores)."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "unnamed_pack"


def _detect_pack_schema(pack_data: dict) -> str:
    """Detect which schema a rule pack uses from its schema_version field.

    Falls back to field heuristics if schema_version is missing.
    """
    sv = pack_data.get("schema_version", "")
    if "gpcm" in sv:
        return "gpcm"
    if "far" in sv:
        return "far"
    if "generic" in sv:
        return "generic"
    # Heuristic fallback
    if pack_data.get("requirements"):
        return "gpcm"
    if pack_data.get("part_index"):
        return "far"
    if pack_data.get("rules"):
        return "generic"
    return "unknown"


def _count_rules(pack_data: dict) -> int:
    """Count the number of rules/requirements in a pack."""
    schema = _detect_pack_schema(pack_data)
    if schema == "gpcm":
        return len(pack_data.get("requirements", []))
    elif schema == "far":
        return pack_data.get("total_binding_requirements", 0)
    elif schema == "generic":
        return len(pack_data.get("rules", []))
    return 0


# _compute_content_hash: reads entire file into memory for small pack JSON files.
# _compute_file_hash (below): streams in 64 KB chunks for large on-disk files (PDFs).
def _compute_content_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    h = hashlib.sha256(file_path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file (e.g., source PDF)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _resolve_pack_name(pack_name: str, manifest: dict) -> str:
    """Resolve a pack name with fuzzy matching.

    If exact match found, returns it. If the name is a substring of exactly
    one slug, resolves to that. If ambiguous, raises ValueError.
    """
    packs = manifest.get("packs", {})

    # Exact match
    if pack_name in packs:
        return pack_name

    # Fuzzy: substring match
    matches = [k for k in packs if pack_name.lower() in k.lower()]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise ValueError(
            f"Ambiguous pack name '{pack_name}'. Matches: {', '.join(sorted(matches))}"
        )
    else:
        available = ", ".join(sorted(packs.keys())) or "(none)"
        raise ValueError(f"Pack '{pack_name}' not found. Available: {available}")


def register_pack(
    pack_path: Path,
    pack_dir: Path,
    name: str | None = None,
    description: str | None = None,
    allow_partial: bool = False,
    overwrite: bool = False,
) -> str:
    """Register a rule pack JSON file in the library.

    Validates against JSON Schema, copies to pack_dir, updates manifest.
    All packs are registered with status='draft' (Section 5.5).

    Args:
        pack_path: Path to the rule pack JSON to register.
        pack_dir: The pack library directory.
        name: Override pack name. Auto-detected if None.
        description: Override description.
        allow_partial: Allow registration of packs with extraction_status='partial'.
        overwrite: Allow overwriting an existing pack with the same slug.

    Returns:
        The registered pack slug.

    Raises:
        ValueError: On validation failure, partial extraction without flag, or
                    existing pack without overwrite flag.
    """
    from oracle.pack_validator import (
        normalize_oracle_metadata,
        normalize_pack_structure,
        validate_pack,
    )

    pack_data = json.loads(pack_path.read_text(encoding="utf-8"))

    # Derive slug
    if not name:
        name = (
            pack_data.get("standard_id")
            or pack_data.get("rule_pack_id")
            or pack_path.stem
        )
    slug = _slugify(name)

    # Normalize oracle_metadata (adds defaults if missing)
    normalize_oracle_metadata(pack_data, slug=slug)
    normalize_pack_structure(pack_data)

    # Validate against JSON Schema
    errors = validate_pack(pack_data)
    if errors:
        error_msg = "\n  ".join(errors[:10])
        raise ValueError(
            f"Pack validation failed ({len(errors)} error(s)):\n  {error_msg}"
        )

    # Completeness check (Section 5.5)
    if pack_data.get("extraction_status") == "partial" and not allow_partial:
        failed = pack_data.get("failed_page_ranges", [])
        raise ValueError(
            f"Pack has partial extraction (failed pages: {failed}). "
            f"Use --allow-partial to register anyway."
        )

    # Overwrite protection (Section 13.4)
    manifest = _load_manifest(pack_dir)
    if slug in manifest.get("packs", {}) and not overwrite:
        raise ValueError(
            f"Pack '{slug}' already exists. Use --overwrite to replace."
        )

    # Copy pack file to library
    dest = pack_dir / f"{slug}.json"
    dest.write_text(
        json.dumps(pack_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Compute content hash
    content_hash = _compute_content_hash(dest)

    # Ensure source_document_hash is populated for all pack types.
    # FAR/GPCM generators don't set this — compute it here if the
    # source PDF is accessible and the hash is missing.
    meta = pack_data.get("oracle_metadata", {})
    if not meta.get("source_document_hash"):
        source_doc = pack_data.get("source_document", "")
        if source_doc:
            source_path = Path(source_doc)
            if source_path.exists() and source_path.is_file():
                meta["source_document_hash"] = _compute_file_hash(source_path)
                # Write back to the pack file so it's persisted
                pack_data["oracle_metadata"] = meta
                dest.write_text(
                    json.dumps(pack_data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                content_hash = _compute_content_hash(dest)  # Recompute after update
                LOGGER.info(f"Computed source document hash for '{slug}'")

    # Update manifest
    manifest["packs"][slug] = {
        "name": meta.get("name", name),
        "slug": slug,
        "file": f"{slug}.json",
        "schema": _detect_pack_schema(pack_data),
        "standard_id": pack_data.get("standard_id", ""),
        "description": description or meta.get("description", ""),
        "rule_count": _count_rules(pack_data),
        "version": pack_data.get("version", "1.0.0"),
        "status": meta.get("status", "draft"),
        "extraction_status": pack_data.get("extraction_status", "complete"),
        "failed_page_ranges": pack_data.get("failed_page_ranges", []),
        "content_hash": content_hash,
        "added_at": meta.get("added_at", datetime.now(timezone.utc).isoformat()),
        "promoted_at": meta.get("promoted_at"),
        "promoted_by": meta.get("promoted_by"),
        "source_document": pack_data.get("source_document", str(pack_path)),
        "source_document_hash": meta.get("source_document_hash"),
    }
    _save_manifest(manifest, pack_dir)

    LOGGER.info(f"Registered pack '{slug}' ({_count_rules(pack_data)} rules, status=draft)")
    return slug


def load_pack(pack_name: str, pack_dir: Path, verify: bool = True) -> tuple[dict, str]:
    """Load a rule pack by name from the library.

    Returns (pack_data, resolved_slug).
    Supports fuzzy name matching (Section 6.3).

    WHY verify at load time: packs were previously validated only at
    generate/import time (AUDIT B1). A pack file edited or corrupted on
    disk after registration — including a promoted one — would feed the
    review's compliance context unchecked. Both checks fail closed:
      - the file's content hash must match the manifest entry recorded
        at registration/promotion time (tamper and corruption detection;
        legacy manifest entries without a hash skip this check)
      - the pack must still validate against its JSON schema
    """
    from oracle.pack_validator import validate_pack

    manifest = _load_manifest(pack_dir)
    resolved = _resolve_pack_name(pack_name, manifest)
    entry = manifest["packs"][resolved]

    pack_path = pack_dir / entry["file"]
    if not pack_path.exists():
        raise FileNotFoundError(f"Pack file missing: {pack_path}")

    if verify:
        expected_hash = entry.get("content_hash", "")
        if expected_hash:
            actual_hash = _compute_content_hash(pack_path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Pack '{resolved}' has been modified on disk since it was "
                    f"registered (content hash mismatch). Re-register it with "
                    f"add-pack --overwrite (and re-promote if needed) before "
                    f"using it for review."
                )

    pack_data = json.loads(pack_path.read_text(encoding="utf-8"))

    if verify:
        errors = validate_pack(pack_data)
        if errors:
            preview = "; ".join(errors[:5])
            raise ValueError(
                f"Pack '{resolved}' failed schema validation at load time "
                f"({len(errors)} error(s)): {preview}"
            )

    return pack_data, resolved


def remove_pack(pack_name: str, pack_dir: Path) -> bool:
    """Remove a pack from the library (manifest + file)."""
    manifest = _load_manifest(pack_dir)
    try:
        resolved = _resolve_pack_name(pack_name, manifest)
    except ValueError:
        return False

    entry = manifest["packs"].pop(resolved, None)
    if not entry:
        return False

    pack_path = pack_dir / entry["file"]
    if pack_path.exists():
        pack_path.unlink()

    _save_manifest(manifest, pack_dir)
    LOGGER.info(f"Removed pack '{resolved}'")
    return True


def promote_pack(
    pack_name: str,
    pack_dir: Path,
    reviewer: str,
    notes: str | None = None,
    allow_partial: bool = False,
    override_hash_mismatch: bool = False,
    auto_confirm: bool = False,
) -> None:
    """Promote a draft pack to 'promoted' status.

    Enforces promotion prerequisites (Section 6.2):
      1. Pack summary display
      2. Extraction completeness gate
      3. Source hash verification gate
      4. Reviewer identity (required)
      5. Attestation notes
      6. Interactive confirmation

    Args:
        pack_name: Pack slug or fuzzy name.
        pack_dir: The pack library directory.
        reviewer: Who reviewed and approved (--reviewer flag, required).
        notes: Optional attestation notes.
        allow_partial: Allow promoting partial extraction packs.
        override_hash_mismatch: Allow promoting despite source hash mismatch.
        auto_confirm: Skip interactive y/N prompt (for --non-interactive --yes).

    Raises:
        ValueError: On failed gates or missing prerequisites.
    """
    manifest = _load_manifest(pack_dir)
    resolved = _resolve_pack_name(pack_name, manifest)
    entry = manifest["packs"][resolved]

    # Load the actual pack file
    pack_path = pack_dir / entry["file"]
    pack_data = json.loads(pack_path.read_text(encoding="utf-8"))
    meta = pack_data.get("oracle_metadata", {})

    # Already promoted?
    if meta.get("status") == "promoted":
        LOGGER.warning(f"Pack '{resolved}' is already promoted (by {meta.get('promoted_by')})")
        return

    # --- Gate 1: Summary Display ---
    print(f"\n{'='*60}")
    print(f"Pack Promotion: {resolved}")
    print(f"{'='*60}")
    print(f"  Standard:     {pack_data.get('standard_id', 'N/A')}")
    print(f"  Rules:        {_count_rules(pack_data)}")
    print(f"  Extraction:   {pack_data.get('extraction_status', 'complete')}")
    print(f"  Schema:       {pack_data.get('schema_version', 'unknown')}")

    chunk_failures = pack_data.get("chunk_failures", [])
    if chunk_failures:
        print(f"  Chunk fails:  {len(chunk_failures)} chunks failed extraction")
        for cf in chunk_failures[:5]:
            print(f"    pages {cf.get('page_start')}-{cf.get('page_end')}: {cf.get('final_error', '?')}")

    source_hash = meta.get("source_document_hash")
    if source_hash:
        print(f"  Source hash:  {source_hash[:20]}...")
    print(f"  Reviewer:     {reviewer}")
    print()

    # --- Gate 2: Extraction Completeness ---
    if pack_data.get("extraction_status") == "partial":
        if not allow_partial:
            raise ValueError(
                f"Cannot promote pack with partial extraction "
                f"({len(chunk_failures)} chunks failed). "
                f"Use --allow-partial-promotion to proceed."
            )
        LOGGER.warning("Promoting pack with partial extraction (--allow-partial-promotion)")

    # --- Gate 3: Source Hash Verification ---
    promotion_notes_parts: list[str] = []
    source_doc = pack_data.get("source_document", "")
    if source_hash and source_doc:
        source_path = Path(source_doc)
        if source_path.exists():
            current_hash = _compute_file_hash(source_path)
            if current_hash != source_hash:
                if not override_hash_mismatch:
                    raise ValueError(
                        f"Source document hash mismatch. The source PDF has been "
                        f"modified since extraction.\n"
                        f"  Expected: {source_hash}\n"
                        f"  Current:  {current_hash}\n"
                        f"Use --override-hash-mismatch to promote anyway."
                    )
                LOGGER.warning("Source hash mismatch overridden (--override-hash-mismatch)")
                promotion_notes_parts.append(
                    f"Hash mismatch overridden: expected {source_hash[:20]}, "
                    f"got {current_hash[:20]}"
                )
        else:
            LOGGER.warning(f"Source PDF not accessible at {source_doc} — skipping hash check")

    if allow_partial and pack_data.get("extraction_status") == "partial":
        promotion_notes_parts.append(
            f"Partial extraction promoted ({len(chunk_failures)} chunks failed)"
        )

    # Build final promotion notes
    if notes:
        promotion_notes_parts.append(notes)
    if not promotion_notes_parts:
        promotion_notes_parts.append("Reviewed and approved.")
    final_notes = "; ".join(promotion_notes_parts)

    # --- Gate 6: Interactive Confirmation ---
    # Fail closed in non-TTY sessions — never silently auto-promote
    if not auto_confirm:
        if not sys.stdin.isatty():
            raise ValueError(
                "promote-pack requires interactive confirmation. "
                "Use --yes with --non-interactive to auto-confirm."
            )
        response = input(f"Promote '{resolved}' to production status? [y/N]: ").strip().lower()
        if response != "y":
            print("Promotion cancelled.")
            return

    # --- Apply Promotion ---
    now = datetime.now(timezone.utc).isoformat()
    meta["status"] = "promoted"
    meta["promoted_at"] = now
    meta["promoted_by"] = reviewer
    meta["promotion_notes"] = final_notes

    # Write updated pack file
    pack_data["oracle_metadata"] = meta
    pack_path.write_text(
        json.dumps(pack_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Update manifest
    entry["status"] = "promoted"
    entry["promoted_at"] = now
    entry["promoted_by"] = reviewer
    entry["content_hash"] = _compute_content_hash(pack_path)
    _save_manifest(manifest, pack_dir)

    print(f"\nPack '{resolved}' promoted by {reviewer}")
    LOGGER.info(f"Promoted pack '{resolved}' by {reviewer}: {final_notes}")


# ---------------------------------------------------------------------------
# Document Type Detection (Section 5.1)
# Two-pass strategy with confidence scoring
# ---------------------------------------------------------------------------

def _detect_document_type(
    pdf_path: Path,
    force_type: str | None = None,
    non_interactive: bool = False,
) -> tuple[str, float]:
    """Detect document type with confidence scoring.

    Pass 1: Read first 10 pages, apply pattern matching.
    Pass 2: If confidence < threshold, sample 5 evenly-spaced body pages.

    Returns (doc_type, confidence). Confidence 1.0 for 'generic' (catch-all).

    Args:
        pdf_path: Path to the PDF.
        force_type: If set, skip detection entirely.
        non_interactive: If True, low-confidence is a hard error without --force-type.

    Returns:
        (doc_type, confidence) tuple.
    """
    if force_type:
        LOGGER.info(f"Detection overridden: --force-type {force_type} applied. Recorded in pack metadata.")
        return force_type, 1.0

    try:
        import fitz
    except ImportError:
        LOGGER.warning("PyMuPDF not available — defaulting to generic extraction")
        return "generic", 1.0

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # --- Pass 1: Front matter (first 10 pages) ---
    pass1_pages = min(10, total_pages)
    page_texts: dict[int, str] = {}
    for i in range(pass1_pages):
        page_texts[i] = doc[i].get_text("text")

    # Pattern definitions for 2-pass document type detection (Section 5.3).
    # WHY 3 separate patterns: each identifies a different regulatory document
    # family.  The detection heuristic counts matches per page — whichever
    # pattern dominates determines the extraction route:
    #   tag_pattern → GPCM route (NASA tagged standards with tags like
    #   [MPR N], [FCR N], [NER N], or NASA-STD-6030's [AMR-N])
    #   far_pattern → FAR route (federal acquisition regulations with Part.Section)
    #   cfr_pattern → Generic route (Code of Federal Regulations references)
    # If no pattern dominates, the generic Claude extraction route is used.
    tag_pattern = re.compile(
        r"\[\s*(MPR|FCR|NER|AMR)\s*[-\s]?\s*\d+[a-z]?\s*\]",
        re.IGNORECASE,
    )
    far_pattern = re.compile(r"(?:FAR|DFARS|NFS|GSAM)\s+(?:Part\s+)?\d+\.\d+", re.IGNORECASE)
    cfr_pattern = re.compile(r"(?:\d+\s+CFR|Code of Federal Regulations)", re.IGNORECASE)

    # Count matches per pattern per page
    def _score_pattern(pattern: re.Pattern, texts: dict[int, str]) -> tuple[int, int]:
        """Returns (total_matches, pages_with_matches)."""
        total = 0
        pages_with = 0
        for page_text in texts.values():
            matches = len(pattern.findall(page_text))
            total += matches
            if matches > 0:
                pages_with += 1
        return total, pages_with

    tag_count, tag_pages = _score_pattern(tag_pattern, page_texts)
    far_count, far_pages = _score_pattern(far_pattern, page_texts)
    cfr_count, cfr_pages = _score_pattern(cfr_pattern, page_texts)

    sampled_pages = pass1_pages

    # --- Pass 2: Body sampling if needed ---
    # Check if any route has clear confidence from pass 1
    def _confidence(match_count: int, pages_with: int, total_sampled: int) -> float:
        """Confidence formula from Section 5.1."""
        if match_count == 0:
            return 0.0
        threshold = 3
        raw_score = match_count / threshold
        dist_factor = pages_with / total_sampled if total_sampled > 0 else 0
        return min(1.0, raw_score * (0.5 + 0.5 * dist_factor))

    best_pass1 = max(
        _confidence(tag_count, tag_pages, sampled_pages),
        _confidence(far_count, far_pages, sampled_pages),
        _confidence(cfr_count, cfr_pages, sampled_pages),
    )

    if best_pass1 < 0.7 and total_pages > 10:
        # Sample 5 evenly-spaced pages from the remainder
        step = max(1, (total_pages - 10) // 6)
        sample_indices = list(range(10, total_pages, step))[:5]
        for i in sample_indices:
            if i < total_pages:
                page_texts[i] = doc[i].get_text("text")
        sampled_pages = len(page_texts)

        # Rescore with all sampled pages
        tag_count, tag_pages = _score_pattern(tag_pattern, page_texts)
        far_count, far_pages = _score_pattern(far_pattern, page_texts)
        cfr_count, cfr_pages = _score_pattern(cfr_pattern, page_texts)

    doc.close()

    # --- Compute final scores ---
    tagged_confidence = _confidence(tag_count, tag_pages, sampled_pages)
    sampled_text = "\n".join(page_texts.values())
    if (
        tagged_confidence < 0.7
        and tag_count >= 2
        and tag_pages >= 2
        and re.search(r"NASA[-_ ]STD[-_ ]\d{4}", sampled_text, re.IGNORECASE)
    ):
        # NASA tagged standards can have long front matter and sparse sampled
        # body pages. Multiple pages with bracketed requirement tags are enough
        # to choose the GPCM tagged-standard route over generic extraction.
        tagged_confidence = 0.75

    scores: list[tuple[str, float]] = [
        ("tagged_standard", tagged_confidence),
        ("far_style", _confidence(far_count, far_pages, sampled_pages)),
        ("cfr_style", _confidence(cfr_count, cfr_pages, sampled_pages)),
    ]

    # Sort by confidence desc, then by specificity (tie-break: Section 5.1)
    specificity = {"tagged_standard": 3, "far_style": 2, "cfr_style": 1}
    scores.sort(key=lambda x: (x[1], specificity.get(x[0], 0)), reverse=True)

    best_type, best_conf = scores[0]

    # If no route scores above 0.0, it's generic
    if best_conf == 0.0:
        return "generic", 1.0

    # Low-confidence handling
    if best_conf < 0.7:
        if non_interactive:
            LOGGER.error(
                f"Detection confidence too low ({best_conf:.2f}) for non-interactive mode. "
                f"Use --force-type <type> to override."
            )
            sys.exit(1)

        # Interactive confirmation
        response = input(
            f"Detected '{best_type}' with low confidence ({best_conf:.2f}). "
            f"Proceed? [Y/n/override]: "
        ).strip().lower()
        if response == "n":
            print("Aborted.")
            sys.exit(0)
        elif response == "override":
            override = input("Enter type (tagged_standard|far_style|cfr_style|generic): ").strip()
            if override in ("tagged_standard", "far_style", "cfr_style", "generic"):
                return override, 1.0

    return best_type, best_conf


# ---------------------------------------------------------------------------
# Pack Generation Pipelines (Section 5.2–5.4)
# ---------------------------------------------------------------------------

def _generate_pack_tagged_standard(
    pdf_path: Path,
    output_dir: Path,
    name: str | None,
    use_vision: bool,
    detect_implicit: bool = False,
) -> Path:
    """Route A: Generate pack from a tagged standard via GPCM pipeline.

    Delegates to build_gpcm_rulepack.run_pipeline() which calls
    shall_extractor.extract_pass1() and gpcm_rulepack_adapter.run_adapter().
    """
    from oracle.build_gpcm_rulepack import run_pipeline

    result = run_pipeline(
        pdf_path=pdf_path,
        output_dir=output_dir,
        mandatory_only=True,
        extractor_sonnet=use_vision,
        adapter_sonnet=use_vision,
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        dpi=150,
        extractor_max_pages=0,
        adapter_model=os.environ.get("ORACLE_VISION_MODEL", "claude-sonnet-4-6"),
        adapter_dpi=200,
        detect_implicit=detect_implicit,
    )
    return result["rule_pack"]


def _generate_pack_far_style(
    pdf_path: Path,
    output_dir: Path,
    name: str | None,
    use_vision: bool,
    detect_implicit: bool = False,
) -> Path:
    """Route B: Generate pack from FAR/DFARS-style regulation.

    Uses shall_extractor for extraction, then build_far_rulepack for
    structuring into the tiered Part/Section format.
    """
    from oracle.shall_extractor import extract_pass1, enrich_with_sonnet, detect_implicit_obligations, save_results
    from oracle.build_far_rulepack import build_rulepack

    # Stage 1: Extract shall statements
    LOGGER.info("Stage 1: Extracting shall statements...")
    result = extract_pass1(pdf_path)

    if use_vision:
        LOGGER.info("Stage 1.5: Sonnet Vision enrichment...")
        result = enrich_with_sonnet(
            result, pdf_path,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )

    if detect_implicit:
        LOGGER.info("Stage 1c: Detecting implicit obligations...")
        result = detect_implicit_obligations(
            result, pdf_path,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )

    paths = save_results(result, output_dir)
    LOGGER.info(f"Extracted {result.total_statements} statements → {paths['json']}")

    # Stage 2: Build FAR-style rule pack
    LOGGER.info("Stage 2: Building rule pack...")
    rulepack = build_rulepack(paths["json"], mandatory_only=True)

    out_path = output_dir / f"{_slugify(name or pdf_path.stem)}_rulepack.json"
    out_path.write_text(
        json.dumps(rulepack, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOGGER.info(f"Rule pack: {out_path} ({rulepack['total_binding_requirements']} requirements)")
    return out_path


# Severity taxonomy for generic extraction (Section 4.3)
SEVERITY_TAXONOMY = """\
Assign severity using this closed taxonomy:
- critical: Obligation uses "shall" or "must" with safety, health, or legal consequence language; OR governs system-level controls (quality control authority, safety shutdowns)
- high: Obligation uses "shall" or "must" for operational requirements without explicit consequence language
- medium: Obligation uses "required" or conditional mandatory language ("shall, when applicable")
- low: Prohibition ("shall not") for administrative or procedural matters"""

GENERIC_EXTRACTION_PROMPT = f"""\
Extract all mandatory obligations from these pages.

Find every statement that uses: shall, shall not, must, must not,
is required, are required, is prohibited, may not.

{SEVERITY_TAXONOMY}

Return STRICT JSON only:
{{
  "rules": [
    {{
      "obligation_type": "mandatory|prohibition",
      "obligation_keyword": "shall|must|shall not|must not|required|prohibited",
      "section": "section number if visible",
      "statement_text": "the full obligation statement",
      "subject": "who/what the obligation applies to",
      "requirement": "what must be done/not done",
      "context": "surrounding context if helpful",
      "severity": "critical|high|medium|low",
      "keywords": ["keyword1", "keyword2"],
      "page": page_number
    }}
  ]
}}

Rules:
- Only extract binding obligations (shall/must), not recommendations (should/may).
- Each rule must be atomic: one obligation per entry.
- Preserve exact regulatory language in statement_text.
- Include section numbers when visible.
- Do not invent or extrapolate — extract only what is on the page.
- If no obligations are found on these pages, return {{"rules": []}}.
- Return valid JSON only. No markdown fences, no commentary.\
"""


def _parse_extraction_json(text: str) -> dict | None:
    """Parse JSON from LLM extraction response.

    Handles: markdown fences, leading text, truncated JSON.
    Returns None on parse failure (NOT {"rules": []}), so callers can
    distinguish parse failure from a genuine empty-rules response.
    """
    text = text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # skip opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Find the JSON object
    start = text.find("{")
    if start == -1:
        return None

    # Balanced brace finder
    depth = 0
    in_string = False
    escape_next = False
    end = start
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


IMPLICIT_GENERIC_PROMPT = """\
You already extracted explicit obligations (shall/must/required/prohibited) from these pages.
Now find **implicit obligations** — statements that impose a binding requirement WITHOUT using standard obligation keywords.

Examples of implicit obligations:
- "Reports are due quarterly" (= shall submit reports quarterly)
- "The system operates at 5V" (= shall be designed to operate at 5V)
- "All personnel hold a SECRET clearance" (= shall staff only cleared personnel)
- "Testing follows MIL-STD-810" (= shall test per MIL-STD-810)

Do NOT extract:
- Statements already using shall/must/required/prohibited (already captured)
- Background, definitions, scope descriptions, or recommendations (should/may)

ALREADY EXTRACTED (do not re-extract):
{already_extracted}

Return STRICT JSON only:
{{
  "rules": [
    {{
      "obligation_type": "implicit",
      "obligation_keyword": "(implicit)",
      "section": "section number if visible",
      "statement_text": "the exact text from the document",
      "subject": "who/what must comply",
      "requirement": "rewritten as an explicit obligation",
      "context": "why this is binding",
      "severity": "high|medium|low",
      "confidence": 0.0-1.0,
      "keywords": ["keyword1", "keyword2"],
      "page": page_number
    }}
  ]
}}

Rules:
- Be conservative. Only extract genuinely binding implicit obligations.
- Each obligation must be atomic: one requirement per entry.
- Preserve exact source language in statement_text.
- If no implicit obligations are found, return {{"rules": []}}.
- Return valid JSON only. No markdown fences, no commentary.\
"""


def _detect_implicit_generic(
    pdf_path: Path,
    existing_rules: list[dict],
    use_vision: bool,
    client,
    rule_counter: int,
) -> list[dict]:
    """Run implicit obligation detection for the generic extraction pipeline.

    Returns a list of new rule dicts with obligation_type='implicit'.
    """
    import fitz

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # Build summary of already-extracted rules for the prompt
    already_lines = []
    for r in existing_rules:
        kw = r.get("obligation_keyword", "").upper()
        text = r.get("statement_text", "")[:150]
        already_lines.append(f"  - [{kw}] {text}")
    already_text = "\n".join(already_lines[:200])  # cap to avoid prompt overflow

    CHUNK_SIZE = 5
    implicit_rules: list[dict] = []
    chunk_start = 0

    while chunk_start < total_pages:
        chunk_end = min(chunk_start + CHUNK_SIZE, total_pages)

        content: list[dict] = []
        for page_idx in range(chunk_start, chunk_end):
            page = doc[page_idx]
            if use_vision:
                import base64
                matrix = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64,
                    },
                })
                content.append({
                    "type": "text",
                    "text": f"[Page {page_idx + 1}]",
                })
            else:
                page_text = page.get_text("text")
                content.append({
                    "type": "text",
                    "text": f"--- PAGE {page_idx + 1} ---\n{page_text}",
                })

        content.append({
            "type": "text",
            "text": IMPLICIT_GENERIC_PROMPT.format(already_extracted=already_text),
        })

        try:
            response = client.messages.create(
                model=os.environ.get("ORACLE_VISION_MODEL", "claude-sonnet-4-6"),
                max_tokens=4096,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            )

            if response.content:
                raw_text = response.content[0].text
                parsed = _parse_extraction_json(raw_text)

                if parsed and parsed.get("rules"):
                    for rule in parsed["rules"]:
                        stmt_text = rule.get("statement_text", "").strip()
                        if not stmt_text or len(stmt_text) < 15:
                            continue
                        rule_counter += 1
                        rule["rule_id"] = f"RULE-{rule_counter:04d}"
                        rule["obligation_type"] = "implicit"
                        rule["obligation_keyword"] = "(implicit)"
                        rule.setdefault("page", chunk_start + 1)
                        rule.setdefault("confidence", 0.5)
                        implicit_rules.append(rule)

                    LOGGER.info(
                        f"    Pages {chunk_start+1}–{chunk_end}: "
                        f"{len(parsed['rules'])} implicit obligations"
                    )

        except Exception as e:
            LOGGER.warning(
                f"    Pages {chunk_start+1}–{chunk_end} implicit detection failed: {e}"
            )

        chunk_start = chunk_end

    doc.close()
    return implicit_rules


def _extract_chunk(
    doc,
    chunk_start: int,
    chunk_end: int,
    total_pages: int,
    use_vision: bool,
    client,
) -> tuple[list[dict] | None, str]:
    """Extract obligations from a single PDF chunk via Claude.

    Returns (rules_list, error_string).  On success error_string is empty.
    On failure after all retries, rules_list is None.

    Why bounded retry: LLM responses occasionally return malformed JSON
    or use wrong keys.  Max 2 retries with a repair prompt is enough to
    recover most cases without burning excessive API credits.
    """
    import base64
    import fitz as _fitz

    LOGGER.info(f"  Processing pages {chunk_start + 1}–{chunk_end} of {total_pages}...")

    content: list[dict] = []
    for page_idx in range(chunk_start, chunk_end):
        page = doc[page_idx]
        if use_vision:
            matrix = _fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
            })
            content.append({"type": "text", "text": f"[Page {page_idx + 1}]"})
        else:
            page_text = page.get_text("text")
            content.append({"type": "text", "text": f"--- PAGE {page_idx + 1} ---\n{page_text}"})

    content.append({"type": "text", "text": GENERIC_EXTRACTION_PROMPT})

    max_retries = 2
    last_error = ""

    for attempt in range(1, max_retries + 2):
        try:
            response = client.messages.create(
                model=os.environ.get("ORACLE_VISION_MODEL", "claude-sonnet-4-6"),
                max_tokens=8192,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            )

            if response.content:
                raw_text = response.content[0].text
                parsed = _parse_extraction_json(raw_text)

                if parsed is None:
                    last_error = "JSON parse failure after markdown fence stripping"
                    if attempt <= max_retries:
                        LOGGER.warning(f"    Attempt {attempt}: malformed JSON, retrying with repair prompt...")
                        content.append({
                            "type": "text",
                            "text": (
                                f"Your previous response was malformed:\n{raw_text[:500]}\n\n"
                                "Return ONLY a valid JSON object with a 'rules' array. "
                                "No markdown fences, no commentary."
                            ),
                        })
                    continue

                rules = parsed.get("rules")
                if rules is None:
                    last_error = f"JSON missing 'rules' key, got keys: {list(parsed.keys())}"
                    if attempt <= max_retries:
                        LOGGER.warning(f"    Attempt {attempt}: {last_error}, retrying with repair prompt...")
                        content.append({
                            "type": "text",
                            "text": (
                                f"Your response was valid JSON but used the wrong key. "
                                f"You returned: {json.dumps(list(parsed.keys()))}. "
                                f"Return a JSON object with a 'rules' array. Example: "
                                f'{{"rules": [{{"rule_id": "...", "statement_text": "..."}}]}}'
                            ),
                        })
                    continue

                LOGGER.info(f"    Found {len(rules)} obligations (attempt {attempt})")
                return rules, ""

        except Exception as e:
            last_error = str(e)
            if attempt <= max_retries:
                LOGGER.warning(f"    Attempt {attempt} failed: {e}. Retrying...")
                time.sleep(2 * attempt)

    return None, last_error


def _deduplicate_rules(rules: list[dict]) -> list[dict]:
    """Deduplicate rules using composite key (section + normalized text).

    Why composite key: Section 5.4 specifies that rules with identical text
    but different sections are preserved (same obligation in different contexts).
    Only exact section+text duplicates from chunk overlap regions are removed.
    """
    seen_keys: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for rule in rules:
        key = (
            rule.get("section", "").strip().lower(),
            re.sub(r"\s+", " ", rule.get("statement_text", "").strip().lower()),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(rule)

    dupes_removed = len(rules) - len(deduped)
    if dupes_removed > 0:
        LOGGER.info(f"  Deduplicated: removed {dupes_removed} duplicate rules (overlap regions)")

    # Re-sequence rule IDs after dedup
    for i, rule in enumerate(deduped, 1):
        rule["rule_id"] = f"RULE-{i:04d}"

    return deduped


def _assemble_generic_pack(
    pdf_path: Path,
    deduped_rules: list[dict],
    total_pages: int,
    extracted_pages: list[int],
    chunk_failures: list[dict],
    name: str | None,
    use_vision: bool,
    force_type: str | None,
) -> dict:
    """Build the final generic pack dict from extracted + deduped rules."""
    source_hash = _compute_file_hash(pdf_path)
    standard_id = name or pdf_path.stem
    extraction_status = "partial" if chunk_failures else "complete"

    return {
        "schema_version": "oracle_generic/v1",
        "rule_pack_id": f"generic-{_slugify(standard_id)}",
        "standard_id": standard_id,
        "standard_title": name or pdf_path.stem,
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_document": str(pdf_path),
        "extraction_method": "claude_vision" if use_vision else "claude_text",
        "extraction_status": extraction_status,
        "total_source_pages": total_pages,
        "extracted_pages": sorted(set(extracted_pages)),
        "failed_page_ranges": [
            f"{cf['page_start']}-{cf['page_end']}" for cf in chunk_failures
        ],
        "chunk_failures": chunk_failures,
        "total_rules": len(deduped_rules),
        "oracle_metadata": {
            "name": name or standard_id,
            "slug": _slugify(standard_id),
            "description": f"Auto-extracted from {pdf_path.name}",
            "status": "draft",
            "added_at": datetime.now(timezone.utc).isoformat(),
            "promoted_at": None,
            "promoted_by": None,
            "promotion_notes": None,
            "source_document_hash": source_hash,
            "detection_override": force_type,
        },
        "rules": deduped_rules,
    }


def _generate_pack_generic(
    pdf_path: Path,
    output_dir: Path,
    name: str | None,
    use_vision: bool,
    force_type: str | None = None,
    detect_implicit: bool = False,
) -> Path:
    """Route C: Generate pack from ANY regulatory document using Claude extraction.

    Processes PDF in overlapping chunks of 5 pages with 1-page overlap.
    Uses Sonnet for extraction with bounded retry (max 2) per chunk.
    Failed chunks are recorded in chunk_failures metadata.

    This is the universal fallback — works on cGMP, ISO, OSHA, ITAR,
    any document with normative language.
    """
    LOGGER.info("Generic extraction: Using Claude to extract obligations...")

    try:
        import fitz
    except ImportError:
        raise RuntimeError("PyMuPDF (fitz) required for PDF processing")

    from anthropic import Anthropic
    import httpx

    client = Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=httpx.Timeout(
            float(os.environ.get("ORACLE_TIMEOUT_SECONDS", "600")),
            connect=10.0,
        ),
    )

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    CHUNK_SIZE = 5
    OVERLAP = 1  # 1-page overlap between consecutive chunks (Section 5.4 / 13.3)

    all_rules: list[dict] = []
    rule_counter = 0
    extracted_pages: list[int] = []
    chunk_failures: list[dict] = []

    chunk_start = 0
    while chunk_start < total_pages:
        chunk_end = min(chunk_start + CHUNK_SIZE, total_pages)

        rules, error = _extract_chunk(doc, chunk_start, chunk_end, total_pages, use_vision, client)

        if rules is not None:
            for rule in rules:
                rule_counter += 1
                rule["rule_id"] = f"RULE-{rule_counter:04d}"
                rule.setdefault("page", chunk_start + 1)
            all_rules.extend(rules)
            extracted_pages.extend(range(chunk_start + 1, chunk_end + 1))
        else:
            LOGGER.error(
                f"    Chunk pages {chunk_start+1}–{chunk_end} FAILED: {error}"
            )
            chunk_failures.append({
                "page_start": chunk_start + 1,
                "page_end": chunk_end,
                "retries_used": 2,
                "final_error": error[:500],
                "extraction_mode": "vision" if use_vision else "text",
            })

        chunk_start = chunk_end - OVERLAP if chunk_end < total_pages else chunk_end

    doc.close()

    # Pass 1c: Implicit obligation detection
    if detect_implicit:
        LOGGER.info("Pass 1c: Detecting implicit obligations...")
        implicit_rules = _detect_implicit_generic(
            pdf_path, all_rules, use_vision, client, rule_counter,
        )
        rule_counter += len(implicit_rules)
        all_rules.extend(implicit_rules)
        extracted_pages.extend(
            r.get("page", 0) for r in implicit_rules if r.get("page")
        )
        LOGGER.info(f"  Found {len(implicit_rules)} implicit obligations")

    deduped_rules = _deduplicate_rules(all_rules)

    pack = _assemble_generic_pack(
        pdf_path, deduped_rules, total_pages, extracted_pages,
        chunk_failures, name, use_vision, force_type,
    )

    out_path = output_dir / f"{_slugify(pack['standard_id'])}_rulepack.json"
    out_path.write_text(
        json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOGGER.info(
        f"Generic rule pack: {out_path} ({len(deduped_rules)} rules, "
        f"status={pack['extraction_status']})"
    )
    return out_path


def generate_pack(
    pdf_path: Path,
    name: str | None = None,
    output_dir: Path | None = None,
    pack_dir: Path | None = None,
    use_vision: bool = True,
    force_type: str | None = None,
    register: bool = True,
    allow_partial: bool = False,
    overwrite: bool = False,
    non_interactive: bool = False,
    detect_implicit: bool = False,
) -> str:
    """Generate a rule pack from a regulatory/standards PDF.

    Auto-detects document type with confidence scoring, routes to the
    appropriate extraction pipeline, validates against JSON Schema,
    and registers in the pack library as a draft.

    Returns the pack slug in the library (or file path if --no-register).
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if output_dir is None:
        output_dir = pdf_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if pack_dir is None:
        pack_dir = _resolve_pack_dir()

    # Detect document type with confidence scoring
    doc_type, confidence = _detect_document_type(pdf_path, force_type, non_interactive)
    LOGGER.info(f"Document type: {doc_type} (confidence: {confidence:.2f})")

    # Route to appropriate generator
    if doc_type == "tagged_standard":
        pack_path = _generate_pack_tagged_standard(
            pdf_path, output_dir, name, use_vision,
            detect_implicit=detect_implicit,
        )
    elif doc_type == "far_style":
        pack_path = _generate_pack_far_style(
            pdf_path, output_dir, name, use_vision,
            detect_implicit=detect_implicit,
        )
    else:
        # cfr_style and generic both use the generic pipeline
        pack_path = _generate_pack_generic(
            pdf_path, output_dir, name, use_vision,
            force_type=force_type,
            detect_implicit=detect_implicit,
        )

    # Register in library
    if register:
        pack_name = register_pack(
            pack_path, pack_dir,
            name=name,
            allow_partial=allow_partial,
            overwrite=overwrite,
        )
        return pack_name
    else:
        return str(pack_path)


# ---------------------------------------------------------------------------
# Pack Rendering for Oracle2 (Section 7.2)
# ---------------------------------------------------------------------------

def _render_pack_for_oracle(
    pack_data: dict,
    pack_id: str,
    parts: list[int] | None = None,
) -> str:
    """Render a rule pack as text for oracle2 prompt injection.

    All renderers prepend [pack_id:rule_id] to each rule line, enabling
    downstream citation extraction by the oracle2_adapter.

    Handles all pack schemas: GPCM, FAR, and generic.
    """
    schema = _detect_pack_schema(pack_data)

    if schema == "far":
        # Render FAR pack with explicit [pack_id:rule_id] citation tokens.
        # We can't modify build_far_rulepack.render_for_oracle(), so we
        # render Tier 1 summary via that function and build Tier 2 ourselves
        # with citation IDs prepended to each requirement line.
        from oracle.build_far_rulepack import render_tier1_summary, FAR_PART_TITLES

        lines = [
            f"# {pack_data.get('standard_title', 'FAR')} Compliance Rule Pack",
            f"Pack ID: {pack_id}",
            f"When citing rules from this pack, use format: [{pack_id}:<rule_id>]",
            "",
            render_tier1_summary(pack_data),
            "",
        ]

        if parts:
            lines.append(f"## Detailed Requirements for Parts: {', '.join(str(p) for p in parts)}")
            lines.append("")
            for part_num in parts:
                part_key = str(part_num)
                reqs = pack_data.get("parts", {}).get(part_key, [])
                if not reqs:
                    lines.append(f"# FAR Part {part_num} — No binding requirements found")
                    continue
                title = FAR_PART_TITLES.get(part_num, f"Part {part_num}")
                lines.append(f"# FAR Part {part_num}: {title}")
                lines.append(f"Binding requirements: {len(reqs)}")
                lines.append("")
                for r in reqs:
                    rid = r.get("id", "?")
                    kw = r.get("obligation_keyword", "SHALL").upper()
                    sec = r.get("section", "??")
                    text = r.get("statement_text", "")
                    if len(text) > 500:
                        text = text[:497] + "..."
                    lines.append(f"[{pack_id}:{rid}] [{kw}] §{sec}: {text}")
                lines.append("")
        else:
            lines.append(
                "NOTE: No specific Parts selected. Review document against the "
                "summary index above. Flag any areas where the document fails to "
                "address requirements from relevant Parts."
            )

        return "\n".join(lines)

    elif schema == "gpcm":
        standard_id = pack_data.get("standard_id", "Unknown Standard")
        reqs = pack_data.get("requirements", [])

        lines = [
            f"# {standard_id} Compliance Rule Pack",
            f"Pack ID: {pack_id}",
            f"Total binding requirements: {len(reqs)}",
            f"When citing rules from this pack, use format: [{pack_id}:<id>]",
            "",
        ]
        for r in reqs:
            rid = r.get("id", "?")
            tag = r.get("source_tag", "")
            sec = r.get("section", "")
            text = r.get("shall_text", r.get("statement_text", ""))
            kw = r.get("obligation_keyword", "SHALL").upper()

            if len(text) > 500:
                text = text[:497] + "..."
            tag_str = f"[{tag}] " if tag else ""
            sec_str = f"§{sec} " if sec else ""
            lines.append(f"[{pack_id}:{rid}] {tag_str}{sec_str}[{kw}]: {text}")

        return "\n".join(lines)

    elif schema == "generic":
        standard_id = pack_data.get("standard_id", "Unknown")
        rules = pack_data.get("rules", [])

        lines = [
            f"# {standard_id} Compliance Rule Pack",
            f"Pack ID: {pack_id}",
            f"Total rules: {len(rules)}",
            f"When citing rules from this pack, use format: [{pack_id}:<rule_id>]",
            "",
        ]
        for r in rules:
            rid = r.get("rule_id", "?")
            sec = r.get("section", "")
            text = r.get("statement_text", "")
            kw = r.get("obligation_keyword", "SHALL").upper()
            sev = r.get("severity", "high").upper()

            if len(text) > 500:
                text = text[:497] + "..."
            sec_str = f"§{sec} " if sec else ""
            lines.append(f"[{pack_id}:{rid}] {sec_str}[{kw}] ({sev}): {text}")

        return "\n".join(lines)

    else:
        # Unknown schema — dump as-is with citation header
        return (
            f"# Compliance Rule Pack (unknown schema)\n"
            f"Pack ID: {pack_id}\n\n"
            + json.dumps(pack_data, indent=2)
        )


# ---------------------------------------------------------------------------
# Token Budget (Section 7.2)
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate using the 4-chars-per-token heuristic."""
    # WHY 4: standard GPT tokenizer averages ~4 chars/token for English prose.
    # Conservative for non-English or code.
    return len(text) // 4


def _compute_token_budget(
    document_text: str,
) -> int:
    """Compute the effective compliance context token budget.

    Formula from Section 7.2:
      compliance_budget = min_model_context_window
                         - estimated_document_tokens
                         - system_prompt_reserve (4,000)
                         - response_headroom (8,000)
                         - per_round_overhead (2,000)

    Capped by ORACLE_MAX_CONTEXT_TOKENS (default 80,000).
    """
    SYSTEM_RESERVE = 4_000
    RESPONSE_HEADROOM = 8_000
    ROUND_OVERHEAD = 2_000

    doc_tokens = _estimate_tokens(document_text)

    # Determine minimum context window across configured models
    model_vars = [
        ("ORACLE_BETH_MODEL", "claude-opus-4-8"),
        ("ORACLE_SONNET_MODEL", "claude-sonnet-4-6"),
        ("ORACLE_FRAN_MODEL", "gpt-5.4"),
        ("ORACLE_CODEX_MODEL", "gpt-5.4"),
        ("ORACLE_GROK_MODEL", "grok-4.20"),
        ("ORACLE_GEMINI_MODEL", "gemini-2.5-pro"),
    ]

    max_context_env = os.environ.get("ORACLE_MAX_CONTEXT_TOKENS")
    max_context_cap = int(max_context_env) if max_context_env else 80_000

    min_window = None
    for var_name, default_model in model_vars:
        model_id = os.environ.get(var_name, default_model)
        window = MODEL_CONTEXT_WINDOWS.get(model_id)
        if window is None:
            if max_context_env:
                # Fixed cap mode — skip per-model lookup
                LOGGER.warning(
                    f"Unknown model '{model_id}'. Using ORACLE_MAX_CONTEXT_TOKENS "
                    f"({max_context_cap}) as fixed budget."
                )
                return max(0, max_context_cap - doc_tokens - SYSTEM_RESERVE - RESPONSE_HEADROOM - ROUND_OVERHEAD)
            else:
                LOGGER.error(
                    f"Unknown model '{model_id}'. Context window size is required for "
                    f"token budget calculation. Set ORACLE_MAX_CONTEXT_TOKENS or use a known model ID."
                )
                sys.exit(1)
        if min_window is None or window < min_window:
            min_window = window

    assert min_window is not None
    computed_budget = min_window - doc_tokens - SYSTEM_RESERVE - RESPONSE_HEADROOM - ROUND_OVERHEAD
    effective = min(max_context_cap, computed_budget)

    if effective <= 0:
        LOGGER.error(
            f"Document too large (est. {doc_tokens} tokens) for the smallest "
            f"configured model context window ({min_window} tokens). "
            f"Reduce document size or increase model context capacity."
        )
        sys.exit(1)

    LOGGER.info(
        f"Token budget: {effective} tokens "
        f"(model_min={min_window}, doc={doc_tokens}, cap={max_context_cap})"
    )
    return effective


def _apply_budget_reduction(
    rendered_sections: list[tuple[str, dict, str]],
    budget_tokens: int,
) -> tuple[str, list[str]]:
    """Apply deterministic token budget reduction to rendered compliance text.

    Reduction order (Section 7.2):
      a. FAR packs without explicit parts: Tier 1 summary only
      b. Generic packs: critical + high severity only
      c. GPCM packs: MUA-relevant first, then fill
      d. Truncate lowest-priority pack to summary

    Args:
        rendered_sections: List of (rendered_text, pack_data, pack_name) tuples.
        budget_tokens: Available token budget.

    Returns:
        (combined_text, warnings) tuple.
    """
    warnings: list[str] = []
    combined = "\n\n---\n\n".join(text for text, _, _ in rendered_sections)

    if _estimate_tokens(combined) <= budget_tokens:
        return combined, warnings  # Within budget, no reduction needed

    # Deterministic reduction: remove full packs from the back (lowest
    # priority first), collecting stubs separately. Stubs are appended
    # AFTER the loop so they can't be re-popped on the next iteration.
    kept: list[tuple[str, dict, str]] = list(rendered_sections)
    omitted_stubs: list[str] = []

    while len(kept) > 1:
        # Re-measure with current kept + stubs
        trial = "\n\n---\n\n".join(
            [t for t, _, _ in kept] + omitted_stubs
        )
        if _estimate_tokens(trial) <= budget_tokens:
            break
        # Drop the last full pack, record a stub
        _dropped_text, dropped_data, dropped_name = kept.pop()
        rule_count = _count_rules(dropped_data)
        standard = dropped_data.get("standard_id", dropped_name)
        omitted_stubs.append(
            f"## Authority (OMITTED — over token budget): {standard}\n"
            f"Pack '{dropped_name}' ({rule_count} rules) was omitted. "
            f"Use --pack-parts or reduce pack count for full coverage."
        )
        warnings.append(
            f"Pack '{dropped_name}' omitted from compliance context ({rule_count} rules). "
            f"Budget: {budget_tokens} tokens."
        )

    # Combine kept packs + omission stubs
    all_parts = [t for t, _, _ in kept] + omitted_stubs
    combined = "\n\n---\n\n".join(all_parts)

    # If the remaining content still exceeds budget (single large pack),
    # truncate to fit. Reserve space for the banner before slicing.
    TRUNCATION_BANNER = (
        "\n\n[... TRUNCATED — exceeds token budget. "
        "Use --pack-parts to select specific sections.]"
    )
    if _estimate_tokens(combined) > budget_tokens:
        banner_chars = len(TRUNCATION_BANNER)
        max_chars = max(0, (budget_tokens * 4) - banner_chars)
        if _estimate_tokens(TRUNCATION_BANNER) >= budget_tokens:
            # Budget can't even fit the truncation banner — fail hard
            # rather than silently dropping packs.
            raise ValueError(
                "Compliance context budget exhausted — no space for pack content "
                "after document and prompt reserves. Reduce document size, use "
                "--pack-parts to select fewer rules, or increase "
                "ORACLE_MAX_CONTEXT_TOKENS."
            )
        else:
            cut_point = combined.rfind("\n", 0, max_chars)
            if cut_point <= 0:
                cut_point = max_chars
            combined = combined[:cut_point] + TRUNCATION_BANNER
        warnings.append(
            f"Compliance context truncated to fit {budget_tokens} token budget. "
            f"Use --pack-parts for targeted review."
        )

    return combined, warnings


# ---------------------------------------------------------------------------
# Review (wraps oracle2) — Section 7
# ---------------------------------------------------------------------------

def _extract_docx_text_fallback(document_path: Path) -> str:
    """Extract readable text from a DOCX without external converters."""
    try:
        with zipfile.ZipFile(document_path) as docx_zip:
            document_xml = docx_zip.read("word/document.xml")
    except KeyError as exc:
        raise RuntimeError(f"DOCX is missing word/document.xml: {document_path}") from exc
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Invalid DOCX container: {document_path}") from exc

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise RuntimeError(f"Failed to parse DOCX XML: {document_path}") from exc

    paragraphs: list[str] = []
    for para in root.findall(".//w:p", DOCX_NS):
        parts: list[str] = []
        for node in para.iter():
            tag = node.tag.rsplit("}", 1)[-1] if "}" in node.tag else node.tag
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag in {"br", "cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(re.sub(r"[ \t]+", " ", text))

    draft = "\n\n".join(paragraphs).strip()
    if not draft:
        raise RuntimeError(f"No readable text found in DOCX: {document_path}")
    return draft


def run_review(
    document_path: Path,
    pack_names: list[str],
    pack_dir: Path,
    pack_parts: dict[str, list[int]] | None = None,
    max_rounds: int = 4,
    output_dir: Path | None = None,
    force_text_only: bool = False,
    workflow: str = "manual",
) -> Any:
    """Run oracle2 review against selected rule packs.

    Handles document ingestion (PDF/DOCX/text), pack rendering with token
    budget, and oracle2 invocation. Saves compliance_context.txt and
    pack_manifest_snapshot.json for auditability.

    Returns the OracleSession from oracle2.
    """
    from oracle.oracle2 import run_review as oracle2_run_review

    if not document_path.exists():
        raise FileNotFoundError(f"Document not found: {document_path}")

    # --- Document Ingestion (Section 7.1) ---
    suffix = document_path.suffix.lower()

    if suffix == ".pdf":
        try:
            import fitz
            doc = fitz.open(document_path)
            page_count = len(doc)
            draft = ""
            for page in doc:
                draft += page.get_text("text") + "\n"
            doc.close()
        except ImportError:
            raise RuntimeError("PyMuPDF required for PDF reading")

        # PDF text quality check (Section 7.1)
        avg_chars = len(draft) / max(page_count, 1)
        if avg_chars < 100 and not force_text_only:
            raise RuntimeError(
                f"PDF appears to be scanned/image-only (avg {avg_chars:.0f} chars/page). "
                f"Use --force-text-only to proceed with extracted text as-is, "
                f"or convert to text-based PDF first."
            )
        elif avg_chars < 100:
            LOGGER.warning(
                f"Low-quality PDF text extraction (avg {avg_chars:.0f} chars/page). "
                f"Review may be incomplete."
            )

    elif suffix == ".docx":
        draft = ""
        pandoc_error: str | None = None
        try:
            result = subprocess.run(
                ["pandoc", str(document_path), "-t", "markdown"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                pandoc_error = (result.stderr or "").strip() or "pandoc returned a non-zero exit code"
            else:
                draft = result.stdout
        except FileNotFoundError:
            pandoc_error = "pandoc not installed"

        if not draft.strip():
            if pandoc_error:
                LOGGER.warning(
                    "DOCX markdown conversion unavailable (%s). Falling back to built-in DOCX text extraction.",
                    pandoc_error,
                )
            draft = _extract_docx_text_fallback(document_path)
    elif suffix in (".md", ".markdown", ".txt"):
        # Native markdown / plain text — pass straight through without
        # conversion.  Uploading a .md bypasses the pandoc dependency
        # entirely, which is important when pandoc is not installed on
        # the server (the DOCX pipeline degrades without it).
        draft = document_path.read_text(encoding="utf-8")
    else:
        draft = document_path.read_text(encoding="utf-8")

    LOGGER.info(f"Loaded document: {document_path} ({len(draft)} chars)")

    # --- Pack Rendering (Section 7.2) ---
    compliance_context: str | None = None
    pack_snapshot: list[dict] = []
    budget_warnings: list[str] = []

    if pack_names:
        # Compute token budget
        budget = _compute_token_budget(draft)

        rendered_sections: list[tuple[str, dict, str]] = []
        manifest = _load_manifest(pack_dir)

        for i, pack_name in enumerate(pack_names, 1):
            pack_data, resolved = load_pack(pack_name, pack_dir)
            entry = manifest["packs"].get(resolved, {})
            pack_id = pack_data.get("rule_pack_id", resolved)

            # Determine parts for this pack
            parts_for_pack = pack_parts.get(resolved) if pack_parts else None

            # Draft warning (Section 5.5)
            status = pack_data.get("oracle_metadata", {}).get("status", "draft")
            if status == "draft":
                LOGGER.warning(f"Pack '{resolved}' is LLM-generated and unverified (draft). Use promote-pack to mark as reviewed.")

            rendered = _render_pack_for_oracle(pack_data, pack_id, parts_for_pack)
            pack_title = pack_data.get("standard_title") or pack_data.get("standard_id") or resolved
            labeled = f"## Authority {i}: {pack_title} (pack_id: {pack_id})\n\n{rendered}"
            rendered_sections.append((labeled, pack_data, resolved))

            # Build snapshot entry
            pack_file = pack_dir / entry.get("file", f"{resolved}.json")
            pack_snapshot.append({
                "slug": resolved,
                "content_hash": _compute_content_hash(pack_file) if pack_file.exists() else "",
                "version": pack_data.get("version", "1.0.0"),
                "status": status,
                "rule_count": _count_rules(pack_data),
            })

            LOGGER.info(f"Loaded pack '{resolved}': {_count_rules(pack_data)} rules (status={status})")

        # Apply token budget reduction if needed
        compliance_context, budget_warnings = _apply_budget_reduction(rendered_sections, budget)

        for warning in budget_warnings:
            LOGGER.warning(warning)

        LOGGER.info(
            f"Combined compliance context: {len(compliance_context)} chars "
            f"(~{_estimate_tokens(compliance_context)} tokens, budget={budget})"
        )

    # --- Run oracle2 ---
    session = oracle2_run_review(
        draft=draft,
        document_path=str(document_path),
        max_rounds=max_rounds,
        output_dir=output_dir,
        compliance_context=compliance_context,
        workflow=workflow,
    )

    # --- Save audit artifacts (Section 7.4) ---
    if output_dir is None:
        output_dir = Path("oracle_reviews") / session.session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    if compliance_context:
        (output_dir / "compliance_context.txt").write_text(
            compliance_context, encoding="utf-8"
        )

    if pack_snapshot:
        snapshot = {
            "packs_used": pack_snapshot,
            "compliance_context_hash": (
                f"sha256:{hashlib.sha256(compliance_context.encode()).hexdigest()}"
                if compliance_context else None
            ),
            "token_budget": _compute_token_budget(draft) if pack_names else None,
            "document_token_estimate": _estimate_tokens(draft),
            "truncation_applied": bool(budget_warnings),
            "truncation_details": budget_warnings,
        }
        (output_dir / "pack_manifest_snapshot.json").write_text(
            json.dumps(snapshot, indent=2), encoding="utf-8"
        )

    return session


# ---------------------------------------------------------------------------
# Findings Report (Section 8)
# ---------------------------------------------------------------------------

def _issue_sources(issue: dict) -> list[str]:
    """Source-oracle attribution for a normalized issue, both workflow shapes.

    Ledger (Sonnet referee) nests sources in merged_from dicts; the manual
    workflow (Beth) lists names in source_reviewers.
    """
    sources: list[str] = []
    for merged in issue.get("merged_from", []) or []:
        if isinstance(merged, dict) and merged.get("oracle"):
            if merged["oracle"] not in sources:
                sources.append(merged["oracle"])
    for reviewer in issue.get("source_reviewers", []) or []:
        if isinstance(reviewer, str) and reviewer and reviewer not in sources:
            sources.append(reviewer)
    return sources


def _format_reviewer_verdicts(session: Any) -> list[str]:
    """Render the final valid round's per-reviewer verdicts.

    WHY: each reviewer's overall_verdict is its headline stance on the
    whole document. It was collected in every response and read by
    nothing (AUDIT A3) — the reader could not see when the coordinator's
    consensus claim diverged from the reviewers' own verdicts.
    """
    for r in reversed(session.rounds):
        if not r.valid:
            continue
        verdicts = {
            name: str(out.get("overall_verdict") or "").strip()
            for name, out in r.reviewer_outputs.items()
            if str(out.get("overall_verdict") or "").strip()
        }
        if not verdicts:
            return []
        lines = ["## Reviewer Verdicts (final round)", ""]
        for name in sorted(verdicts):
            lines.append(f"- **{name}**: {verdicts[name]}")
        majors = sorted(n for n, v in verdicts.items() if v == "major_revision")
        if majors and session.converged:
            lines.append("")
            lines.append(
                f"> **Warning:** consensus was reported although "
                f"{', '.join(majors)} returned verdict `major_revision`. "
                f"The override is the coordinator's judgment — see Dissent Summary."
            )
        lines.append("")
        return lines
    return []


def _format_dissent_summary(session: Any) -> list[str]:
    """Render every rejected/unresolved finding with full coordinator reasoning.

    WHY this section exists: the coordinator decides what enters the
    revised draft, but dissent it declines must remain visible to the
    reader with full fidelity — a rejection count is not dissent
    (AUDIT A1, philosophy rule 4). Reasons are NOT truncated here.
    """
    entries: list[tuple[int, dict, dict | None]] = []
    for r in session.rounds:
        if not r.valid:
            continue
        issues_by_id = {
            i.get("issue_id"): i
            for i in r.normalized_issues.get("normalized_issues", [])
            if i.get("issue_id")
        }
        for d in r.coordinator_decisions.get("revision_decisions", []):
            if d.get("decision") in ("rejected_claim", "unresolved_question"):
                entries.append((r.round_number, d, issues_by_id.get(d.get("issue_id"))))

    if not entries:
        return []

    lines = [
        "## Dissent Summary",
        "",
        "> The findings below were raised by reviewer oracles and NOT accepted "
        "into the revised draft. The coordinator's reasoning is recorded in "
        "full. A rejection is the coordinator's judgment, not a consensus "
        "verdict — readers should weigh the reviewer's position themselves.",
        "",
    ]
    for round_num, decision, issue in entries:
        iid = decision.get("issue_id", "?")
        label = (
            "REJECTED BY COORDINATOR"
            if decision.get("decision") == "rejected_claim"
            else "UNRESOLVED QUESTION"
        )
        title = (issue or {}).get("title", "") or iid
        lines.append(f"### [{label}] {title} ({iid}, round {round_num})")
        if issue:
            lines.append(f"**Severity (as raised):** {issue.get('severity', '?')}")
            sources = _issue_sources(issue)
            if sources:
                lines.append(f"**Raised by:** {', '.join(sources)}")
            if issue.get("conflict_flag"):
                lines.append("**⚠ Direct conflict between reviewers on this issue**")
        reason = decision.get("reason", "")
        if reason:
            lines.append(f"**Coordinator reasoning (full):** {reason}")
        lines.append("")
    return lines


def _format_referee_drops(session: Any) -> list[str]:
    """List reviewer findings the referee excluded before coordination.

    WHY: dropped findings previously survived only as aggregate rates;
    the findings themselves vanished (AUDIT A8). Listing them keeps the
    referee's filtering auditable.
    """
    drops: list[tuple[int, dict]] = []
    for r in session.rounds:
        if not r.valid:
            continue
        for d in r.normalized_issues.get("dropped_findings", []):
            if isinstance(d, dict):
                drops.append((r.round_number, d))

    if not drops:
        return []

    lines = [
        "## Findings Dropped by Referee",
        "",
        "> The referee oracle excluded these reviewer findings before they "
        "reached the coordinator. Listed for dissent fidelity.",
        "",
    ]
    for round_num, d in drops:
        lines.append(
            f"- Round {round_num} — **{d.get('oracle', '?')}**: "
            f"{d.get('title', '?')} (drop reason: {d.get('reason', '?')})"
        )
    lines.append("")
    return lines


def format_findings_report(
    session: Any,
    pack_dir: Path,
    pack_names: list[str] | None = None,
    compliance_context: str | None = None,
    output_path: Path | None = None,
) -> str:
    """Generate a formatted findings report from a completed oracle session.

    Uses oracle2_adapter to reconstruct structured data from session files,
    then formats into the Section 8 report structure.
    """
    from oracle.oracle2 import compute_metrics
    from oracle.oracle2_adapter import build_review_result

    metrics = compute_metrics(session)

    # Try to reconstruct structured data via adapter
    session_dir = Path("oracle_reviews") / session.session_id
    if hasattr(session, '_output_dir') and session._output_dir:
        session_dir = session._output_dir
    # Also check the common output directory patterns
    for candidate in [
        Path("oracle_reviews") / session.session_id,
        Path(session.document_path).parent / "oracle_reviews" / session.session_id,
    ]:
        if candidate.exists():
            session_dir = candidate
            break

    lines = [
        "# ORACLE Review Report",
        "",
        f"**Document:** {session.document_path}",
        f"**Session:** {session.session_id}",
        f"**Rounds:** {len(session.rounds)}",
        f"**Converged:** {'Yes' if session.converged else 'No'}",
        "",
    ]

    # consensus_type distinguishes full agreement from agreement-with-residue
    # and from a blocked stop (AUDIT A2) — getattr for pre-A2 session objects.
    consensus_type = getattr(session, "consensus_type", "")
    if consensus_type:
        label = {
            "full_agreement": "Full agreement",
            "stable_with_notes": "Stable, with unresolved notes",
            "blocked": "BLOCKED — stopped without consensus",
        }.get(consensus_type, consensus_type)
        lines.append(f"**Consensus:** {label}")
        lines.append("")

    if session.convergence_reason:
        lines.append(f"**Convergence Reason:** {session.convergence_reason}")
        lines.append("")

    # --- Authority Summary (Section 8, item 2) ---
    if pack_names:
        lines.append("## Authority Summary")
        lines.append("")
        manifest = _load_manifest(pack_dir)
        has_draft = False
        has_generic = False
        has_override = False
        for pn in pack_names:
            try:
                resolved = _resolve_pack_name(pn, manifest)
                entry = manifest["packs"].get(resolved, {})
                status = entry.get("status", "draft")
                lines.append(f"- **{entry.get('name', resolved)}** ({entry.get('rule_count', '?')} rules, status: {status})")
                if status == "draft":
                    has_draft = True
            except ValueError:
                lines.append(f"- **{pn}** (not found in library)")
        lines.append("")

        if has_draft:
            lines.append("> **Warning:** This review used unverified (draft) rule packs. Findings should be validated against source regulations.")
            lines.append("")

    # --- Metrics Summary ---
    lines.extend([
        "## Metrics",
        "",
        f"- Accepted critical defects: {metrics.get('accepted_critical_count', 0)}",
        f"- Accepted high defects: {metrics.get('accepted_high_count', 0)}",
        f"- Total accepted defects: {metrics.get('total_accepted_defects', 0)}",
        f"- Total rejected claims: {metrics.get('total_rejected_claims', 0)}",
        f"- Preference-only findings: {metrics.get('total_preference_only', 0)}",
        f"- Duplicate rate: {metrics.get('duplicate_rate', 0):.1%}",
        f"- Rounds to stability: {metrics.get('rounds_to_stability', 0)}",
        f"- Converged: {metrics.get('converged', False)}",
        "",
    ])

    # --- Reviewer verdicts + Dissent Summary (AUDIT A3 + A1) — before
    # per-round detail so dissent is impossible to miss in a skim read ---
    lines.extend(_format_reviewer_verdicts(session))
    lines.extend(_format_dissent_summary(session))
    lines.extend(_format_referee_drops(session))

    # --- Per-Round Detail ---
    for r in session.rounds:
        if not r.valid:
            continue

        lines.append(f"## Round {r.round_number}")
        lines.append("")

        # Degraded-data disclosure (AUDIT B2): a truncated response that
        # was partially salvaged means this round's finding set may be
        # incomplete — the reader must know, not just the logs.
        degraded = sorted(
            name
            for name, out in r.reviewer_outputs.items()
            if isinstance(out, dict) and out.get("recovered_partial")
        )
        if r.coordinator_decisions.get("recovered_partial"):
            degraded.append("Beth (coordinator)")
        if degraded:
            lines.append(
                f"> **Degraded data:** the response(s) from "
                f"{', '.join(degraded)} were truncated or malformed and only "
                f"partially recovered. This round's finding set may be incomplete."
            )
            lines.append("")

        # Normalized issues
        issues = r.normalized_issues.get("normalized_issues", [])
        if issues:
            for issue in issues:
                sev = issue.get("severity", "?").upper()
                title = issue.get("title", "Untitled")
                iid = issue.get("issue_id", "?")
                problem = issue.get("core_problem", "")
                fix = issue.get("recommended_fix", "")

                lines.append(f"### [{sev}] {title} ({iid})")
                if problem:
                    lines.append(f"**Problem:** {problem}")
                if fix:
                    lines.append(f"**Fix:** {fix}")

                merged = issue.get("merged_from", [])
                if merged:
                    sources = ", ".join(m.get("oracle", "?") for m in merged)
                    lines.append(f"**Sources:** {sources}")
                lines.append("")

        # Coordinator decisions
        decisions = r.coordinator_decisions.get("revision_decisions", [])
        if decisions:
            lines.append("### Coordinator Decisions")
            for d in decisions:
                iid = d.get("issue_id", "?")
                dec = d.get("decision", "?")
                reason = d.get("reason", "")
                lines.append(f"- **{iid}**: {dec}" + (f" — {reason[:200]}" if reason else ""))
            lines.append("")

    # --- Open Questions ---
    # Iterate newest-first: the LAST valid round's open questions are the
    # freshest unresolved dissent. (Iterating oldest-first showed round 1's
    # questions and dropped the final round's — AUDIT A10.)
    for r in reversed(session.rounds):
        if not r.valid:
            continue
        open_qs = r.coordinator_decisions.get("open_questions", [])
        if open_qs:
            lines.append("## Open Questions")
            lines.append("")
            for q in open_qs:
                if isinstance(q, dict):
                    lines.append(f"- {q.get('question', q.get('title', str(q)))}")
                else:
                    lines.append(f"- {q}")
            lines.append("")
            break  # Only show the last valid round's open questions

    report = "\n".join(lines)

    if output_path:
        output_path.write_text(report, encoding="utf-8")
        LOGGER.info(f"Findings report written: {output_path}")

    return report


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------

def cmd_review(args: argparse.Namespace) -> None:
    """Handle 'review' subcommand."""
    pack_dir = _resolve_pack_dir(getattr(args, 'pack_dir', None))

    # Parse --pack-parts (e.g., --pack-parts far=15,19 --pack-parts dfars=252)
    pack_parts: dict[str, list[int]] | None = None
    if hasattr(args, 'pack_parts') and args.pack_parts:
        pack_parts = {}
        for spec in args.pack_parts:
            if "=" in spec:
                pack_name, parts_str = spec.split("=", 1)
                pack_parts[pack_name] = [int(p.strip()) for p in parts_str.split(",") if p.strip().isdigit()]
            else:
                # No prefix — only valid if exactly one FAR-family pack
                parts_list = [int(p.strip()) for p in spec.split(",") if p.strip().isdigit()]
                # Will be resolved later when we know which packs are FAR-family
                pack_parts["__unscoped__"] = parts_list

        # Resolve unscoped parts
        if "__unscoped__" in pack_parts and args.packs:
            far_packs = []
            manifest = _load_manifest(pack_dir)
            for pn in args.packs:
                try:
                    resolved = _resolve_pack_name(pn, manifest)
                    entry = manifest["packs"].get(resolved, {})
                    if entry.get("schema") == "far":
                        far_packs.append(resolved)
                except ValueError:
                    pass

            if len(far_packs) == 1:
                pack_parts[far_packs[0]] = pack_parts.pop("__unscoped__")
            elif len(far_packs) > 1:
                LOGGER.error(
                    f"Multiple FAR-family packs selected ({', '.join(far_packs)}). "
                    f"Use --pack-parts <pack>=<parts> to specify per-pack."
                )
                sys.exit(1)
            else:
                pack_parts.pop("__unscoped__")

    output_dir = Path(args.output_dir) if args.output_dir else None

    session = run_review(
        document_path=Path(args.document),
        pack_names=args.packs or [],
        pack_dir=pack_dir,
        pack_parts=pack_parts,
        max_rounds=args.max_rounds,
        output_dir=output_dir,
        force_text_only=getattr(args, 'force_text_only', False),
        workflow=getattr(args, "workflow", "manual"),
    )

    # Generate findings report
    if output_dir is None:
        output_dir = Path("oracle_reviews") / session.session_id
    report_path = output_dir / "findings_report.md"
    format_findings_report(
        session, pack_dir,
        pack_names=args.packs,
        output_path=report_path,
    )

    from oracle.oracle2 import compute_metrics
    metrics = compute_metrics(session)
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )

    print(f"\nDone. Results in {output_dir}/")
    print(f"  findings_report.md          — Formatted findings report")
    print(f"  final_draft.md              — Canonical revised document")
    print(f"  compliance_context.txt      — Exact compliance text used")
    print(f"  pack_manifest_snapshot.json — Pack versions and hashes")
    print(f"  session_summary.json        — Round-by-round stats")
    print(f"  metrics.json                — QC scoring rubric")


def cmd_generate_pack(args: argparse.Namespace) -> None:
    """Handle 'generate-pack' subcommand."""
    pack_dir = _resolve_pack_dir(getattr(args, 'pack_dir', None))
    pdf_path = Path(args.pdf)
    output_dir = Path(args.output_dir) if args.output_dir else None

    pack_name = generate_pack(
        pdf_path=pdf_path,
        name=args.name,
        output_dir=output_dir,
        pack_dir=pack_dir,
        use_vision=not args.no_vision,
        force_type=args.force_type,
        register=not args.no_register,
        allow_partial=getattr(args, 'allow_partial', False),
        overwrite=getattr(args, 'overwrite', False),
        non_interactive=getattr(args, 'non_interactive', False),
        detect_implicit=getattr(args, 'implicit', False),
    )

    print(f"\nPack generated and registered: {pack_name}")
    print(f"  Status: draft (use 'oracle promote-pack {pack_name} --reviewer <name>' to promote)")
    print(f"  Review with: oracle review document.pdf --packs {pack_name}")


def cmd_list_packs(args: argparse.Namespace) -> None:
    """Handle 'list-packs' subcommand."""
    pack_dir = _resolve_pack_dir(getattr(args, 'pack_dir', None))
    manifest = _load_manifest(pack_dir)
    packs = list(manifest.get("packs", {}).values())

    if not packs:
        print("No packs in library. Generate one with: oracle generate-pack <pdf>")
        return

    print(f"\n{'Name':<30} {'Rules':>6} {'Schema':<10} {'Status':<10} {'Standard':<25} {'Added'}")
    print("-" * 100)
    for p in packs:
        added = p.get("added_at", "")[:10]
        status = p.get("status", "?")
        print(
            f"{p['slug']:<30} {p.get('rule_count', 0):>6} "
            f"{p.get('schema', '?'):<10} {status:<10} "
            f"{p.get('standard_id', ''):<25} {added}"
        )
    print(f"\n{len(packs)} pack(s) in library ({pack_dir})")


def cmd_add_pack(args: argparse.Namespace) -> None:
    """Handle 'add-pack' subcommand.

    Normalizes oracle_metadata (adds defaults if missing), then validates
    against JSON Schema before registering.
    """
    pack_dir = _resolve_pack_dir(getattr(args, 'pack_dir', None))
    pack_path = Path(args.json_file)

    if not pack_path.exists():
        print(f"File not found: {pack_path}")
        sys.exit(1)

    try:
        pack_name = register_pack(
            pack_path, pack_dir,
            name=args.name,
            description=getattr(args, 'description', None),
        )
        print(f"Added pack: {pack_name} (status: draft)")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_remove_pack(args: argparse.Namespace) -> None:
    """Handle 'remove-pack' subcommand."""
    pack_dir = _resolve_pack_dir(getattr(args, 'pack_dir', None))
    if remove_pack(args.name, pack_dir):
        print(f"Removed pack: {args.name}")
    else:
        print(f"Pack not found: {args.name}")
        sys.exit(1)


def cmd_show_pack(args: argparse.Namespace) -> None:
    """Handle 'show-pack' subcommand."""
    pack_dir = _resolve_pack_dir(getattr(args, 'pack_dir', None))
    try:
        pack_data, resolved = load_pack(args.name, pack_dir)
    except (ValueError, FileNotFoundError) as e:
        print(str(e))
        sys.exit(1)

    meta = pack_data.get("oracle_metadata", {})
    schema = _detect_pack_schema(pack_data)

    print(f"\nPack: {resolved}")
    print(f"  Schema:       {schema} ({pack_data.get('schema_version', 'N/A')})")
    print(f"  Standard:     {pack_data.get('standard_id', 'N/A')}")
    print(f"  Title:        {pack_data.get('standard_title', 'N/A')}")
    print(f"  Version:      {pack_data.get('version', 'N/A')}")
    print(f"  Status:       {meta.get('status', 'unknown')}")
    print(f"  Rules:        {_count_rules(pack_data)}")
    print(f"  Extraction:   {pack_data.get('extraction_status', 'complete')}")
    print(f"  Source:       {pack_data.get('source_document', 'N/A')}")

    if meta.get("promoted_by"):
        print(f"  Promoted by:  {meta['promoted_by']} ({meta.get('promoted_at', '?')[:10]})")
    if meta.get("detection_override"):
        print(f"  Override:     --force-type {meta['detection_override']}")

    chunk_failures = pack_data.get("chunk_failures", [])
    if chunk_failures:
        print(f"  Chunk fails:  {len(chunk_failures)}")

    if args.verbose:
        pack_id = pack_data.get("rule_pack_id", resolved)
        print(f"\n--- Rendered for Oracle ---\n")
        print(_render_pack_for_oracle(pack_data, pack_id))


def cmd_promote_pack(args: argparse.Namespace) -> None:
    """Handle 'promote-pack' subcommand."""
    pack_dir = _resolve_pack_dir(getattr(args, 'pack_dir', None))

    # Non-interactive requires --yes (Section 6.2)
    non_interactive = getattr(args, 'non_interactive', False)
    auto_yes = getattr(args, 'yes', False)
    if non_interactive and not auto_yes:
        LOGGER.error(
            "promote-pack requires interactive confirmation. "
            "Use --yes with --non-interactive to auto-confirm."
        )
        sys.exit(1)

    try:
        promote_pack(
            pack_name=args.name,
            pack_dir=pack_dir,
            reviewer=args.reviewer,
            notes=getattr(args, 'notes', None),
            allow_partial=getattr(args, 'allow_partial_promotion', False),
            override_hash_mismatch=getattr(args, 'override_hash_mismatch', False),
            auto_confirm=auto_yes,
        )
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main():
    """ORACLE CLI entry point.

    Parses arguments and routes to the appropriate subcommand handler.
    Validates API keys before executing commands that require them.
    """
    parser = argparse.ArgumentParser(
        prog="oracle",
        description="ORACLE — Orchestrated Review And Compliance Liaison Engine (v1.3.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
BoundState AI 2026 — Proprietary

Examples:
  oracle generate-pack NASA-STD-6016C.pdf
  oracle review proposal.md --packs nasa_std_6016c
  oracle promote-pack nasa_std_6016c --reviewer "Dr. J. Wilde"
  oracle list-packs
""",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--pack-dir", type=str, default=None,
                        help="Override pack library location (default: ~/.oracle/packs/)")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Suppress confirmation prompts")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- review ---
    p_review = subparsers.add_parser("review", help="Review a document against rule packs")
    p_review.add_argument("document", help="Path to the document to review")
    p_review.add_argument("--packs", nargs="+", default=[], help="Pack names from library")
    p_review.add_argument("--pack-parts", action="append", default=[],
                          help="Per-pack part scoping: --pack-parts far=15,19 --pack-parts dfars=252")
    p_review.add_argument("--max-rounds", type=int, default=4, help="Maximum review rounds (default: 4)")
    p_review.add_argument("--workflow", choices=["manual", "ledger"], default=os.environ.get("ORACLE_WORKFLOW", "manual"),
                          help="Review workflow: manual=Beth bundles raw reviews, ledger=Sonnet issue ledger")
    p_review.add_argument("--output-dir", type=str, default=None, help="Output directory")
    p_review.add_argument("--force-text-only", action="store_true",
                          help="Proceed with low-quality PDF text extraction")
    p_review.set_defaults(func=cmd_review)

    # --- generate-pack ---
    p_gen = subparsers.add_parser("generate-pack", help="Generate a rule pack from a regulatory PDF")
    p_gen.add_argument("pdf", help="Path to the regulatory/standards PDF")
    p_gen.add_argument("--name", type=str, default=None, help="Pack name (auto-detected if omitted)")
    p_gen.add_argument("--output-dir", type=str, default=None, help="Output directory for intermediate files")
    p_gen.add_argument("--no-vision", action="store_true", help="Skip vision mode (text-only extraction)")
    p_gen.add_argument("--force-type",
                        choices=["tagged_standard", "far_style", "cfr_style", "generic"],
                        help="Force document type detection")
    p_gen.add_argument("--no-register", action="store_true", help="Don't add to library")
    p_gen.add_argument("--allow-partial", action="store_true",
                        help="Allow registration of packs with partial extraction")
    p_gen.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing pack with same name")
    p_gen.add_argument("--implicit", action="store_true",
                        help="Run Pass 1c: detect implicit obligations without keyword markers")
    p_gen.set_defaults(func=cmd_generate_pack)

    # --- list-packs ---
    p_list = subparsers.add_parser("list-packs", help="List all packs in the library")
    p_list.set_defaults(func=cmd_list_packs)

    # --- add-pack ---
    p_add = subparsers.add_parser("add-pack", help="Import a rule pack JSON into the library")
    p_add.add_argument("json_file", help="Path to rule pack JSON file")
    p_add.add_argument("--name", type=str, default=None, help="Pack name (auto-detected if omitted)")
    p_add.add_argument("--description", type=str, default=None, help="Pack description")
    p_add.set_defaults(func=cmd_add_pack)

    # --- remove-pack ---
    p_rm = subparsers.add_parser("remove-pack", help="Remove a pack from the library")
    p_rm.add_argument("name", help="Pack name to remove")
    p_rm.set_defaults(func=cmd_remove_pack)

    # --- show-pack ---
    p_show = subparsers.add_parser("show-pack", help="Display pack contents and stats")
    p_show.add_argument("name", help="Pack name to display")
    p_show.add_argument("--verbose", "-v", action="store_true", help="Show rendered pack content")
    p_show.set_defaults(func=cmd_show_pack)

    # --- promote-pack ---
    p_promote = subparsers.add_parser("promote-pack", help="Mark a draft pack as reviewed/promoted")
    p_promote.add_argument("name", help="Pack name to promote")
    p_promote.add_argument("--reviewer", required=True, help="Reviewer identity (required)")
    p_promote.add_argument("--notes", type=str, default=None, help="Attestation notes")
    p_promote.add_argument("--allow-partial-promotion", action="store_true",
                           help="Allow promoting packs with partial extraction")
    p_promote.add_argument("--override-hash-mismatch", action="store_true",
                           help="Allow promoting despite source document hash mismatch")
    p_promote.add_argument("--yes", action="store_true",
                           help="Auto-confirm (required with --non-interactive)")
    p_promote.set_defaults(func=cmd_promote_pack)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Propagate global args to subcommands
    if hasattr(args, 'pack_dir') and not args.pack_dir and hasattr(parser, '_default_pack_dir'):
        args.pack_dir = parser._default_pack_dir

    # Validate API keys for commands that need them.
    # generate-pack only needs ANTHROPIC_API_KEY for generic extraction or
    # vision enrichment. FAR/GPCM --no-vision paths use local extractors only.
    if args.command == "generate-pack":
        needs_anthropic = True
        if getattr(args, 'no_vision', False) and getattr(args, 'force_type', None) in ("tagged_standard", "far_style"):
            needs_anthropic = False  # Local-only extraction path
        if needs_anthropic and not os.environ.get("ANTHROPIC_API_KEY"):
            LOGGER.error("ANTHROPIC_API_KEY is required for this generation mode")
            sys.exit(1)
    elif args.command == "review":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            LOGGER.error("ANTHROPIC_API_KEY is required")
            sys.exit(1)
        if args.command == "review":
            missing = []
            if not os.environ.get("OPENAI_API_KEY"):
                missing.append("OPENAI_API_KEY")
            if not os.environ.get("XAI_API_KEY"):
                missing.append("XAI_API_KEY")
            if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
                missing.append("GEMINI_API_KEY or GOOGLE_API_KEY")
            if missing:
                LOGGER.error(f"Missing API keys for review: {', '.join(missing)}")
                sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
