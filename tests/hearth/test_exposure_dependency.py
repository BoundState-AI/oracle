"""P2-A acceptance gate: exposure-capture dependencies are explicit and
their absence is user-visible (§13 P2-A; closes the BUILD_NOTES §7 trap)."""

from __future__ import annotations

import json

import pytest

from hearth.core.scrubber.engine import scrub_document
from hearth.packs.loader import BUILTIN_JURISDICTION_DIR, PackError, load_pack
from hearth.packs.signing import sign_rule_dict

from .conftest import GREYROCK_FIXTURE, RUN_DATE

PACK_PATH = BUILTIN_JURISDICTION_DIR / "CO-Larimer" / "pack.json"


def _write_pack(tmp_path, data) -> None:
    pack_dir = tmp_path / "CO-Larimer"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.json").write_text(json.dumps(data), encoding="utf-8")


def test_shipped_pack_declares_the_backstop_dependency():
    pack = load_pack("CO-Larimer").pack
    backstop = next(r for r in pack.rules if r.rule_id == "CO-LAR-BDB-BACKSTOP-001")
    exposure = backstop.payload["finding"]["exposure"]
    assert exposure["capture_from_rule"] == "CO-LAR-BDB-FEE-001"


def test_dangling_capture_from_rule_fails_at_load(tmp_path):
    data = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    backstop = next(
        r for r in data["rules"] if r["rule_id"] == "CO-LAR-BDB-BACKSTOP-001"
    )
    backstop["payload"]["finding"]["exposure"]["capture_from_rule"] = "CO-LAR-GONE-999"
    backstop["signature"] = sign_rule_dict(backstop)
    _write_pack(tmp_path, data)
    with pytest.raises(PackError, match="capture_from_rule"):
        load_pack("CO-Larimer", packs_dir=tmp_path)


def test_missing_capture_is_visible_in_the_finding(tmp_path):
    """Delete the fee rule: the backstop finding must SAY the exposure is
    missing, in the finding text the buyer reads — not only in a log."""
    data = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    data["rules"] = [r for r in data["rules"] if r["rule_id"] != "CO-LAR-BDB-FEE-001"]
    backstop = next(
        r for r in data["rules"] if r["rule_id"] == "CO-LAR-BDB-BACKSTOP-001"
    )
    # The dependency now points at a rule outside the pack; redeclare it as
    # absent so the pack still loads — the capture simply never fires.
    del backstop["payload"]["finding"]["exposure"]["capture_from_rule"]
    backstop["signature"] = sign_rule_dict(backstop)
    _write_pack(tmp_path, data)

    loaded = load_pack("CO-Larimer", packs_dir=tmp_path)
    run = scrub_document(
        GREYROCK_FIXTURE, loaded.pack, target_price_usd=700_000, run_date=RUN_DATE
    )
    backstop_finding = next(
        f for f in run.findings if f.jurisdiction_basis == "CO-LAR-BDB-BACKSTOP-001"
    )
    assert backstop_finding.exposure_usd is None
    assert "Exposure not computed" in backstop_finding.default_analysis
    assert "missing, not zero" in backstop_finding.default_analysis


def test_computed_exposure_carries_no_note():
    loaded = load_pack("CO-Larimer")
    run = scrub_document(
        GREYROCK_FIXTURE, loaded.pack, target_price_usd=700_000, run_date=RUN_DATE
    )
    backstop_finding = next(
        f for f in run.findings if f.jurisdiction_basis == "CO-LAR-BDB-BACKSTOP-001"
    )
    assert backstop_finding.exposure_usd == 21_000
    assert "Exposure not computed" not in backstop_finding.default_analysis
