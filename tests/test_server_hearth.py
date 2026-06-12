"""Tests for the /hearth server surface — the CLI pipeline over HTTP
(HEARTH spec v0.3 §3.3 fail-closed, §8 banners, §11 audit; founder-mode
amendment logged in BUILD_NOTES.md)."""

import io
import os
from pathlib import Path

from fastapi.testclient import TestClient

import server

GREYROCK = Path("tests/fixtures/BDB24-6-24_greyrock_2026-06-11_SYNTHETIC.txt")


def _client() -> TestClient:
    return TestClient(server.app)


def _scrub(client, filename, payload, audit_dir, pack="CO-Larimer", **form):
    data = {"pack": pack, **form}
    previous = os.environ.get("HEARTH_AUDIT_DIR")
    os.environ["HEARTH_AUDIT_DIR"] = str(audit_dir)
    try:
        return client.post(
            "/hearth/scrub",
            files={"file": (filename, io.BytesIO(payload), "application/octet-stream")},
            data=data,
        )
    finally:
        if previous is None:
            os.environ.pop("HEARTH_AUDIT_DIR", None)
        else:
            os.environ["HEARTH_AUDIT_DIR"] = previous


def test_hearth_health_no_auth():
    response = _client().get("/hearth/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "hearth"
    assert body["mode"] == "findings-only"


def test_hearth_packs_lists_co_larimer():
    response = _client().get("/hearth/packs")
    assert response.status_code == 200
    body = response.json()
    packs = {p["name"]: p for p in body["packs"]}
    assert packs["CO-Larimer"]["pack_id"] == "CO-Larimer@2026.06.1"
    assert packs["CO-Larimer"]["status"] == "provisional"
    assert packs["CO-Larimer"]["rules"] == 13
    assert packs["CO-Larimer"]["provisional_rules"] == 13
    assert "NOT LEGAL ADVICE" in body["legal_banner"]


def test_scrub_greyrock_end_to_end(tmp_path):
    response = _scrub(
        _client(),
        GREYROCK.name,
        GREYROCK.read_bytes(),
        tmp_path / "audit",
        target_price="700000",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refused"] is False
    assert body["provisional_findings"] == 4
    by_rule = {f["jurisdiction_basis"]: f for f in body["findings"]}
    assert by_rule["CO-LAR-BDB-BACKSTOP-001"]["exposure_usd"] == 21_000
    assert {f["severity"] for f in body["findings"]} == {"warn", "flag"}
    assert "PROVISIONAL BASIS" in body["rendered_report"]
    assert "NOT LEGAL ADVICE" in body["rendered_report"]
    # §11: the run left a verifiable audit artifact where we pointed it.
    artifacts = list((tmp_path / "audit").glob("*.json"))
    assert len(artifacts) == 1
    assert body["audit_artifact"] == str(artifacts[0])


def test_scrub_garbage_pdf_refuses_in_body(tmp_path):
    response = _scrub(
        _client(), "broken.pdf", b"%PDF-1.7\x00not a pdf", tmp_path / "audit"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert [f["severity"] for f in body["findings"]] == ["refuse"]
    assert body["refusal_reason"]
    # Refusals leave an audit trail too.
    assert len(list((tmp_path / "audit").glob("*.json"))) == 1


def test_scrub_unknown_pack_refuses_in_body(tmp_path):
    response = _scrub(
        _client(), "fine.txt", b"1. COMPENSATION. Fee is 3%.",
        tmp_path / "audit", pack="XX-Nowhere",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert "pack unusable" in body["refusal_reason"]


def test_scrub_transport_level_rejections(tmp_path):
    client = _client()
    # Unsupported format never reaches the engine.
    response = _scrub(client, "sheet.xlsx", b"PK\x03\x04", tmp_path)
    assert response.status_code == 422
    # Non-positive target price would poison exposure math.
    response = _scrub(client, "fine.txt", b"1. TEXT.", tmp_path, target_price="0")
    assert response.status_code == 422
    # Path components in the filename are stripped, not traversed.
    response = _scrub(
        client, "../../../etc/evil.txt", b"1. COMPENSATION. Fee is 3%.",
        tmp_path / "audit",
    )
    assert response.status_code == 200
    assert response.json()["document"] == "evil.txt"


# -- Phase-3 app surface (§14 P3-C): everything reachable, not just CLI -------

ASSESSOR_CSV = Path("tests/fixtures/ingest/larimer_assessor_SYNTHETIC.csv")
WELLS_CSV = Path("tests/fixtures/ingest/ecmc_wells_SYNTHETIC.csv")


def _with_store(tmp_path):
    """Point the server-side store + audit dir at tmp for one test."""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        prev_store = os.environ.get("HEARTH_STORE_DIR")
        prev_audit = os.environ.get("HEARTH_AUDIT_DIR")
        os.environ["HEARTH_STORE_DIR"] = str(tmp_path / "store")
        os.environ["HEARTH_AUDIT_DIR"] = str(tmp_path / "audit")
        try:
            yield
        finally:
            for key, prev in (("HEARTH_STORE_DIR", prev_store),
                              ("HEARTH_AUDIT_DIR", prev_audit)):
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev

    return ctx()


def _post_file(client, path, file_path, **form):
    return client.post(
        path,
        files={"file": (file_path.name, io.BytesIO(file_path.read_bytes()),
                        "text/csv")},
        data=form,
    )


def test_full_app_workflow_ingest_to_scan(tmp_path):
    client = _client()
    with _with_store(tmp_path):
        body = _post_file(client, "/hearth/ingest", ASSESSOR_CSV,
                          adapter="larimer-assessor").json()
        assert body["refused"] is False
        assert body["outcomes"]["created"] == 4
        assert body["rights_verified"] is False  # §4.1 stays visible

        body = _post_file(client, "/hearth/wells", WELLS_CSV).json()
        assert body["refused"] is False and body["identities_annotated"] == 4

        body = client.post("/hearth/radon", data={"county": "Larimer"}).json()
        assert body["refused"] is False and body["zone"] == 1

        body = client.post(
            "/hearth/evidence",
            data={"property": "shadow mountain", "field": "fema_flood_zone",
                  "value": "AE", "source_note": "msc.fema.gov lookup"},
        ).json()
        assert body["refused"] is False

        props = client.get("/hearth/properties").json()
        assert len(props["properties"]) == 4
        shadow = next(p for p in props["properties"]
                      if "SHADOW MOUNTAIN" in p["address"])
        assert "fema_flood_zone" in shadow["evidence_fields"]
        assert shadow["joins_blocked"] is False

        scan = client.post(
            "/hearth/scan", data={"property": "shadow mountain"}
        ).json()
        assert scan["refused"] is False
        by_rule = {a["rule_id"]: a for a in scan["alerts"]}
        assert by_rule["CO-LAR-LM-FLOOD-001"]["severity"] == "flag"  # AE
        assert by_rule["CO-LAR-LM-RADON-001"]["severity"] == "warn"  # real zone 1
        assert "NOT LEGAL ADVICE" in scan["rendered_report"]
        assert len(list((tmp_path / "audit").glob("*.json"))) == 1


def test_app_scan_refusal_is_a_result(tmp_path):
    client = _client()
    with _with_store(tmp_path):
        body = client.post("/hearth/scan", data={"property": "nowhere lane"}).json()
        assert body["refused"] is True
        assert "ingest" in body["refusal_reason"]


def test_app_ingest_garbage_refuses_in_body(tmp_path):
    client = _client()
    with _with_store(tmp_path):
        response = client.post(
            "/hearth/ingest",
            files={"file": ("bad.csv", io.BytesIO(b"not,a\nreal,export\n"), "text/csv")},
            data={"adapter": "larimer-assessor"},
        )
        body = response.json()
        assert body["refused"] is True
        assert "missing required columns" in body["reason"]


def test_app_pull_plan_and_pack_status(tmp_path):
    client = _client()
    plan = client.get("/hearth/pull-plan").json()
    ids = {s["source_id"] for s in plan["sources"]}
    assert {"ecmc-wells", "fema-nfhl", "csfs-wildfire"} <= ids

    status = client.get("/hearth/pack-status").json()
    assert status["refused"] is False
    assert status["pack_id"] == "CO-Larimer@2026.06.1"
    assert status["rules_by_status"] == {"provisional": 13}
