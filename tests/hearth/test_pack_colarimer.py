"""P1-C acceptance gate: CO-Larimer pack skeleton, provisional
(spec v0.3 §2.2, §12 P1-C)."""

from __future__ import annotations

import json

import pytest

from hearth.data import JurisdictionPack
from hearth.packs.loader import (
    BUILTIN_JURISDICTION_DIR,
    PackError,
    load_pack,
)
from hearth.packs.signing import SIGNATURE_PREFIX

PACK_PATH = BUILTIN_JURISDICTION_DIR / "CO-Larimer" / "pack.json"

# §12 P1-C composition: 4 BDB findings rules + 4 CBS deadlines + 4 landmines.
EXPECTED_RULES = {
    "CO-LAR-BDB-FEE-001": "commission_norm",
    "CO-LAR-BDB-SCOPE-001": "form",
    "CO-LAR-BDB-BACKSTOP-001": "commission_norm",
    "CO-LAR-BDB-DEFAULT-001": "form",
    "CO-LAR-CBS-DL-INSPOBJ-001": "contract_deadline",
    "CO-LAR-CBS-DL-INSPRES-001": "contract_deadline",
    "CO-LAR-CBS-DL-APPRAISAL-001": "contract_deadline",
    "CO-LAR-CBS-DL-LOAN-001": "contract_deadline",
    "CO-LAR-LM-METRO-001": "landmine",
    "CO-LAR-LM-RADON-001": "landmine",
    "CO-LAR-LM-WILDFIRE-001": "landmine",
    "CO-LAR-LM-OILGAS-001": "landmine",
}


@pytest.fixture(scope="module")
def pack():
    return load_pack("CO-Larimer").pack


def test_pack_validates_against_section_2_2_schema():
    """ACCEPT: the shipped file validates against the §2.2 model directly."""
    raw = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    pack = JurisdictionPack.model_validate(raw)
    # And round-trips losslessly, like every other contract (P1-A).
    assert pack.to_json_dict() == raw
    assert pack.pack_id == "CO-Larimer@2026.06"


def test_pack_has_at_least_12_rules_with_expected_composition(pack):
    assert len(pack.rules) >= 12
    actual = {rule.rule_id: rule.category for rule in pack.rules}
    assert actual == EXPECTED_RULES


def test_every_rule_is_provisional_with_signature_and_source(pack):
    for rule in pack.rules:
        assert rule.status == "provisional", rule.rule_id
        assert rule.authority_review is None, rule.rule_id
        assert rule.signature.startswith(SIGNATURE_PREFIX), rule.rule_id
        # Real citations, not placeholders (§12 P1-C: real source citations).
        assert len(rule.source) > 30, f"{rule.rule_id} source looks like a stub"


def test_governance_block(pack):
    assert pack.governance.status == "provisional"
    assert pack.governance.owner
    assert len(pack.governance.monitored_sources) >= 5
    assert pack.governance.update_sla_days == 30


def test_deadline_rules_carry_lever_and_risk_text(pack):
    deadline_rules = [r for r in pack.rules if r.category == "contract_deadline"]
    assert len(deadline_rules) == 4
    deadlines = {r.payload["deadline"] for r in deadline_rules}
    assert deadlines == {
        "inspection_objection",
        "inspection_resolution",
        "appraisal",
        "loan_availability",
    }
    for rule in deadline_rules:
        # §12 P1-C: payload = lever + risk-if-waived text.
        assert len(rule.payload["lever"]) > 50, rule.rule_id
        assert len(rule.payload["risk_if_waived"]) > 50, rule.rule_id


def test_landmine_rules_are_data_specs_without_built_adapters(pack):
    landmines = {r.rule_id: r for r in pack.rules if r.category == "landmine"}
    assert len(landmines) == 4
    for rule in landmines.values():
        detection = rule.payload["detection"]
        assert detection["type"] == "data_query", rule.rule_id
        assert detection["adapter"], rule.rule_id
        assert detection["thresholds"], rule.rule_id

    metro = landmines["CO-LAR-LM-METRO-001"].payload["detection"]
    assert metro["thresholds"] == [
        {"severity": "warn", "gte": 45},
        {"severity": "flag", "gte": 60},
    ]
    oilgas = landmines["CO-LAR-LM-OILGAS-001"].payload["detection"]
    assert oilgas["radius_ft"] == 2000


def test_tampered_rule_fails_signature_verification(tmp_path):
    """Editing a rule without re-signing must make the pack unusable."""
    data = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    data["rules"][0]["payload"]["finding"]["severity"] = "info"  # soften quietly
    tampered_dir = tmp_path / "CO-Larimer"
    tampered_dir.mkdir(parents=True)
    (tampered_dir / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PackError, match="signature"):
        load_pack("CO-Larimer", packs_dir=tmp_path)


def test_malformed_detection_regex_fails_at_load_time(tmp_path):
    """A bad regex must never surface as a silently missing finding."""
    data = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    data["rules"][0]["payload"]["detection"]["all_of"] = ["(unclosed"]
    from hearth.packs.signing import sign_rule_dict

    data["rules"][0]["signature"] = sign_rule_dict(data["rules"][0])
    bad_dir = tmp_path / "CO-Larimer"
    bad_dir.mkdir(parents=True)
    (bad_dir / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PackError, match="regex"):
        load_pack("CO-Larimer", packs_dir=tmp_path)
