#!/usr/bin/env python3
"""
Module: oracle.disposition.packs
Purpose: Phase 0/4 rule-pack service — multi-pack load, draft authoring workspace.

Builtin packs under oracle/builtin_packs are never mutated. Curated 6033 seed
lives under oracle/disposition/data/. New packs can be loaded from any JSON
path without code changes (Phase 4 exit condition).

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from oracle.disposition.rulepack import (
    BUILTIN_NASA_6030,
    PackPinError,
    RequirementRecord,
    content_hash_bytes,
    content_hash_path,
    load_requirement_records,
)

LOGGER = logging.getLogger("oracle.disposition.packs")

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_6033 = DATA_DIR / "nasa_std_6033_seed.json"
CURATED_6030 = DATA_DIR / "nasa_std_6030_curated.json"


def load_pack(
    path: Path | str,
    *,
    expected_hash: Optional[str] = None,
    repin: bool = False,
) -> tuple[list[RequirementRecord], str]:
    """Load any structured rule-pack JSON into requirement records."""
    return load_requirement_records(path, expected_hash=expected_hash, repin=repin)


def load_rdw_default_packs(
    *,
    include_6033: bool = True,
    extra_paths: Optional[list[Path | str]] = None,
    repin: bool = True,
) -> tuple[list[RequirementRecord], dict[str, str]]:
    """
    Phase 0 / Stage 0: load 6030 (curated preferred) + curated 6033 seed.

    When nasa_std_6030_curated.json is present under disposition/data/, it is
    preferred over the builtin pack (builtin stays untouched as fallback).

    Returns (merged records, {pack_id: content_hash}).
    """
    hashes: dict[str, str] = {}
    all_recs: list[RequirementRecord] = []
    seen: set[str] = set()

    # Stage 0: curated 6030 supersedes builtin when present
    pack_6030 = CURATED_6030 if CURATED_6030.is_file() else Path(BUILTIN_NASA_6030)
    if CURATED_6030.is_file():
        LOGGER.info("Using curated 6030 pack at %s", CURATED_6030)
    paths: list[Path] = [pack_6030]
    if include_6033 and SEED_6033.is_file():
        paths.append(SEED_6033)
    for p in extra_paths or []:
        paths.append(Path(p))

    for path in paths:
        recs, digest = load_pack(path, repin=repin)
        pack_id = recs[0].rule_pack_id if recs else path.stem
        hashes[pack_id] = digest
        for r in recs:
            if r.requirement_id in seen:
                LOGGER.warning("Duplicate requirement_id %s skipped", r.requirement_id)
                continue
            seen.add(r.requirement_id)
            all_recs.append(r)

    LOGGER.info(
        "Loaded %d requirements from %d packs",
        len(all_recs),
        len(hashes),
    )
    return all_recs, hashes


class DraftPackWorkspace:
    """
    Phase 4: separate draft extraction workspace.

    Does not mutate approved/builtin packs. Writes only under workspace root.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.draft_path = self.root / "draft_pack.json"
        self.meta_path = self.root / "draft_meta.json"

    def import_source_json(self, source: Path | str, *, name: Optional[str] = None) -> Path:
        """Copy a pack JSON into the draft workspace (source bytes preserved via copy)."""
        src = Path(source)
        raw = src.read_bytes()
        # Validate JSON structure
        data = json.loads(raw.decode("utf-8"))
        if "requirements" not in data and "rules" not in data:
            raise ValueError("Pack JSON must contain 'requirements' or 'rules'")
        self.draft_path.write_bytes(raw)
        meta = {
            "name": name or src.stem,
            "source": str(src),
            "content_hash": content_hash_bytes(raw),
            "status": "draft",
            "reviewed_by": None,
        }
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return self.draft_path

    def load_draft(self) -> tuple[list[RequirementRecord], str]:
        if not self.draft_path.is_file():
            raise FileNotFoundError(f"No draft pack at {self.draft_path}")
        return load_pack(self.draft_path, repin=True)

    def mark_reviewed(self, reviewer: str, notes: str = "") -> dict[str, Any]:
        if not self.meta_path.is_file():
            raise FileNotFoundError("No draft meta")
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        if not reviewer or not reviewer.strip():
            raise ValueError("reviewer identity required (FR-003)")
        # Pin content hash at review time (detect post-review mutation at promote)
        meta["content_hash"] = content_hash_path(self.draft_path)
        meta["status"] = "reviewed"
        meta["reviewed_by"] = reviewer.strip()
        meta["notes"] = notes
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    def promote_to(self, dest: Path | str) -> Path:
        """Promote reviewed draft to a destination path (never builtin_packs)."""
        if not self.meta_path.is_file():
            raise FileNotFoundError("No draft meta")
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        if meta.get("status") != "reviewed":
            raise ValueError("Draft must be reviewed before promote (FR-003)")
        # H3: recompute hash at promote; refuse if draft mutated after review
        current_hash = content_hash_path(self.draft_path)
        reviewed_hash = meta.get("content_hash")
        if reviewed_hash and reviewed_hash != current_hash:
            raise ValueError(
                "Draft content changed after mark_reviewed(); re-review required "
                f"(reviewed={reviewed_hash}, current={current_hash})"
            )
        meta["content_hash"] = current_hash
        dest_p = Path(dest)
        if "builtin_packs" in dest_p.parts:
            raise ValueError("Refusing to write into builtin_packs")
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.draft_path, dest_p)
        meta["status"] = "promoted"
        meta["promoted_to"] = str(dest_p)
        meta["promoted_hash"] = current_hash
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return dest_p


def pack_revision_diff(
    old_path: Path | str,
    new_path: Path | str,
) -> dict[str, Any]:
    """
    FR-016: compare two pack files; identify requirement ids needing re-evaluation.
    """
    old_recs, old_h = load_pack(old_path, repin=True)
    new_recs, new_h = load_pack(new_path, repin=True)
    old_map = {r.requirement_id: r for r in old_recs}
    new_map = {r.requirement_id: r for r in new_recs}
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    changed: list[str] = []
    for rid in sorted(set(old_map) & set(new_map)):
        o, n = old_map[rid], new_map[rid]
        if o.shall_text != n.shall_text:
            changed.append(rid)
            continue
        if o.locator.section != n.locator.section or o.locator.page != n.locator.page:
            changed.append(rid)
            continue
        if o.locator.standard != n.locator.standard or o.locator.revision != n.locator.revision:
            changed.append(rid)
            continue
        # H3: actor/trigger/provenance deltas force re-evaluation
        o_actor = o.actor_candidate.value if o.actor_candidate else None
        n_actor = n.actor_candidate.value if n.actor_candidate else None
        if o_actor != n_actor:
            changed.append(rid)
            continue
        o_tr = tuple(t.value for t in o.trigger_candidates)
        n_tr = tuple(t.value for t in n.trigger_candidates)
        if o_tr != n_tr:
            changed.append(rid)
            continue
        if o.pack_content_hash != n.pack_content_hash and o.shall_text == n.shall_text:
            # same text, different pack pin — still reevaluate
            pass
    return {
        "old_hash": old_h,
        "new_hash": new_h,
        "added": added,
        "removed": removed,
        "changed_text_or_locator": changed,
        # H3: removed ids also require re-evaluation (drop/invalidate prior dispositions)
        "reevaluate": sorted(set(added + changed + removed)),
    }
