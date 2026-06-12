"""P2-C acceptance gate: bulk-file ingest, identity resolution with explicit
confidence, and the join-guarded evidence store (§13 P2-C; spec §2.3, §4.1,
§6)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hearth.cli import main as hearth_main
from hearth.core.identity.resolver import (
    CONFIDENCE_ADDRESS_CONFLICT,
    CONFIDENCE_AUTHORITATIVE,
    normalize_address,
    property_uid,
    resolve_batches,
)
from hearth.data import PropertyEvidence
from hearth.db.evidence_store import (
    EvidenceStore,
    EvidenceStoreError,
    LowConfidenceJoinError,
)
from hearth.ingest import get_adapter
from hearth.ingest.base import (
    IngestBatch,
    IngestError,
    RawPropertyRecord,
    validate_batch,
)
from hearth.ingest.larimer_assessor import LarimerAssessorAdapter

from .conftest import FIXTURES

ASSESSOR_CSV = FIXTURES / "ingest" / "larimer_assessor_SYNTHETIC.csv"
PERMITS_CSV = FIXTURES / "ingest" / "larimer_permits_SYNTHETIC.csv"

UID_SHADOW_MOUNTAIN = property_uid("CO", "Larimer", "R1234567")


# -- normalization + uid ------------------------------------------------------


def test_normalize_address_collapses_variants():
    assert normalize_address("123 Shadow Mountain Drive") == normalize_address(
        "123 Shadow Mountain Dr."
    )
    assert normalize_address("456 West Ursa Major Lane") == "456 W URSA MAJOR LN"


def test_property_uid_is_stable_and_format_insensitive():
    assert property_uid("CO", "Larimer", "R1234567") == property_uid(
        "co", "larimer", "r 123-4567"
    )
    assert property_uid("CO", "Larimer", "R1234567") != property_uid(
        "CO", "Weld", "R1234567"
    )
    assert UID_SHADOW_MOUNTAIN.startswith("hearth:prop:")


# -- adapters (fail closed) ---------------------------------------------------


def test_assessor_adapter_parses_fixture():
    batch = get_adapter("larimer-assessor").parse(ASSESSOR_CSV)
    assert len(batch.records) == 4
    shadow = next(r for r in batch.records if r.parcel_id == "R1234567")
    assert shadow.fields["metro_district_mill_levy"] == 52.0
    assert shadow.fields["last_sale_price"] == 685_000
    assert batch.rights.verified is False  # §4.1: declared, not yet verified
    assert set(shadow.fields) <= set(batch.rights.allowed_fields)


def test_permits_adapter_aggregates_per_parcel():
    batch = get_adapter("larimer-permits").parse(PERMITS_CSV)
    assert len(batch.records) == 2
    shadow = next(r for r in batch.records if r.parcel_id == "R1234567")
    assert shadow.fields["permit_count_total"] == 2
    assert shadow.fields["last_permit_date"] == "2024-08-19"
    assert "REROOF" in shadow.fields["permit_types"]


def test_unknown_adapter_fails_closed():
    with pytest.raises(IngestError, match="unknown ingest adapter"):
        get_adapter("zillow-scraper")


def test_missing_columns_fail_closed(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("parcel_number,situs_address\nR1,123 Elm St\n", encoding="utf-8")
    with pytest.raises(IngestError, match="missing required columns"):
        get_adapter("larimer-assessor").parse(bad)


def test_malformed_row_fails_the_whole_file(tmp_path):
    rows = ASSESSOR_CSV.read_text(encoding="utf-8").splitlines()
    rows.append(rows[1].replace("40.3083", "not-a-latitude").replace("A001", "A005"))
    bad = tmp_path / "bad.csv"
    bad.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="malformed"):
        get_adapter("larimer-assessor").parse(bad)


def test_empty_file_fails_closed(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text(ASSESSOR_CSV.read_text(encoding="utf-8").splitlines()[0] + "\n")
    with pytest.raises(IngestError, match="zero records"):
        get_adapter("larimer-assessor").parse(empty)


def test_fields_outside_rights_declaration_fail(tmp_path):
    batch = IngestBatch(
        source_id="larimer-assessor",
        rights=LarimerAssessorAdapter.rights,
        records=[
            RawPropertyRecord(
                parcel_id="R1",
                address_raw="1 Test Ln",
                fields={"owner_full_name": "J. Doe"},  # NOT in allowed_fields
            )
        ],
        retrieved=date(2026, 6, 12),
    )
    with pytest.raises(IngestError, match="outside the declared data-rights row"):
        validate_batch(batch)


# -- resolver -----------------------------------------------------------------


def test_resolver_assessor_records_get_authoritative_confidence():
    batch = get_adapter("larimer-assessor").parse(ASSESSOR_CSV)
    identities = resolve_batches([batch])
    assert len(identities) == 4
    assert all(i.match_confidence == CONFIDENCE_AUTHORITATIVE for i in identities)
    shadow = next(i for i in identities if i.property_uid == UID_SHADOW_MOUNTAIN)
    assert shadow.address_normalized == "123 SHADOW MOUNTAIN DR"
    assert shadow.geocode.lat == pytest.approx(40.3083)


def test_resolver_flags_address_conflicts_below_join_threshold():
    record_a = RawPropertyRecord(parcel_id="R9", address_raw="12 Elm Street", fields={})
    record_b = RawPropertyRecord(parcel_id="R9", address_raw="98 Oak Avenue", fields={})
    batch_a = IngestBatch(
        "larimer-assessor", LarimerAssessorAdapter.rights, [record_a], date(2026, 6, 12)
    )
    batch_b = IngestBatch(
        "larimer-permits", LarimerAssessorAdapter.rights, [record_b], date(2026, 6, 12)
    )
    (identity,) = resolve_batches([batch_a, batch_b])
    assert identity.match_confidence == CONFIDENCE_ADDRESS_CONFLICT


# -- evidence store -----------------------------------------------------------


def _seeded_store(tmp_path) -> EvidenceStore:
    store = EvidenceStore(tmp_path / "store")
    batch = get_adapter("larimer-assessor").parse(ASSESSOR_CSV)
    for identity in resolve_batches([batch]):
        store.upsert_identity(identity)
    store.add_evidence(
        PropertyEvidence(
            property_uid=UID_SHADOW_MOUNTAIN,
            field="metro_district_mill_levy",
            value=52,
            source="Larimer County Assessor bulk export (larimer.gov/assessor)",
            retrieved=date(2026, 6, 12),
            confidence=0.95,
        )
    )
    return store


def test_store_roundtrip_and_filtering(tmp_path):
    store = _seeded_store(tmp_path)
    assert len(store.identities()) == 4
    rows = store.evidence_for(UID_SHADOW_MOUNTAIN, "metro_district_mill_levy")
    assert [row.value for row in rows] == [52]
    assert rows[0].source.startswith("Larimer County Assessor")


def test_store_unknown_uid_fails_closed(tmp_path):
    store = _seeded_store(tmp_path)
    with pytest.raises(EvidenceStoreError, match="unknown property_uid"):
        store.evidence_for("hearth:prop:doesnotexist")


def test_low_confidence_join_is_blocked_until_override(tmp_path):
    store = _seeded_store(tmp_path)
    identity = store.get_identity(UID_SHADOW_MOUNTAIN)
    low = identity.model_copy(update={"match_confidence": 0.85})
    store.upsert_identity(low)
    with pytest.raises(LowConfidenceJoinError, match="no silent merges"):
        store.evidence_for(UID_SHADOW_MOUNTAIN)

    overridden = low.model_copy(update={"manual_override": True})
    store.upsert_identity(overridden)
    assert store.evidence_for(UID_SHADOW_MOUNTAIN)  # joins again, explicitly


def test_corrupt_store_line_fails_closed(tmp_path):
    store = _seeded_store(tmp_path)
    evidence_file = store.root / "evidence.jsonl"
    evidence_file.write_text(
        evidence_file.read_text(encoding="utf-8") + '{"not": "evidence"}\n',
        encoding="utf-8",
    )
    with pytest.raises(EvidenceStoreError, match="corrupt"):
        store.evidence_for(UID_SHADOW_MOUNTAIN)


# -- CLI end to end -----------------------------------------------------------


def test_cli_ingest_both_sources_end_to_end(tmp_path, capsys):
    store_dir = tmp_path / "store"
    assert (
        hearth_main(
            ["ingest", str(ASSESSOR_CSV), "--adapter", "larimer-assessor",
             "--store", str(store_dir)]
        )
        == 0
    )
    assert (
        hearth_main(
            ["ingest", str(PERMITS_CSV), "--adapter", "larimer-permits",
             "--store", str(store_dir)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "4 upserted" in out
    assert "NOT yet verified" in out  # §4.1 obligation stays visible

    store = EvidenceStore(store_dir)
    assert len(store.identities()) == 4  # permits never forked identities
    rows = store.evidence_for(UID_SHADOW_MOUNTAIN)
    fields = {row.field for row in rows}
    assert "metro_district_mill_levy" in fields
    assert "permit_count_total" in fields  # both sources joined on one uid


def test_cli_ingest_garbage_exits_2(tmp_path, capsys):
    garbage = tmp_path / "garbage.csv"
    garbage.write_text("this,is\nnot,assessor data\n", encoding="utf-8")
    exit_code = hearth_main(
        ["ingest", str(garbage), "--adapter", "larimer-assessor",
         "--store", str(tmp_path / "store")]
    )
    assert exit_code == 2
    assert "REFUSED" in capsys.readouterr().out
