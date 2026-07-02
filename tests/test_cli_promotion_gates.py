"""Promotion gates, builtin tombstones, and manifest-rebuild trust tests.

Pins the WS2 trust/audit fixes:
  - promote_pack refuses a pack file modified after registration
    (tamper laundering via hash re-stamp).
  - promote_pack fails closed without a TTY unless auto-confirmed.
  - remove-pack of a builtin records a tombstone that bootstrap honors;
    a deliberate re-add clears it.
  - _rebuild_manifest only restores "promoted" when the pack file carries
    promotion evidence, and always marks entries rebuilt=true.

No monkeypatching: every function under test takes pack_dir explicitly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle.cli import (
    BUILTIN_PACK_SPECS,
    _bootstrap_builtin_packs,
    _load_manifest,
    _rebuild_manifest,
    _save_manifest,
    _slugify,
    promote_pack,
    register_pack,
    remove_pack,
)


def _generic_pack_payload(rule_pack_id: str = "generic-test-pack") -> dict:
    return {
        "schema_version": "oracle_generic/v1",
        "rule_pack_id": rule_pack_id,
        "standard_id": "TEST-STD-1",
        "standard_title": "Test Standard",
        "version": "1.0.0",
        "generated_at": "2026-04-05T00:00:00Z",
        "source_document": "test.pdf",
        "extraction_method": "test",
        "extraction_status": "complete",
        "total_source_pages": 1,
        "extracted_pages": [1],
        "failed_page_ranges": [],
        "chunk_failures": [],
        "total_rules": 1,
        "oracle_metadata": {
            "name": "Test Pack",
            "slug": "test_pack",
            "description": "Test pack",
            "status": "draft",
            "added_at": "2026-04-05T00:00:00Z",
        },
        "rules": [
            {
                "rule_id": "RULE-001",
                "statement_text": "The system shall do the thing.",
                "severity": "high",
            }
        ],
    }


def _register(tmp_path: Path, name: str = "Test Pack") -> tuple[Path, str]:
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir(exist_ok=True)
    src = tmp_path / "src_pack.json"
    src.write_text(json.dumps(_generic_pack_payload()), encoding="utf-8")
    slug = register_pack(src, pack_dir, name=name)
    return pack_dir, slug


# ---------------------------------------------------------------------------
# Gate 0: content-hash tamper check
# ---------------------------------------------------------------------------

def test_promote_refuses_pack_modified_after_registration(tmp_path):
    pack_dir, slug = _register(tmp_path)

    # Tamper: edit the registered pack file on disk
    pack_path = pack_dir / f"{slug}.json"
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    data["rules"][0]["statement_text"] = "The system shall do something ELSE."
    pack_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="modified on disk"):
        promote_pack(
            pack_name=slug,
            pack_dir=pack_dir,
            reviewer="J. Tester",
            auto_confirm=True,
        )

    # The tampered content must NOT have been blessed
    manifest = _load_manifest(pack_dir)
    assert manifest["packs"][slug]["status"] == "draft"


def test_promote_succeeds_for_untouched_pack(tmp_path):
    pack_dir, slug = _register(tmp_path)

    promote_pack(
        pack_name=slug,
        pack_dir=pack_dir,
        reviewer="J. Tester",
        auto_confirm=True,
    )

    manifest = _load_manifest(pack_dir)
    entry = manifest["packs"][slug]
    assert entry["status"] == "promoted"
    assert entry["promoted_by"] == "J. Tester"
    pack_data = json.loads((pack_dir / f"{slug}.json").read_text(encoding="utf-8"))
    assert pack_data["oracle_metadata"]["status"] == "promoted"


def test_promote_fails_closed_without_tty(tmp_path):
    # pytest runs without a TTY on stdin, so the non-auto-confirm path
    # must refuse rather than crash on input().
    pack_dir, slug = _register(tmp_path)

    with pytest.raises(ValueError, match="interactive confirmation"):
        promote_pack(
            pack_name=slug,
            pack_dir=pack_dir,
            reviewer="J. Tester",
            auto_confirm=False,
        )


# ---------------------------------------------------------------------------
# Builtin tombstones
# ---------------------------------------------------------------------------

def _builtin_slug() -> str:
    return _slugify(BUILTIN_PACK_SPECS[0]["name"])


def test_removed_builtin_is_not_resurrected_by_bootstrap(tmp_path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    _bootstrap_builtin_packs(pack_dir)
    slug = _builtin_slug()
    assert slug in _load_manifest(pack_dir)["packs"]

    assert remove_pack(slug, pack_dir) is True

    # The next bootstrap (any CLI command) must honor the tombstone
    _bootstrap_builtin_packs(pack_dir)
    manifest = _load_manifest(pack_dir)
    assert slug not in manifest["packs"]
    # Tombstones live in a sidecar so a manifest rebuild can't lose them
    sidecar = json.loads((pack_dir / "removed_builtins.json").read_text(encoding="utf-8"))
    assert slug in sidecar


def test_tombstone_survives_manifest_rebuild(tmp_path):
    """A corrupt manifest + rebuild must NOT resurrect a removed builtin —
    the original resurrection bug resurfacing exactly when trust state is
    already in doubt."""
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    _bootstrap_builtin_packs(pack_dir)
    slug = _builtin_slug()
    remove_pack(slug, pack_dir)

    _corrupt_manifest(pack_dir)
    _rebuild_manifest(pack_dir)
    _bootstrap_builtin_packs(pack_dir)

    manifest = _load_manifest(pack_dir)
    assert slug not in manifest["packs"]


def test_deliberate_readd_clears_builtin_tombstone(tmp_path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    _bootstrap_builtin_packs(pack_dir)
    slug = _builtin_slug()
    remove_pack(slug, pack_dir)

    # Re-add the builtin pack file deliberately
    builtin_file = (
        Path("oracle") / "builtin_packs" / BUILTIN_PACK_SPECS[0]["filename"]
    )
    readded = register_pack(
        builtin_file, pack_dir, name=BUILTIN_PACK_SPECS[0]["name"], overwrite=True
    )

    manifest = _load_manifest(pack_dir)
    assert readded == slug
    assert slug in manifest["packs"]
    assert slug not in manifest.get("removed_builtins", [])


# ---------------------------------------------------------------------------
# Manifest rebuild trust
# ---------------------------------------------------------------------------

def _corrupt_manifest(pack_dir: Path) -> None:
    (pack_dir / "manifest.json").write_text("{not json", encoding="utf-8")


def test_rebuild_restores_promotion_only_with_evidence(tmp_path):
    pack_dir, slug = _register(tmp_path)
    promote_pack(
        pack_name=slug, pack_dir=pack_dir, reviewer="J. Tester", auto_confirm=True
    )

    _corrupt_manifest(pack_dir)
    manifest = _rebuild_manifest(pack_dir)

    entry = manifest["packs"][slug]
    assert entry["status"] == "promoted"       # evidence present → restored
    assert entry["promoted_by"] == "J. Tester"
    assert entry["rebuilt"] is True


def test_rebuild_demotes_promoted_claim_without_evidence(tmp_path):
    pack_dir, slug = _register(tmp_path)

    # Forge: pack file claims promoted but carries no promotion evidence
    pack_path = pack_dir / f"{slug}.json"
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    data["oracle_metadata"]["status"] = "promoted"
    pack_path.write_text(json.dumps(data), encoding="utf-8")

    _corrupt_manifest(pack_dir)
    manifest = _rebuild_manifest(pack_dir)

    entry = manifest["packs"][slug]
    assert entry["status"] == "draft"
    assert entry["promoted_by"] is None
    assert entry["rebuilt"] is True
