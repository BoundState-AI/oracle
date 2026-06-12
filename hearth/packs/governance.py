#!/usr/bin/env python3
"""
Module: hearth.packs.governance
Purpose: Pack freshness + auto-invalidation (spec v0.3 §2.2; §13 P2-B).

A pack's governance block names its monitored sources; this module tracks
what the maintainer last snapshotted of those sources (sources.lock.json
beside the pack) and reports staleness against update_sla_days. When a
monitored source changes, `invalidate` flips every dependent reviewed rule
back to provisional (§2.2 auto-invalidation) and re-signs it with the stub
scheme — the prior review attestation no longer covers the new reality.

CLI:
  python -m hearth.packs.governance snapshot <pack.json> --source "<name>" [--sha256 <hex>]
  python -m hearth.packs.governance invalidate <pack.json> "<source fragment>"

Safety Critical: False
Financially Critical: True — stale rules silently treated as fresh would
  drive findings from a legal reality that no longer exists.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__financially_critical__: bool = True

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hearth.data import JurisdictionPack
from hearth.packs.signing import sign_rule_dict

LOGGER = logging.getLogger("hearth.packs.governance")

SOURCES_LOCK_FILENAME = "sources.lock.json"


class GovernanceError(Exception):
    """Lockfile or pack content unusable; caller must fail CLOSED."""


@dataclass(frozen=True)
class SourceSnapshot:
    """What the maintainer last recorded about one monitored source."""

    source: str
    sha256: str | None  # None = presence recorded, content hash pending
    recorded: date


@dataclass(frozen=True)
class FreshnessIssue:
    """One reason the pack's basis may have drifted."""

    source: str
    kind: str  # "missing_snapshot" | "stale" | "unhashed" | "untracked_snapshot"
    detail: str


@dataclass(frozen=True)
class FreshnessReport:
    """Freshness verdict for one pack on one day."""

    pack_id: str
    checked_on: date
    issues: list[FreshnessIssue]

    @property
    def fresh(self) -> bool:
        """True when nothing blocks trusting the pack's source basis."""
        return not any(i.kind in ("missing_snapshot", "stale") for i in self.issues)


def load_sources_lock(pack_dir: Path) -> list[SourceSnapshot]:
    """Read the lockfile; an absent file is an empty (fully stale) state."""
    path = pack_dir / SOURCES_LOCK_FILENAME
    if not path.is_file():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["sources"]
        return [
            SourceSnapshot(
                source=entry["source"],
                sha256=entry.get("sha256"),
                recorded=date.fromisoformat(entry["recorded"]),
            )
            for entry in entries
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise GovernanceError(f"sources lock {path} unusable: {exc}") from exc


def check_freshness(
    pack: JurisdictionPack, pack_dir: Path, today: date | None = None
) -> FreshnessReport:
    """Compare monitored sources against the lockfile, within the SLA."""
    checked_on = today or date.today()
    snapshots = {snap.source: snap for snap in load_sources_lock(pack_dir)}
    sla_days = pack.governance.update_sla_days
    issues: list[FreshnessIssue] = []

    for source in pack.governance.monitored_sources:
        snapshot = snapshots.pop(source, None)
        if snapshot is None:
            issues.append(
                FreshnessIssue(source, "missing_snapshot", "never snapshotted")
            )
            continue
        age = (checked_on - snapshot.recorded).days
        if age > sla_days:
            issues.append(
                FreshnessIssue(
                    source, "stale", f"snapshot is {age} days old (SLA {sla_days})"
                )
            )
        elif snapshot.sha256 is None:
            issues.append(
                FreshnessIssue(source, "unhashed", "content hash pending")
            )

    for orphan in snapshots:
        issues.append(
            FreshnessIssue(orphan, "untracked_snapshot", "not in monitored_sources")
        )
    return FreshnessReport(pack_id=pack.pack_id, checked_on=checked_on, issues=issues)


def record_source_snapshot(
    pack_dir: Path, source: str, sha256: str | None, today: date | None = None
) -> Path:
    """Upsert one source snapshot into the lockfile."""
    snapshots = [s for s in load_sources_lock(pack_dir) if s.source != source]
    snapshots.append(
        SourceSnapshot(source=source, sha256=sha256, recorded=today or date.today())
    )
    path = pack_dir / SOURCES_LOCK_FILENAME
    payload = {
        "sources": [
            {"source": s.source, "sha256": s.sha256, "recorded": s.recorded.isoformat()}
            for s in sorted(snapshots, key=lambda s: s.source)
        ]
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")
    LOGGER.info("recorded snapshot for %r in %s", source, path)
    return path


def invalidate_rules_for_source(pack_path: Path, source_fragment: str) -> int:
    """§2.2 auto-invalidation: a changed source flips dependent reviewed
    rules back to provisional. Returns the number of rules flipped."""
    if not source_fragment.strip():
        raise GovernanceError("refusing to invalidate on an empty source fragment")
    content = json.loads(pack_path.read_text(encoding="utf-8"))
    fragment = source_fragment.lower()
    flipped = 0
    for rule in content.get("rules", []):
        if rule.get("status") != "reviewed":
            continue
        if fragment in str(rule.get("source", "")).lower():
            rule["status"] = "provisional"
            # The Ed25519 review attestation covered the OLD basis; re-sign
            # with the stub so the rule still loads, visibly unreviewed.
            rule["signature"] = sign_rule_dict(rule)
            flipped += 1
            LOGGER.warning(
                "rule %s flipped to provisional (source changed: %s)",
                rule.get("rule_id"),
                source_fragment,
            )
    if flipped:
        pack_path.write_text(
            json.dumps(content, indent=2, ensure_ascii=False) + "\n", "utf-8"
        )
    return flipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hearth.packs.governance")
    sub = parser.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot", help="record a monitored-source snapshot")
    snapshot.add_argument("pack", type=Path)
    snapshot.add_argument("--source", required=True)
    snapshot.add_argument("--sha256", default=None)

    invalidate = sub.add_parser(
        "invalidate", help="flip reviewed rules citing a changed source to provisional"
    )
    invalidate.add_argument("pack", type=Path)
    invalidate.add_argument("fragment")

    options = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if options.command == "snapshot":
        path = record_source_snapshot(options.pack.parent, options.source, options.sha256)
        sys.stdout.write(f"snapshot recorded in {path}\n")
        return 0
    flipped = invalidate_rules_for_source(options.pack, options.fragment)
    sys.stdout.write(f"{flipped} reviewed rule(s) flipped to provisional\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - dev utility entry
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
