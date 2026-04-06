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
