"""P2-D acceptance gate: the landmine scan engine turns P1-C's data_query
specs into evidence-cited alerts, and fails CLOSED everywhere
(§13 P2-D; spec §2.2, §2.3, §3.1, §6, §11)."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from hearth.audit.artifact import build_scan_artifact, verify_artifact_file
from hearth.cli import main as hearth_main
from hearth.core.identity.resolver import property_uid, resolve_batches
from hearth.core.signals.landmines import scan_property
from hearth.data import PropertyEvidence
from hearth.db.evidence_store import EvidenceStore
from hearth.ingest import get_adapter
from hearth.packs.loader import load_pack
from hearth.utils.render import render_scan_report

from .conftest import FIXTURES, make_pack, make_rule

ASSESSOR_CSV = FIXTURES / "ingest" / "larimer_assessor_SYNTHETIC.csv"
GOLDEN = Path(__file__).parent / "golden" / "scan_alerts_shadow_mountain.json"

RUN_DAY = date(2026, 6, 12)
UID_A = property_uid("CO", "Larimer", "R1234567")  # mills 52 — the warn case
UID_B = property_uid("CO", "Larimer", "R2345678")  # mills 63 — the flag case
UID_C = property_uid("CO", "Larimer", "R3456789")  # mills 0 — the clear case


def _manual(uid: str, field: str, value) -> PropertyEvidence:
    """Buyer-supplied manual entry (§4 table: confidence tier 0.80)."""
    return PropertyEvidence(
        property_uid=uid,
        field=field,
        value=value,
        source="manual:founder (buyer-supplied)",
        retrieved=RUN_DAY,
        confidence=0.8,
    )


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory) -> EvidenceStore:
    store = EvidenceStore(tmp_path_factory.mktemp("scanstore"))
    batch = get_adapter("larimer-assessor").parse(ASSESSOR_CSV)
    for identity in resolve_batches([batch]):
        store.upsert_identity(identity)
    for record in batch.records:
        uid = property_uid("CO", "Larimer", record.parcel_id)
        for field_name, value in record.fields.items():
            store.add_evidence(
                PropertyEvidence(
                    property_uid=uid,
                    field=field_name,
                    value=value,
                    source=batch.rights.source,
                    retrieved=RUN_DAY,
                    confidence=batch.rights.confidence_tier,
                )
            )
    # Risk-layer fields arrive as buyer-supplied manual entries in P2 (the
    # adapters are Phase-3; the rule specs run all the same).
    store.add_evidence(_manual(UID_A, "epa_radon_zone", 1))
    store.add_evidence(_manual(UID_A, "csfs_wildfire_risk_rating", "moderate"))
    store.add_evidence(_manual(UID_A, "wells_within_radius", 1))
    store.add_evidence(_manual(UID_B, "csfs_wildfire_risk_rating", "high"))
    store.add_evidence(_manual(UID_B, "wells_within_radius", 3))
    return store


@pytest.fixture(scope="module")
def pack():
    return load_pack("CO-Larimer").pack


def _alerts_by_rule(run):
    return {alert.rule_id: alert for alert in run.alerts}


def test_warn_thresholds_property_a(seeded_store, pack):
    run = scan_property(UID_A, seeded_store, pack, run_date=RUN_DAY)
    assert run.refused is False
    alerts = _alerts_by_rule(run)
    assert len(alerts) == 4
    assert (alerts["CO-LAR-LM-METRO-001"].status,
            alerts["CO-LAR-LM-METRO-001"].severity) == ("alert", "warn")  # 52 ≥ 45 < 60
    assert (alerts["CO-LAR-LM-RADON-001"].status,
            alerts["CO-LAR-LM-RADON-001"].severity) == ("alert", "warn")  # zone 1
    assert (alerts["CO-LAR-LM-WILDFIRE-001"].status,
            alerts["CO-LAR-LM-WILDFIRE-001"].severity) == ("alert", "warn")
    assert (alerts["CO-LAR-LM-OILGAS-001"].status,
            alerts["CO-LAR-LM-OILGAS-001"].severity) == ("alert", "warn")  # 1 well
    # §6 evidence-first: every alert cites the row it rests on.
    for alert in run.alerts:
        assert alert.evidence, alert.rule_id
        assert alert.evidence[0].source
        assert alert.requires_human_review is True


def test_flag_thresholds_property_b(seeded_store, pack):
    run = scan_property(UID_B, seeded_store, pack, run_date=RUN_DAY)
    alerts = _alerts_by_rule(run)
    assert alerts["CO-LAR-LM-METRO-001"].severity == "flag"  # 63 ≥ 60
    assert alerts["CO-LAR-LM-WILDFIRE-001"].severity == "flag"  # high
    assert alerts["CO-LAR-LM-OILGAS-001"].severity == "flag"  # 3 wells
    # No radon row was supplied: surfaced, never assumed clear (§3.1).
    radon = alerts["CO-LAR-LM-RADON-001"]
    assert radon.status == "insufficient_evidence"
    assert radon.severity is None
    assert "never assume" in radon.analysis


def test_clear_and_insufficient_property_c(seeded_store, pack):
    run = scan_property(UID_C, seeded_store, pack, run_date=RUN_DAY)
    alerts = _alerts_by_rule(run)
    metro = alerts["CO-LAR-LM-METRO-001"]
    assert (metro.status, metro.severity) == ("clear", None)  # 0 mills
    assert metro.evidence  # clear still cites its evidence
    insufficient = [a for a in run.alerts if a.status == "insufficient_evidence"]
    assert len(insufficient) == 3


def test_scan_golden_file(seeded_store, pack):
    run = scan_property(UID_A, seeded_store, pack, run_date=RUN_DAY)
    actual = {
        "property_uid": run.property_uid,
        "pack": run.pack_id,
        "run_date": run.run_date.isoformat(),
        "refused": run.refused,
        "alerts": [alert.to_json_dict() for alert in run.alerts],
    }
    if os.environ.get("HEARTH_UPDATE_GOLDEN") == "1":  # pragma: no cover
        GOLDEN.write_text(
            json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected, (
        "Scan output drifted from golden. If deliberate, regenerate with "
        "HEARTH_UPDATE_GOLDEN=1 and review the diff."
    )


# -- fail-closed paths --------------------------------------------------------


def test_unknown_property_refuses(seeded_store, pack):
    run = scan_property("hearth:prop:nope00000000", seeded_store, pack, run_date=RUN_DAY)
    assert run.refused is True
    assert "unknown property_uid" in run.refusal_reason


def test_low_confidence_identity_blocks_the_scan(seeded_store, pack, tmp_path):
    # Copy the store, then degrade one identity below the join threshold.
    store = EvidenceStore(tmp_path / "lowconf")
    for identity in seeded_store.identities():
        store.upsert_identity(identity)
    (store.root / "evidence.jsonl").write_text(
        (seeded_store.root / "evidence.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    weak = store.get_identity(UID_A).model_copy(update={"match_confidence": 0.85})
    store.upsert_identity(weak)

    run = scan_property(UID_A, store, pack, run_date=RUN_DAY)
    assert run.refused is True
    assert "no silent merges" in run.refusal_reason


def test_malformed_threshold_spec_refuses(seeded_store):
    bad_pack = make_pack(
        [
            make_rule(
                "CO-TEST-LM-BAD-001",
                "landmine",
                {
                    "summary": "broken thresholds",
                    "analysis": "n/a",
                    "detection": {
                        "type": "data_query",
                        "query_field": "metro_district_mill_levy",
                        "thresholds": [{"severity": "warn", "wat": 1}],
                    },
                },
            )
        ]
    )
    run = scan_property(UID_A, seeded_store, bad_pack, run_date=RUN_DAY)
    assert run.refused is True
    assert "no known comparator" in run.refusal_reason


def test_pack_without_landmine_rules_refuses(seeded_store):
    pack = make_pack(
        [
            make_rule(
                "CO-TEST-NOTLM-001",
                "form",
                {
                    "summary": "not a landmine",
                    "detection": {"type": "clause_regex", "all_of": ["x"]},
                    "finding": {
                        "category": "scope",
                        "severity": "info",
                        "default_analysis": "n/a",
                        "exposure": None,
                    },
                },
            )
        ]
    )
    run = scan_property(UID_A, seeded_store, pack, run_date=RUN_DAY)
    assert run.refused is True
    assert "no effective landmine rules" in run.refusal_reason


# -- render + audit -----------------------------------------------------------


def test_scan_report_banners_and_evidence(seeded_store, pack):
    run = scan_property(UID_A, seeded_store, pack, run_date=RUN_DAY)
    report = render_scan_report(run, pack)
    assert "NOT LEGAL ADVICE" in report
    assert "PROVISIONAL BASIS: 4 of 4 alerts" in report
    assert "metro_district_mill_levy = 52" in report
    assert "requires human review: yes" in report


def test_refusal_report_is_unmissable(seeded_store, pack):
    run = scan_property("hearth:prop:nope00000000", seeded_store, pack, run_date=RUN_DAY)
    report = render_scan_report(run, pack)
    assert "SCAN REFUSED" in report
    assert "NOT LEGAL ADVICE" in report


def test_scan_audit_artifact_roundtrips(seeded_store, pack, tmp_path):
    loaded = load_pack("CO-Larimer")
    run = scan_property(UID_A, seeded_store, loaded.pack, run_date=RUN_DAY)
    rendered = render_scan_report(run, loaded.pack)
    artifact = build_scan_artifact(run, loaded, seeded_store.root, rendered, 0)
    assert artifact.run_type == "scan"
    assert len(artifact.alerts) == 4 and artifact.findings == []
    assert any(s.startswith("store:evidence.jsonl:sha256:") for s in artifact.source_snapshot_ids)
    assert any(s.startswith(f"pack:{loaded.pack.pack_id}:sha256:") for s in artifact.source_snapshot_ids)

    from hearth.audit.artifact import write_artifact

    path = write_artifact(artifact, tmp_path)
    assert verify_artifact_file(path) == artifact


# -- CLI end to end -----------------------------------------------------------


def _cli_scan_store(tmp_path) -> Path:
    store_dir = tmp_path / "store"
    assert (
        hearth_main(
            ["ingest", str(ASSESSOR_CSV), "--adapter", "larimer-assessor",
             "--store", str(store_dir)]
        )
        == 0
    )
    store = EvidenceStore(store_dir)
    store.add_evidence(_manual(UID_A, "epa_radon_zone", 1))
    store.add_evidence(_manual(UID_A, "csfs_wildfire_risk_rating", "moderate"))
    store.add_evidence(_manual(UID_A, "wells_within_radius", 1))
    return store_dir


def test_cli_scan_by_address_fragment(tmp_path, capsys):
    store_dir = _cli_scan_store(tmp_path)
    exit_code = hearth_main(
        ["scan", "shadow mountain", "--pack", "CO-Larimer",
         "--store", str(store_dir), "--audit-dir", str(tmp_path / "audit"),
         "--json", str(tmp_path / "alerts.json")]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "PROVISIONAL BASIS" in out
    assert "audit artifact:" in out
    payload = json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))
    assert payload["property_uid"] == UID_A
    assert len(payload["alerts"]) == 4
    assert len(list((tmp_path / "audit").glob("*.json"))) == 1


def test_cli_scan_ambiguous_fragment_refuses(tmp_path, capsys):
    store_dir = _cli_scan_store(tmp_path)
    # "1" hits both "123 SHADOW MOUNTAIN DR" and "1010 FOOTHILLS CT".
    exit_code = hearth_main(
        ["scan", "1", "--pack", "CO-Larimer", "--store", str(store_dir),
         "--audit-dir", str(tmp_path / "audit")]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "ambiguous" in out


def test_cli_scan_unknown_property_refuses(tmp_path, capsys):
    store_dir = _cli_scan_store(tmp_path)
    exit_code = hearth_main(
        ["scan", "no such road", "--pack", "CO-Larimer", "--store", str(store_dir),
         "--audit-dir", str(tmp_path / "audit")]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "SCAN REFUSED" in out
    # Refusals leave the §11 trail too.
    assert len(list((tmp_path / "audit").glob("*.json"))) == 1
