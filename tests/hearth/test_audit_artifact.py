"""AuditArtifact emission, immutability and verification (spec v0.3 §11,
§12 P1-B)."""

from __future__ import annotations

import json

import pytest

from hearth.audit.artifact import (
    AuditIntegrityError,
    AuditWriteError,
    build_artifact,
    compute_code_hash,
    verify_artifact_file,
    write_artifact,
)
from hearth.core.scrubber.engine import scrub_document
from hearth.data import STUB_MODEL_HASH, STUB_PROMPT_HASH
from hearth.packs.loader import load_pack
from hearth.utils.render import render_report

from .conftest import GREYROCK_FIXTURE, RUN_DATE


@pytest.fixture()
def artifact_and_run():
    loaded = load_pack("CO-Larimer")
    run = scrub_document(
        GREYROCK_FIXTURE, loaded.pack, target_price_usd=700_000, run_date=RUN_DATE
    )
    rendered = render_report(run, loaded.pack)
    return build_artifact(run, loaded, rendered, exit_code=0), run, loaded


def test_artifact_carries_section_11_fields(artifact_and_run):
    artifact, run, loaded = artifact_and_run
    # Source snapshot IDs: which data rows/versions fed the run.
    assert any(
        s.startswith(f"doc:{run.document_name}:sha256:") for s in artifact.source_snapshot_ids
    )
    assert f"pack:{loaded.pack.pack_id}:sha256:{loaded.sha256}" in artifact.source_snapshot_ids
    assert artifact.jurisdiction_pack_id == "CO-Larimer@2026.06.1"
    assert artifact.contributing_rule_ids == [
        "CO-LAR-BDB-SCOPE-001",
        "CO-LAR-BDB-FEE-001",
        "CO-LAR-BDB-BACKSTOP-001",
        "CO-LAR-BDB-DEFAULT-001",
    ]
    # Code hash is real; model/prompt hashes are honest P1 stubs (§12 P1-B).
    assert artifact.code_hash == compute_code_hash()
    assert len(artifact.code_hash) == 64
    assert artifact.model_hash == STUB_MODEL_HASH
    assert artifact.prompt_hash == STUB_PROMPT_HASH
    assert artifact.rendered_output  # the run's actual displayed output
    assert len(artifact.findings) == 4


def test_artifact_roundtrips_and_verifies(artifact_and_run, tmp_path):
    artifact, _, _ = artifact_and_run
    path = write_artifact(artifact, tmp_path)
    verified = verify_artifact_file(path)
    assert verified == artifact


def test_artifact_tamper_is_detected(artifact_and_run, tmp_path):
    artifact, _, _ = artifact_and_run
    path = write_artifact(artifact, tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["findings"][0]["severity"] = "info"  # quietly soften a finding
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(AuditIntegrityError):
        verify_artifact_file(path)


def test_artifact_files_are_create_only(artifact_and_run, tmp_path):
    artifact, _, _ = artifact_and_run
    write_artifact(artifact, tmp_path)
    with pytest.raises(AuditWriteError):
        write_artifact(artifact, tmp_path)  # same name: never overwritten


def test_unwritable_audit_dir_fails_closed(artifact_and_run, tmp_path):
    artifact, _, _ = artifact_and_run
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where a directory must go", encoding="utf-8")
    with pytest.raises(AuditWriteError):
        write_artifact(artifact, blocked)
