"""P1-A acceptance gate: JSON → model → JSON is lossless for every §2/§11
contract, and the contracts reject what they must (spec v0.3 §12 P1-A)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hearth.data import (
    AuditArtifact,
    BuyerPack,
    JurisdictionPack,
    MicroRule,
    PropertyEvidence,
    PropertyIdentity,
    ScrubFinding,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

ROUNDTRIP_CASES = [
    (BuyerPack, FIXTURES / "buyerpack_canary.json"),
    (JurisdictionPack, FIXTURES / "models" / "jurisdiction_pack.json"),
    (PropertyIdentity, FIXTURES / "models" / "property_identity.json"),
    (PropertyEvidence, FIXTURES / "models" / "property_evidence.json"),
    (ScrubFinding, FIXTURES / "models" / "scrub_finding.json"),
    (AuditArtifact, FIXTURES / "models" / "audit_artifact.json"),
]


@pytest.mark.parametrize(
    "model_cls,fixture", ROUNDTRIP_CASES, ids=[c[0].__name__ for c in ROUNDTRIP_CASES]
)
def test_json_roundtrip_lossless(model_cls, fixture):
    original = json.loads(fixture.read_text(encoding="utf-8"))
    instance = model_cls.model_validate(original)
    dumped = instance.to_json_dict()
    assert dumped == original, f"{model_cls.__name__} round-trip lost or mutated data"
    # Dump → parse → dump must be a fixed point, not merely close.
    assert model_cls.model_validate(dumped).to_json_dict() == dumped


@pytest.mark.parametrize(
    "model_cls,fixture", ROUNDTRIP_CASES, ids=[c[0].__name__ for c in ROUNDTRIP_CASES]
)
def test_unknown_keys_rejected(model_cls, fixture):
    polluted = json.loads(fixture.read_text(encoding="utf-8"))
    polluted["unexpected_key"] = "smuggled"
    with pytest.raises(ValidationError):
        model_cls.model_validate(polluted)


def test_soft_preference_target_types_survive():
    pack = BuyerPack.model_validate_json(
        (FIXTURES / "buyerpack_canary.json").read_text(encoding="utf-8")
    )
    targets = [p.target for p in pack.soft_preferences]
    assert targets[0] == 600 and isinstance(targets[0], int)
    assert targets[1] is True
    assert isinstance(targets[2], str)


def test_reviewed_rule_requires_authority_review():
    pack_json = json.loads(
        (FIXTURES / "models" / "jurisdiction_pack.json").read_text(encoding="utf-8")
    )
    rule = dict(pack_json["rules"][0])
    assert rule["authority_review"] is None
    rule["status"] = "reviewed"
    with pytest.raises(ValidationError, match="authority_review"):
        MicroRule.model_validate(rule)


def test_scrub_finding_requires_human_review_is_immutable_true():
    finding = json.loads(
        (FIXTURES / "models" / "scrub_finding.json").read_text(encoding="utf-8")
    )
    finding["requires_human_review"] = False
    with pytest.raises(ValidationError):
        ScrubFinding.model_validate(finding)


def test_match_confidence_bounds_enforced():
    identity = json.loads(
        (FIXTURES / "models" / "property_identity.json").read_text(encoding="utf-8")
    )
    identity["match_confidence"] = 1.5
    with pytest.raises(ValidationError):
        PropertyIdentity.model_validate(identity)


def test_rule_effective_window():
    pack = JurisdictionPack.model_validate_json(
        (FIXTURES / "models" / "jurisdiction_pack.json").read_text(encoding="utf-8")
    )
    open_ended, bounded = pack.rules
    from datetime import date

    assert open_ended.is_effective_on(date(2026, 6, 11))
    assert not open_ended.is_effective_on(date(2024, 8, 16))
    assert bounded.is_effective_on(date(2026, 6, 11))
    assert not bounded.is_effective_on(date(2027, 1, 2))
    assert pack.pack_id == "CO-TestCounty@2026.06"
