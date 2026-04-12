"""Tests for rule pack normalization — legacy field coercion for FAR and GPCM pack schemas."""
from oracle.pack_validator import normalize_pack_structure


def test_normalize_far_pack_legacy_fields():
    pack = {
        "schema_version": "far_rulepack/v1",
        "parts": {
            "1": [
                {
                    "id": 42,
                    "section": "1.1",
                    "page": "4, 10",
                    "statement_text": "The contractor shall do the thing.",
                }
            ]
        },
    }

    normalized = normalize_pack_structure(pack)
    rule = normalized["parts"]["1"][0]
    assert rule["id"] == "42"
    assert rule["page"] == 4


def test_normalize_gpcm_pack_legacy_fields():
    pack = {
        "schema_version": "gpcm_rulepack/v1",
        "requirements": [
            {
                "id": 42,
                "shall_text": "The system shall do the thing.",
                "page": "9, 11",
            }
        ],
    }

    normalized = normalize_pack_structure(pack)
    requirement = normalized["requirements"][0]
    assert requirement["id"] == "42"
    assert requirement["page"] == 9
