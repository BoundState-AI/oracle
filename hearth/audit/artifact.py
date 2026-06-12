#!/usr/bin/env python3
"""
Module: hearth.audit.artifact
Purpose: Build, persist and verify per-run AuditArtifacts (spec v0.3 §11).

Every scrub run — refusals included — leaves an immutable artifact: source
snapshot IDs (document + pack hashes), pack version and contributing
rule_ids, code/model/prompt hashes, findings, and the rendered output.
Artifacts are written create-only (mode "x") and carry a content hash so
any later mutation is detectable. If the artifact cannot be written, the
run must not report success: AuditWriteError propagates to the CLI and the
run exits 2 (never-suppress-error).

code_hash is real (SHA-256 over the hearth package sources); model/prompt
hashes are honest stub constants in P1 (§12 P1-B) because the deterministic
pipeline has no model and no prompt.

Safety Critical: False
Financially Critical: True

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
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from hearth.core.scrubber.engine import ScrubRun
from hearth.core.signals.landmines import ScanRun
from hearth.data import STUB_MODEL_HASH, STUB_PROMPT_HASH, AuditArtifact
from hearth.packs.loader import LoadedPack

LOGGER = logging.getLogger("hearth.audit.artifact")

DEFAULT_AUDIT_DIR = Path("hearth_audit")

_PLACEHOLDER_HASH = "0" * 64


class AuditWriteError(Exception):
    """Artifact could not be persisted; the run must fail CLOSED."""


class AuditIntegrityError(Exception):
    """Stored artifact does not match its content hash."""


def build_artifact(
    run: ScrubRun,
    loaded_pack: LoadedPack | None,
    rendered_output: str,
    exit_code: int,
    *,
    now: datetime | None = None,
    run_id: str | None = None,
) -> AuditArtifact:
    """Assemble the §11 artifact for one scrub run."""
    artifact = AuditArtifact(
        run_id=run_id or uuid.uuid4().hex,
        run_type="scrub",
        created_at=now or datetime.now(timezone.utc),
        source_snapshot_ids=_snapshot_ids(run, loaded_pack),
        jurisdiction_pack_id=run.pack_id,
        contributing_rule_ids=run.contributing_rule_ids,
        scoring_profile_version=None,
        code_hash=compute_code_hash(),
        model_hash=STUB_MODEL_HASH,
        prompt_hash=STUB_PROMPT_HASH,
        findings=run.findings,
        rendered_output=rendered_output,
        exit_code=exit_code,
        artifact_sha256=_PLACEHOLDER_HASH,
    )
    return artifact.model_copy(
        update={"artifact_sha256": compute_artifact_hash(artifact)}
    )


def build_scan_artifact(
    run: ScanRun,
    loaded_pack: LoadedPack | None,
    store_root: Path | None,
    rendered_output: str,
    exit_code: int,
    *,
    now: datetime | None = None,
    run_id: str | None = None,
) -> AuditArtifact:
    """Assemble the §11 artifact for one landmine scan (§13 P2-D)."""
    artifact = AuditArtifact(
        run_id=run_id or uuid.uuid4().hex,
        run_type="scan",
        created_at=now or datetime.now(timezone.utc),
        source_snapshot_ids=_scan_snapshot_ids(run, loaded_pack, store_root),
        jurisdiction_pack_id=run.pack_id,
        contributing_rule_ids=run.contributing_rule_ids,
        scoring_profile_version=None,
        code_hash=compute_code_hash(),
        model_hash=STUB_MODEL_HASH,
        prompt_hash=STUB_PROMPT_HASH,
        findings=[],
        alerts=run.alerts,
        rendered_output=rendered_output,
        exit_code=exit_code,
        artifact_sha256=_PLACEHOLDER_HASH,
    )
    return artifact.model_copy(
        update={"artifact_sha256": compute_artifact_hash(artifact)}
    )


def _scan_snapshot_ids(
    run: ScanRun, loaded_pack: LoadedPack | None, store_root: Path | None
) -> list[str]:
    """Which evidence/pack state fed the scan (§11)."""
    snapshots = [f"property:{run.property_uid}"]
    if store_root is not None:
        for name in ("identities.jsonl", "evidence.jsonl"):
            store_file = Path(store_root) / name
            digest = (
                hashlib.sha256(store_file.read_bytes()).hexdigest()
                if store_file.is_file()
                else "absent"
            )
            snapshots.append(f"store:{name}:sha256:{digest}")
    if loaded_pack is not None:
        snapshots.append(f"pack:{loaded_pack.pack.pack_id}:sha256:{loaded_pack.sha256}")
    elif run.pack_id is not None:
        snapshots.append(f"pack:{run.pack_id}:in-memory")
    return snapshots


def compute_artifact_hash(artifact: AuditArtifact) -> str:
    """Content hash over the canonical dump, self-hash field excluded."""
    payload = artifact.to_json_dict()
    payload.pop("artifact_sha256")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_artifact(artifact: AuditArtifact, audit_dir: Path) -> Path:
    """Persist create-only; AuditWriteError on any failure (fail CLOSED)."""
    name = (
        f"{artifact.created_at:%Y%m%dT%H%M%S}Z_{artifact.run_id[:12]}_"
        f"{artifact.run_type}.json"
    )
    path = audit_dir / name
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        # "x": immutability starts at birth — an existing file is never
        # overwritten, a collision is an error, not a merge.
        with path.open("x", encoding="utf-8") as handle:
            handle.write(artifact.model_dump_json(indent=2))
            handle.write("\n")
    except OSError as exc:
        raise AuditWriteError(f"cannot write audit artifact {path}: {exc}") from exc
    LOGGER.info("audit artifact written: %s", path)
    return path


def verify_artifact_file(path: Path) -> AuditArtifact:
    """Load an artifact and prove its content hash; raise on tamper."""
    artifact = AuditArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    expected = compute_artifact_hash(artifact)
    if artifact.artifact_sha256 != expected:
        raise AuditIntegrityError(
            f"artifact {path} content hash mismatch: stored "
            f"{artifact.artifact_sha256}, recomputed {expected}"
        )
    return artifact


@lru_cache(maxsize=1)
def compute_code_hash() -> str:
    """SHA-256 over every hearth/*.py source, path-stable and sorted (§11)."""
    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for source in sorted(package_root.rglob("*.py")):
        digest.update(source.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(source.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _snapshot_ids(run: ScrubRun, loaded_pack: LoadedPack | None) -> list[str]:
    """Which data fed the run (§11): document bytes + pack bytes."""
    doc_hash = run.document_sha256 or "unreadable"
    snapshots = [f"doc:{run.document_name}:sha256:{doc_hash}"]
    if loaded_pack is not None:
        snapshots.append(
            f"pack:{loaded_pack.pack.pack_id}:sha256:{loaded_pack.sha256}"
        )
    elif run.pack_id is not None:
        snapshots.append(f"pack:{run.pack_id}:in-memory")
    return snapshots
