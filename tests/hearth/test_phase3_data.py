"""P3-A/P3-B acceptance gates: fetch layer (offline-provable), wells
proximity math, real radon-zone integration, buyer-supplied evidence, and
the flood landmine (§14; spec §4, §4.1, §6)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from hearth.cli import main as hearth_main
from hearth.core.identity.resolver import property_uid, resolve_batches
from hearth.core.signals.wells import (
    WellsError,
    compute_well_proximity,
    haversine_ft,
    parse_wells_csv,
)
from hearth.db.evidence_store import EvidenceStore
from hearth.ingest import get_adapter
from hearth.ingest.co_radon import RadonError, stamp_radon_zone
from hearth.ingest.fetch import SOURCES, FetchError, fetch_source, plan_lines

from .conftest import FIXTURES

ASSESSOR_CSV = FIXTURES / "ingest" / "larimer_assessor_SYNTHETIC.csv"
WELLS_CSV = FIXTURES / "ingest" / "ecmc_wells_SYNTHETIC.csv"
UID_A = property_uid("CO", "Larimer", "R1234567")
UID_B = property_uid("CO", "Larimer", "R2345678")
RUN_DAY = date(2026, 6, 12)


def _store_with_assessor(tmp_path) -> EvidenceStore:
    store = EvidenceStore(tmp_path / "store")
    batch = get_adapter("larimer-assessor").parse(ASSESSOR_CSV)
    for identity in resolve_batches([batch]):
        store.upsert_identity(identity)
    return store


# -- P3-A: fetch layer --------------------------------------------------------


def test_pull_plan_is_offline_and_complete():
    lines = "\n".join(plan_lines())
    for source_id in ("larimer-assessor", "ecmc-wells", "fema-nfhl", "csfs-wildfire"):
        assert f"[{source_id}]" in lines
    assert "manual" in lines  # portal-gated sources carry runbooks
    assert "hearth ingest" in lines and "hearth wells" in lines


def test_pull_unknown_source_fails_closed(tmp_path):
    with pytest.raises(FetchError, match="unknown pull source"):
        fetch_source("zillow", tmp_path)


def test_pull_portal_gated_source_prints_runbook(tmp_path):
    with pytest.raises(FetchError, match="portal-gated"):
        fetch_source("larimer-assessor", tmp_path)


def test_pull_mocked_transport_writes_cache_and_manifest(tmp_path):
    payload = b"api,well_name\n05-069-1,TEST\n"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=payload)
    )
    result = fetch_source("ecmc-wells", tmp_path, transport=transport)
    assert result.bytes_written == len(payload)
    assert result.path.read_bytes() == payload
    manifest = json.loads((result.path.parent / "manifest.json").read_text("utf-8"))
    assert manifest["sha256"] == result.sha256
    assert manifest["source_id"] == "ecmc-wells"


def test_pull_http_error_fails_closed_with_runbook(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with pytest.raises(FetchError, match="Manual fallback"):
        fetch_source("ecmc-wells", tmp_path, transport=transport)


def test_pull_empty_body_fails_closed(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b""))
    with pytest.raises(FetchError, match="empty body"):
        fetch_source("ecmc-wells", tmp_path, transport=transport)


def test_every_source_has_consumer_and_provenance_plan():
    for source in SOURCES.values():
        assert source.adapter_hint, source.source_id
        assert source.urls or source.manual_steps, source.source_id


# -- P3-B: wells --------------------------------------------------------------


def test_haversine_known_distance():
    # 1 degree of latitude ≈ 364,600 ft; assert within 1%.
    distance = haversine_ft(40.0, -105.0, 41.0, -105.0)
    assert abs(distance - 364_600) < 3_650


def test_wells_proximity_counts_and_nearest(tmp_path):
    store = _store_with_assessor(tmp_path)
    wells = parse_wells_csv(WELLS_CSV)
    annotated = compute_well_proximity(store, wells, retrieved=RUN_DAY)
    assert annotated == 4

    rows_a = {r.field: r for r in store.evidence_for(UID_A)}
    assert rows_a["wells_within_radius"].value == 1  # PR well; PA excluded
    assert 550 < rows_a["nearest_well_ft"].value < 750
    assert rows_a["wells_within_radius"].source.startswith("ECMC")

    rows_b = {r.field: r for r in store.evidence_for(UID_B)}
    assert rows_b["wells_within_radius"].value == 1  # the AC well


def test_plugged_wells_are_excluded_but_abandoned_counted():
    wells = parse_wells_csv(WELLS_CSV)
    statuses = {w.status for w in wells}
    assert "PA" in statuses  # fixture includes one; engine must skip it
    # The PA well sits ~70 ft from property A; if it were counted the
    # nearest distance would be < 100. Covered by the 550-750 assert above.


def test_wells_malformed_csv_fails_closed(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("api,latitude\n1,40.0\n", encoding="utf-8")
    with pytest.raises(WellsError, match="missing required columns"):
        parse_wells_csv(bad)


def test_wells_without_geocodes_fails_closed(tmp_path):
    store = EvidenceStore(tmp_path / "empty")
    wells = parse_wells_csv(WELLS_CSV)
    with pytest.raises(WellsError, match="failing closed"):
        compute_well_proximity(store, wells)


def test_cli_wells_end_to_end(tmp_path, capsys):
    store = _store_with_assessor(tmp_path)
    exit_code = hearth_main(
        ["wells", str(WELLS_CSV), "--store", str(store.root)]
    )
    assert exit_code == 0
    assert "4 identities" in capsys.readouterr().out


# -- P3-B: radon (REAL data) --------------------------------------------------


def test_radon_stamps_real_zone_1(tmp_path):
    store = _store_with_assessor(tmp_path)
    stamped = stamp_radon_zone(store, "Larimer", retrieved=RUN_DAY)
    assert stamped == 4
    rows = store.evidence_for(UID_A, "epa_radon_zone")
    assert rows[0].value == 1  # EPA Map of Radon Zones, verified 2026-06-12
    assert "EPA" in rows[0].source
    # Idempotent: a second stamp adds nothing.
    assert stamp_radon_zone(store, "Larimer", retrieved=RUN_DAY) == 0


def test_radon_unknown_county_fails_closed(tmp_path):
    store = _store_with_assessor(tmp_path)
    with pytest.raises(RadonError, match="refusing to guess"):
        stamp_radon_zone(store, "Maricopa")


# -- P3-B: buyer-supplied evidence + flood rule end to end ----------------------


def test_full_realtor_proofing_scan(tmp_path, capsys):
    """The §14 headline: assessor + wells + radon + buyer-supplied flood and
    wildfire, scanned — alerts on all five landmine rules, every row cited."""
    store = _store_with_assessor(tmp_path)
    assert hearth_main(["wells", str(WELLS_CSV), "--store", str(store.root)]) == 0
    assert hearth_main(["radon", "--store", str(store.root)]) == 0
    assert hearth_main(
        ["add-evidence", UID_A, "--field", "fema_flood_zone", "--value", "AE",
         "--store", str(store.root), "--source-note", "msc.fema.gov lookup"]
    ) == 0
    assert hearth_main(
        ["add-evidence", UID_A, "--field", "csfs_wildfire_risk_rating",
         "--value", "moderate", "--store", str(store.root)]
    ) == 0
    # Seed the mills evidence the scan needs (assessor fields).
    batch = get_adapter("larimer-assessor").parse(ASSESSOR_CSV)
    from hearth.data import PropertyEvidence

    for record in batch.records:
        uid = property_uid("CO", "Larimer", record.parcel_id)
        store.add_evidence(
            PropertyEvidence(
                property_uid=uid, field="metro_district_mill_levy",
                value=record.fields["metro_district_mill_levy"],
                source=batch.rights.source, retrieved=RUN_DAY,
                confidence=batch.rights.confidence_tier,
            )
        )

    exit_code = hearth_main(
        ["scan", UID_A, "--pack", "CO-Larimer", "--store", str(store.root),
         "--audit-dir", str(tmp_path / "audit"),
         "--json", str(tmp_path / "alerts.json")]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    payload = json.loads((tmp_path / "alerts.json").read_text("utf-8"))
    by_rule = {a["rule_id"]: a for a in payload["alerts"]}
    assert by_rule["CO-LAR-LM-METRO-001"]["severity"] == "warn"      # 52 mills
    assert by_rule["CO-LAR-LM-RADON-001"]["severity"] == "warn"      # REAL zone 1
    assert by_rule["CO-LAR-LM-OILGAS-001"]["severity"] == "warn"     # 1 well, computed
    assert by_rule["CO-LAR-LM-FLOOD-001"]["severity"] == "flag"      # zone AE
    assert by_rule["CO-LAR-LM-WILDFIRE-001"]["severity"] == "warn"   # moderate
    for alert in payload["alerts"]:
        assert alert["evidence"], alert["rule_id"]
