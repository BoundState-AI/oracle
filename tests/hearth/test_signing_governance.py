"""P2-B acceptance gate: real Ed25519 signing, the reviewed-requires-reviewer
invariant, and the governance freshness loop (§13 P2-B; spec §2.2)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hearth.packs.governance import (
    GovernanceError,
    check_freshness,
    invalidate_rules_for_source,
    record_source_snapshot,
)
from hearth.packs.loader import PackError, load_pack
from hearth.packs.signing import (
    generate_keypair,
    sign_rule_dict,
    sign_rule_dict_ed25519,
    verify_rule_signature,
)

from .conftest import make_pack, make_rule

RUN_DAY = date(2026, 6, 12)


def _detection_rule(rule_id: str = "CO-TEST-SIG-001") -> dict:
    return make_rule(
        rule_id,
        "form",
        {
            "summary": "signing test rule",
            "detection": {"type": "clause_regex", "all_of": ["compensation"]},
            "finding": {
                "category": "scope",
                "severity": "info",
                "default_analysis": "n/a",
                "exposure": None,
            },
        },
    )


def _write_pack_dir(tmp_path: Path, rules: list[dict], registry: dict | None = None) -> Path:
    pack = make_pack(rules).to_json_dict()
    pack_dir = tmp_path / "CO-TestCounty"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    if registry is not None:
        # The trusted registry lives at the packs-library ROOT, never inside
        # the pack directory (self-attestation hardening).
        (tmp_path / "keys.json").write_text(json.dumps(registry), encoding="utf-8")
    return pack_dir


def _registry_entry(key_id: str, public_hex: str) -> dict:
    return {
        "keys": [
            {
                "key_id": key_id,
                "owner": "Test Reviewer",
                "public_key_hex": public_hex,
                "created": "2026-06-12",
            }
        ]
    }


def test_ed25519_sign_verify_roundtrip_and_tamper():
    private_hex, public_hex = generate_keypair()
    registry = {"rev-1": _key_record("rev-1", public_hex)}
    rule = _detection_rule()
    rule["signature"] = sign_rule_dict_ed25519(rule, private_hex, "rev-1")
    assert verify_rule_signature(rule, registry) is True

    rule["payload"]["summary"] = "quietly altered"
    assert verify_rule_signature(rule, registry) is False


def _key_record(key_id: str, public_hex: str):
    from hearth.packs.signing import KeyRecord

    return KeyRecord(
        key_id=key_id, owner="Test Reviewer", public_key_hex=public_hex,
        created="2026-06-12",
    )


def test_unknown_key_id_fails_verification():
    private_hex, _public_hex = generate_keypair()
    rule = _detection_rule()
    rule["signature"] = sign_rule_dict_ed25519(rule, private_hex, "ghost-key")
    assert verify_rule_signature(rule, {}) is False


def test_reviewed_rule_with_stub_signature_refuses_to_load(tmp_path):
    rule = _detection_rule()
    rule["status"] = "reviewed"
    rule["authority_review"] = {
        "reviewer": "Test Reviewer",
        "license": "CO-FA-100000000",
        "date": "2026-06-01",
    }
    rule["signature"] = sign_rule_dict(rule)  # stub: drift detection only
    _write_pack_dir(tmp_path, [rule])
    with pytest.raises(PackError, match="cannot attest review"):
        load_pack("CO-TestCounty", packs_dir=tmp_path)


def test_reviewed_rule_with_ed25519_signature_loads(tmp_path):
    private_hex, public_hex = generate_keypair()
    rule = _detection_rule()
    rule["status"] = "reviewed"
    rule["authority_review"] = {
        "reviewer": "Test Reviewer",
        "license": "CO-FA-100000000",
        "date": "2026-06-01",
    }
    rule["signature"] = sign_rule_dict_ed25519(rule, private_hex, "rev-1")
    _write_pack_dir(tmp_path, [rule], registry=_registry_entry("rev-1", public_hex))

    loaded = load_pack("CO-TestCounty", packs_dir=tmp_path)
    assert loaded.pack.rules[0].status == "reviewed"


def test_freshness_reports_missing_stale_and_unhashed(tmp_path):
    pack = make_pack([_detection_rule()])
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    # No lockfile at all: every monitored source is missing.
    report = check_freshness(pack, pack_dir, today=RUN_DAY)
    assert report.fresh is False
    assert {i.kind for i in report.issues} == {"missing_snapshot"}

    # Fresh but unhashed snapshot: informational, not blocking.
    record_source_snapshot(pack_dir, "synthetic", None, today=RUN_DAY)
    report = check_freshness(pack, pack_dir, today=RUN_DAY)
    assert report.fresh is True
    assert {i.kind for i in report.issues} == {"unhashed"}

    # Past the 30-day SLA: blocking.
    record_source_snapshot(pack_dir, "synthetic", "ab" * 32, today=date(2026, 1, 1))
    report = check_freshness(pack, pack_dir, today=RUN_DAY)
    assert report.fresh is False
    assert {i.kind for i in report.issues} == {"stale"}


def test_corrupt_sources_lock_fails_closed(tmp_path):
    pack = make_pack([_detection_rule()])
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "sources.lock.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(GovernanceError):
        check_freshness(pack, pack_dir, today=RUN_DAY)


def test_invalidation_flips_reviewed_rules_and_pack_still_loads(tmp_path):
    private_hex, public_hex = generate_keypair()
    reviewed = _detection_rule("CO-TEST-SIG-REV-001")
    reviewed["status"] = "reviewed"
    reviewed["authority_review"] = {
        "reviewer": "Test Reviewer",
        "license": "CO-FA-100000000",
        "date": "2026-06-01",
    }
    reviewed["source"] = "CREC standard forms library, form XYZ"
    reviewed["signature"] = sign_rule_dict_ed25519(reviewed, private_hex, "rev-1")
    untouched = _detection_rule("CO-TEST-SIG-OTHER-001")
    pack_dir = _write_pack_dir(
        tmp_path, [reviewed, untouched], registry=_registry_entry("rev-1", public_hex)
    )
    pack_path = pack_dir / "pack.json"

    flipped = invalidate_rules_for_source(pack_path, "CREC standard forms")
    assert flipped == 1

    loaded = load_pack("CO-TestCounty", packs_dir=tmp_path)
    by_id = {r.rule_id: r for r in loaded.pack.rules}
    assert by_id["CO-TEST-SIG-REV-001"].status == "provisional"
    assert by_id["CO-TEST-SIG-REV-001"].signature.startswith("STUB1:")
    # The prior human review stays on record even though status dropped.
    assert by_id["CO-TEST-SIG-REV-001"].authority_review is not None
    assert by_id["CO-TEST-SIG-OTHER-001"].status == "provisional"


def test_invalidation_refuses_empty_fragment(tmp_path):
    pack_dir = _write_pack_dir(tmp_path, [_detection_rule()])
    with pytest.raises(GovernanceError):
        invalidate_rules_for_source(pack_dir / "pack.json", "   ")


def test_shipped_pack_is_fresh_as_of_lock_date():
    loaded = load_pack("CO-Larimer")
    report = check_freshness(loaded.pack, loaded.path.parent, today=date(2026, 6, 13))
    assert report.fresh is True
    # Hashes pending is expected founder-mode state, surfaced not hidden.
    assert {i.kind for i in report.issues} == {"unhashed"}


def test_cli_pack_status(capsys):
    from hearth.cli import main

    exit_code = main(["pack-status", "--pack", "CO-Larimer"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "CO-Larimer@2026.06.1" in out
    assert "13 provisional" in out
    assert "STUB1" in out
    assert "Source freshness" in out


def test_cli_pack_status_unknown_pack(capsys):
    from hearth.cli import main

    exit_code = main(["pack-status", "--pack", "XX-Nowhere"])
    assert exit_code == 2
    assert "REFUSED" in capsys.readouterr().out
