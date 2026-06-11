"""Tests for vision-repair field provenance (retrieved vs interpreted separation)."""
from __future__ import annotations

from oracle.gpcm_rulepack_adapter import mark_vision_provenance
from oracle.pack_validator import validate_pack


def test_mark_vision_provenance_records_overwritten_fields():
    requirement = {"id": "stmt-001", "shall_text": "old text"}

    mark_vision_provenance(requirement, ["shall_text", "justification"])

    assert requirement["field_provenance"] == {
        "shall_text": "vision_repaired",
        "justification": "vision_repaired",
    }


def test_mark_vision_provenance_accumulates_across_repairs():
    requirement = {"id": "stmt-001", "field_provenance": {"section": "vision_repaired"}}

    mark_vision_provenance(requirement, ["shall_text"])

    assert requirement["field_provenance"] == {
        "section": "vision_repaired",
        "shall_text": "vision_repaired",
    }


def test_gpcm_pack_with_field_provenance_validates():
    pack = {
        "schema_version": "gpcm_rulepack/v1",
        "rule_pack_id": "gpcm-test",
        "standard_id": "NASA-STD-TEST",
        "version": "1.0.0",
        "generated_at": "2026-06-09T00:00:00Z",
        "source_document": "test.pdf",
        "source_extract": "test_shall.json",
        "extraction_status": "complete",
        "total_requirements": 1,
        "oracle_metadata": {
            "name": "Test",
            "slug": "test",
            "description": "t",
            "status": "draft",
            "added_at": "2026-06-09T00:00:00Z",
        },
        "requirements": [
            {
                "id": "stmt-001",
                "shall_text": "The system shall do the thing.",
                "field_provenance": {"shall_text": "vision_repaired"},
            }
        ],
    }

    assert validate_pack(pack) == []


def test_gpcm_pack_with_invalid_provenance_value_fails_validation():
    pack = {
        "schema_version": "gpcm_rulepack/v1",
        "rule_pack_id": "gpcm-test",
        "standard_id": "NASA-STD-TEST",
        "version": "1.0.0",
        "generated_at": "2026-06-09T00:00:00Z",
        "source_document": "test.pdf",
        "source_extract": "test_shall.json",
        "extraction_status": "complete",
        "total_requirements": 1,
        "oracle_metadata": {
            "name": "Test",
            "slug": "test",
            "description": "t",
            "status": "draft",
            "added_at": "2026-06-09T00:00:00Z",
        },
        "requirements": [
            {
                "id": "stmt-001",
                "shall_text": "The system shall do the thing.",
                "field_provenance": {"shall_text": "hallucinated"},
            }
        ],
    }

    assert validate_pack(pack) != []
