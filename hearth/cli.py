#!/usr/bin/env python3
"""
Module: hearth.cli
Purpose: HEARTH unified CLI (spec v0.3 §12 P1-B).

Commands:
  scrub    Scrub a document against a JurisdictionPack (findings-only)

Usage:
  hearth scrub agreement.pdf --pack CO-Larimer --target-price 700000
  hearth scrub contract.txt --pack CO-Larimer --json findings.json

Exit codes:
  0   scrub completed (findings, if any, are in the report)
  2   REFUSED — unparseable document, unusable pack, or unwritable audit
      trail; the document has NOT been reviewed (fail closed, §3.3/§12)

Every run, refusals included, writes an immutable AuditArtifact (§11).
Phase 1 is findings-only: no suggested_template, no generative legal
language (§8 blocking gate).

Safety Critical: False
Financially Critical: True — exit codes and rendered output are the
  decision surface; never-suppress-error pattern applies.

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
from pathlib import Path

from hearth import __version__
from hearth.audit.artifact import (
    DEFAULT_AUDIT_DIR,
    AuditWriteError,
    build_artifact,
    write_artifact,
)
from hearth.core.scrubber.engine import ScrubRun, refusal_run, scrub_document
from hearth.packs.loader import LoadedPack, PackError, load_pack
from hearth.utils.render import render_report

LOGGER = logging.getLogger("hearth.cli")

EXIT_OK = 0
EXIT_REFUSE = 2


def _positive_int(raw: str) -> int:
    """argparse type: a price of 0 or less would silently poison every
    exposure computation downstream, so reject it at the gate."""
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {raw}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hearth",
        description=(
            "HEARTH — buyer-side real estate intelligence. Surfaces unexplained "
            "defaults with citations; your licensed human drafts and executes."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"hearth {__version__}"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    scrub = subcommands.add_parser(
        "scrub",
        help="scrub a document for unexplained defaults (findings-only)",
        description=(
            "Parse a document (.pdf/.docx/.txt/.md), segment clauses, and run "
            "the jurisdiction pack's deterministic micro-rules. Unparseable "
            "input REFUSES with exit code 2 — never a silent pass."
        ),
    )
    scrub.add_argument("document", type=Path, help="document to scrub")
    scrub.add_argument(
        "--pack",
        required=True,
        help="JurisdictionPack name (e.g. CO-Larimer) or path to a pack.json",
    )
    scrub.add_argument(
        "--packs-dir",
        type=Path,
        default=None,
        help="directory holding <name>/pack.json trees (default: built-in packs)",
    )
    scrub.add_argument(
        "--target-price",
        type=_positive_int,
        default=None,
        metavar="USD",
        help="target purchase price; enables exposure_usd math (e.g. 700000)",
    )
    scrub.add_argument(
        "--json",
        dest="json_out",
        type=Path,
        default=None,
        metavar="PATH",
        help="also write findings as JSON to PATH",
    )
    scrub.add_argument(
        "--audit-dir",
        type=Path,
        default=DEFAULT_AUDIT_DIR,
        help=f"directory for immutable audit artifacts (default: {DEFAULT_AUDIT_DIR})",
    )
    scrub.add_argument("--verbose", action="store_true", help="debug logging")
    scrub.set_defaults(handler=cmd_scrub)

    status = subcommands.add_parser(
        "pack-status",
        help="governance posture of a jurisdiction pack (§13 P2-B)",
        description=(
            "Validate a pack and report rule statuses, signature schemes, and "
            "monitored-source freshness against the governance SLA."
        ),
    )
    status.add_argument(
        "--pack", required=True, help="pack name (e.g. CO-Larimer) or pack.json path"
    )
    status.add_argument("--packs-dir", type=Path, default=None)
    status.add_argument("--verbose", action="store_true", help="debug logging")
    status.set_defaults(handler=cmd_pack_status)

    ingest = subcommands.add_parser(
        "ingest",
        help="ingest a bulk source export into the evidence store (§13 P2-C)",
        description=(
            "Parse a county bulk-export file with a declared adapter, resolve "
            "PropertyIdentities, and append provenance-carrying evidence rows. "
            "Malformed input REFUSES with exit code 2."
        ),
    )
    ingest.add_argument("file", type=Path, help="bulk export file (CSV)")
    ingest.add_argument(
        "--adapter",
        required=True,
        help="adapter source_id (e.g. larimer-assessor, larimer-permits)",
    )
    ingest.add_argument(
        "--store",
        type=Path,
        required=True,
        help="evidence store directory (created if absent)",
    )
    ingest.add_argument("--verbose", action="store_true", help="debug logging")
    ingest.set_defaults(handler=cmd_ingest)

    scan = subcommands.add_parser(
        "scan",
        help="evaluate landmine rules against a property's evidence (§13 P2-D)",
        description=(
            "Run the pack's data_query landmine rules (metro mills, radon, "
            "wildfire, wells) against the evidence store. Unknown property, "
            "blocked identity join, or unusable pack REFUSES with exit code 2."
        ),
    )
    scan.add_argument(
        "property",
        help="property_uid (hearth:prop:...) or an address fragment to resolve",
    )
    scan.add_argument(
        "--pack", required=True, help="JurisdictionPack name or pack.json path"
    )
    scan.add_argument("--packs-dir", type=Path, default=None)
    scan.add_argument(
        "--store", type=Path, required=True, help="evidence store directory"
    )
    scan.add_argument("--json", dest="json_out", type=Path, default=None, metavar="PATH")
    scan.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    scan.add_argument("--verbose", action="store_true", help="debug logging")
    scan.set_defaults(handler=cmd_scan)
    return parser


def cmd_scan(args: argparse.Namespace) -> int:
    from hearth.audit.artifact import build_scan_artifact
    from hearth.core.signals.landmines import refusal_scan, scan_property
    from hearth.db.evidence_store import EvidenceStore, EvidenceStoreError
    from hearth.utils.render import render_scan_report

    loaded: LoadedPack | None = None
    store = None
    try:
        loaded = load_pack(args.pack, args.packs_dir)
    except PackError as exc:
        LOGGER.error("pack load failed closed: %s", exc)
        run = refusal_scan(args.property, reason=f"jurisdiction pack unusable: {exc}")
    else:
        try:
            store = EvidenceStore(args.store)
            uid = _resolve_property_ref(store, args.property)
        except EvidenceStoreError as exc:
            LOGGER.error("scan failed closed: %s", exc)
            run = refusal_scan(args.property, reason=str(exc), pack=loaded.pack)
        else:
            run = scan_property(uid, store, loaded.pack)

    exit_code = EXIT_REFUSE if run.refused else EXIT_OK
    rendered = render_scan_report(run, loaded.pack if loaded else None)

    try:
        artifact = build_scan_artifact(
            run, loaded, args.store if store is not None else None, rendered, exit_code
        )
        audit_path = write_artifact(artifact, args.audit_dir)
    except AuditWriteError as exc:
        LOGGER.error("%s", exc)
        print(rendered)
        print(f"\n*** REFUSED — audit artifact could not be written: {exc}")
        return EXIT_REFUSE

    print(rendered)
    print(f"audit artifact: {audit_path}")

    if args.json_out is not None:
        payload = {
            "property_uid": run.property_uid,
            "pack": run.pack_id,
            "run_date": run.run_date.isoformat(),
            "refused": run.refused,
            "refusal_reason": run.refusal_reason,
            "exit_code": exit_code,
            "alerts": [alert.to_json_dict() for alert in run.alerts],
            "audit_artifact": str(audit_path),
        }
        try:
            args.json_out.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8"
            )
        except OSError as exc:
            LOGGER.error("JSON output failed: %s", exc)
            print(f"\n*** REFUSED — JSON output could not be written: {exc}")
            return EXIT_REFUSE
        print(f"alerts JSON   : {args.json_out}")

    return exit_code


def _resolve_property_ref(store, reference: str) -> str:
    """Resolve a CLI property reference: a uid passes through; anything else
    is an address fragment that must match exactly one identity."""
    from hearth.core.identity.resolver import normalize_address
    from hearth.db.evidence_store import EvidenceStoreError

    if reference.startswith("hearth:prop:"):
        return reference
    fragment = normalize_address(reference)
    if not fragment:
        # "" is a substring of every address — junk input must not quietly
        # resolve to whatever single property happens to be in the store.
        raise EvidenceStoreError(
            f"address fragment {reference!r} normalizes to nothing — "
            "give part of the street address or a property_uid"
        )
    matches = [
        identity
        for identity in store.identities()
        if fragment in identity.address_normalized
    ]
    if len(matches) == 1:
        return matches[0].property_uid
    if not matches:
        raise EvidenceStoreError(
            f"no ingested property matches {reference!r} — run hearth ingest first"
        )
    listing = "; ".join(
        f"{m.property_uid} ({m.address_normalized})" for m in matches[:5]
    )
    raise EvidenceStoreError(
        f"{reference!r} is ambiguous across {len(matches)} properties: {listing} — "
        "use the property_uid"
    )


def cmd_ingest(args: argparse.Namespace) -> int:
    from hearth.core.identity.resolver import (
        property_uid,
        reconcile_identity,
        resolve_batches,
    )
    from hearth.data import PropertyEvidence
    from hearth.db.evidence_store import EvidenceStore, EvidenceStoreError
    from hearth.ingest import IngestError, get_adapter

    try:
        adapter = get_adapter(args.adapter)
        batch = adapter.parse(args.file)
        store = EvidenceStore(args.store)

        outcomes = {"created": 0, "kept": 0, "upgraded": 0, "conflict": 0}
        conflicts: list[str] = []
        for identity in resolve_batches([batch]):
            current = store.get_identity(identity.property_uid)
            merged, outcome = reconcile_identity(current, identity)
            outcomes[outcome] += 1
            if outcome == "conflict":
                conflicts.append(merged.property_uid)
            if merged is not current:
                store.upsert_identity(merged)

        rows = 0
        for record in batch.records:
            uid = property_uid("CO", "Larimer", record.parcel_id)
            for field_name, value in record.fields.items():
                store.add_evidence(
                    PropertyEvidence(
                        property_uid=uid,
                        field=field_name,
                        value=value,
                        source=batch.rights.source,
                        retrieved=batch.retrieved,
                        confidence=batch.rights.confidence_tier,
                    )
                )
                rows += 1
    except (IngestError, EvidenceStoreError) as exc:
        LOGGER.error("ingest failed closed: %s", exc)
        print(f"*** REFUSED — ingest failed closed: {exc}")
        return EXIT_REFUSE

    print(f"ingested {args.file.name} via {batch.source_id}")
    print(
        f"  identities    : {outcomes['created']} created, "
        f"{outcomes['upgraded']} upgraded, {outcomes['kept']} kept, "
        f"{outcomes['conflict']} in conflict"
    )
    print(f"  evidence rows : {rows} appended (source confidence {batch.rights.confidence_tier})")
    print(f"  store         : {args.store}")
    for uid in conflicts:
        print(
            f"  !! ADDRESS CONFLICT on {uid}: sources disagree on the situs — "
            "confidence dropped, evidence joins are BLOCKED until resolved (§2.3)"
        )
    if not batch.rights.verified:
        print(
            "  NOTE: this source's data-rights row is founder-declared and "
            "NOT yet verified (§4.1)."
        )
    return EXIT_OK


def cmd_pack_status(args: argparse.Namespace) -> int:
    from hearth.packs.governance import GovernanceError, check_freshness
    from hearth.utils.render import render_pack_status

    try:
        loaded = load_pack(args.pack, args.packs_dir)
        freshness = check_freshness(loaded.pack, loaded.path.parent)
    except (PackError, GovernanceError) as exc:
        LOGGER.error("pack-status failed closed: %s", exc)
        print(f"*** REFUSED — pack unusable: {exc}")
        return EXIT_REFUSE
    print(render_pack_status(loaded.pack, loaded.path, freshness))
    return EXIT_OK


def cmd_scrub(args: argparse.Namespace) -> int:
    loaded: LoadedPack | None = None
    try:
        loaded = load_pack(args.pack, args.packs_dir)
    except PackError as exc:
        LOGGER.error("pack load failed closed: %s", exc)
        run = refusal_run(
            Path(args.document).name,
            reason=f"jurisdiction pack unusable: {exc}",
            target_price_usd=args.target_price,
        )
    else:
        run = scrub_document(
            args.document, loaded.pack, target_price_usd=args.target_price
        )

    exit_code = EXIT_REFUSE if run.refused else EXIT_OK
    rendered = render_report(run, loaded.pack if loaded else None)

    try:
        artifact = build_artifact(run, loaded, rendered, exit_code)
        audit_path = write_artifact(artifact, args.audit_dir)
    except AuditWriteError as exc:
        # A run that cannot leave its §11 trail must not report success.
        LOGGER.error("%s", exc)
        print(rendered)
        print(f"\n*** REFUSED — audit artifact could not be written: {exc}")
        return EXIT_REFUSE

    print(rendered)
    print(f"audit artifact: {audit_path}")

    if args.json_out is not None:
        try:
            _write_json(args.json_out, run, exit_code, audit_path)
        except OSError as exc:
            LOGGER.error("JSON output failed: %s", exc)
            print(f"\n*** REFUSED — JSON output could not be written: {exc}")
            return EXIT_REFUSE
        print(f"findings JSON : {args.json_out}")

    return exit_code


def _write_json(path: Path, run: ScrubRun, exit_code: int, audit_path: Path) -> None:
    payload = {
        "document": run.document_name,
        "document_sha256": run.document_sha256,
        "pack": run.pack_id,
        "run_date": run.run_date.isoformat(),
        "target_price_usd": run.target_price_usd,
        "refused": run.refused,
        "exit_code": exit_code,
        "findings": [finding.to_json_dict() for finding in run.findings],
        "audit_artifact": str(audit_path),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.handler(args)


if __name__ == "__main__":  # pragma: no cover - module execution guard
    sys.exit(main())
