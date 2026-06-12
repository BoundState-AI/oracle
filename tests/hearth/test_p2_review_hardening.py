"""Regression tests from the Phase-2 adversarial review — every finding
pinned (§13; spec §2.2, §2.3)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hearth.cli import main as hearth_main
from hearth.core.identity.resolver import property_uid
from hearth.core.signals.landmines import scan_property
from hearth.data import PropertyEvidence
from hearth.db.evidence_store import EvidenceStore, LowConfidenceJoinError
from hearth.packs.loader import BUILTIN_JURISDICTION_DIR, PackError, load_pack
from hearth.packs.signing import (
    generate_keypair,
    sign_rule_dict,
    sign_rule_dict_ed25519,
)

from .conftest import FIXTURES, make_pack, make_rule

ASSESSOR_CSV = FIXTURES / "ingest" / "larimer_assessor_SYNTHETIC.csv"
UID_A = property_uid("CO", "Larimer", "R1234567")
RUN_DAY = date(2026, 6, 12)


# MAJOR-1: the realistic assessor-then-permits CLI flow must surface a
# cross-source address conflict and block joins — never silently merge.
def test_cli_cross_source_address_conflict_blocks_joins(tmp_path, capsys):
    store_dir = tmp_path / "store"
    assert (
        hearth_main(
            ["ingest", str(ASSESSOR_CSV), "--adapter", "larimer-assessor",
             "--store", str(store_dir)]
        )
        == 0
    )
    conflicting = tmp_path / "permits_wrong_situs.csv"
    conflicting.write_text(
        "permit_number,parcel_number,address,issued_date,permit_type,valuation,status\n"
        "BP99-0001,R1234567,999 Wrong Way,2024-01-15,REROOF,12000,FINALED\n",
        encoding="utf-8",
    )
    assert (
        hearth_main(
            ["ingest", str(conflicting), "--adapter", "larimer-permits",
             "--store", str(store_dir)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "ADDRESS CONFLICT" in out
    assert "1 in conflict" in out

    store = EvidenceStore(store_dir)
    identity = store.get_identity(UID_A)
    assert identity.match_confidence == 0.85
    assert identity.manual_override is False
    with pytest.raises(LowConfidenceJoinError):
        store.evidence_for(UID_A)
    # And the scan refuses rather than pricing the wrong house.
    run = scan_property(UID_A, store, load_pack("CO-Larimer").pack, run_date=RUN_DAY)
    assert run.refused is True


def test_matching_addresses_across_sources_do_not_conflict(tmp_path, capsys):
    store_dir = tmp_path / "store"
    hearth_main(["ingest", str(ASSESSOR_CSV), "--adapter", "larimer-assessor",
                 "--store", str(store_dir)])
    hearth_main(["ingest", str(FIXTURES / "ingest" / "larimer_permits_SYNTHETIC.csv"),
                 "--adapter", "larimer-permits", "--store", str(store_dir)])
    out = capsys.readouterr().out
    assert "0 in conflict" in out
    store = EvidenceStore(store_dir)
    assert store.get_identity(UID_A).match_confidence == 0.97
    assert store.evidence_for(UID_A)  # joins fine


# MAJOR-2: a pack directory shipping its own keys.json must not be able to
# self-attest review.
def test_pack_shipping_its_own_registry_cannot_self_attest(tmp_path):
    private_hex, public_hex = generate_keypair()
    rule = make_rule(
        "CO-TEST-FORGE-001",
        "form",
        {
            "summary": "forged review",
            "detection": {"type": "clause_regex", "all_of": ["x"]},
            "finding": {
                "category": "scope", "severity": "info",
                "default_analysis": "n/a", "exposure": None,
            },
        },
    )
    rule["status"] = "reviewed"
    rule["authority_review"] = {
        "reviewer": "Mallory", "license": "FAKE-1", "date": "2026-06-01",
    }
    rule["signature"] = sign_rule_dict_ed25519(rule, private_hex, "mallory-1")
    pack_dir = tmp_path / "CO-TestCounty"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.json").write_text(
        json.dumps(make_pack([rule]).to_json_dict()), encoding="utf-8"
    )
    # Attacker ships the registry INSIDE the pack — must be ignored.
    (pack_dir / "keys.json").write_text(
        json.dumps({"keys": [{"key_id": "mallory-1", "owner": "Mallory",
                              "public_key_hex": public_hex, "created": "2026-06-01"}]}),
        encoding="utf-8",
    )
    with pytest.raises(PackError, match="signature verification"):
        load_pack("CO-TestCounty", packs_dir=tmp_path)


# MINOR-3: dangling capture_from_rule must be rejected on EVERY rule type.
def test_dangling_capture_on_data_query_rule_rejected(tmp_path):
    data = json.loads(
        (BUILTIN_JURISDICTION_DIR / "CO-Larimer" / "pack.json").read_text("utf-8")
    )
    metro = next(r for r in data["rules"] if r["rule_id"] == "CO-LAR-LM-METRO-001")
    metro["payload"]["finding"] = {
        "exposure": {"method": "pct_capture_times_target_price",
                     "pct_capture": "x", "capture_from_rule": "CO-LAR-GONE-999"}
    }
    metro["signature"] = sign_rule_dict(metro)
    pack_dir = tmp_path / "CO-Larimer"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PackError, match="capture_from_rule"):
        load_pack("CO-Larimer", packs_dir=tmp_path)


# MINOR-4: junk address fragments must refuse, even with one property stored.
def test_junk_address_fragment_refuses_on_single_property_store(tmp_path, capsys):
    store_dir = tmp_path / "store"
    single = tmp_path / "one.csv"
    lines = ASSESSOR_CSV.read_text(encoding="utf-8").splitlines()
    single.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    hearth_main(["ingest", str(single), "--adapter", "larimer-assessor",
                 "--store", str(store_dir)])
    for junk in ("!!!", "   ", "."):
        exit_code = hearth_main(
            ["scan", junk, "--pack", "CO-Larimer", "--store", str(store_dir),
             "--audit-dir", str(tmp_path / "audit")]
        )
        assert exit_code == 2, f"junk fragment {junk!r} must refuse"
    assert "normalizes to nothing" in capsys.readouterr().out


# NIT-7: boolean evidence must not satisfy numeric thresholds.
def test_boolean_evidence_fails_closed(tmp_path):
    store = EvidenceStore(tmp_path / "store")
    from hearth.core.identity.resolver import resolve_batches
    from hearth.ingest import get_adapter

    batch = get_adapter("larimer-assessor").parse(ASSESSOR_CSV)
    for identity in resolve_batches([batch]):
        store.upsert_identity(identity)
    store.add_evidence(
        PropertyEvidence(
            property_uid=UID_A, field="epa_radon_zone", value="true",
            source="manual:bad-entry", retrieved=RUN_DAY, confidence=0.8,
        )
    )
    run = scan_property(UID_A, store, load_pack("CO-Larimer").pack, run_date=RUN_DAY)
    assert run.refused is True  # "true" is not a numeric zone — fail closed
