"""Tests for GPCM rule pack adapter — dedup, shall derivation, ID normalization, and section pattern matching."""
from oracle.gpcm_rulepack_adapter import (
    canonical_requirement_id,
    clean_justification,
    dedupe_requirements,
    derive_shall_text,
    extract_tag,
    infer_standard_id,
    normalize_source_tag,
    page_window_for_tag,
    strip_leading_tag,
    vision_repair_reasons,
)
from oracle.shall_extractor import SECTION_PATTERN


def test_derive_shall_text_prefers_richer_block_text():
    block = "[MPR 19] e. Process specifications for spaceflight hardware shall define repeatable process steps."
    statement = "e"

    assert (
        derive_shall_text(block, statement, "")
        == "Process specifications for spaceflight hardware shall define repeatable process steps."
    )


def test_canonical_requirement_id_uses_tag_identity():
    statement = {"id": 224, "mpr_id": "MPR 3"}
    assert canonical_requirement_id(statement, "MPR 3") == "3"
    assert canonical_requirement_id(statement, "NER 12") == "12"
    assert canonical_requirement_id(statement, "FCR 7") == "fcr-7"
    assert canonical_requirement_id(statement, "AMR-22") == "amr-22"


def test_amr_tag_normalization_accepts_hyphenated_source_tags():
    text = "[AMR-22] Engineering drawings shall specify additive manufacturing build orientation."

    assert extract_tag(text) == "AMR 22"
    assert normalize_source_tag("AMR-22") == "AMR 22"
    assert strip_leading_tag(text) == (
        "Engineering drawings shall specify additive manufacturing build orientation."
    )


def test_page_window_for_tag_finds_hyphenated_amr_tag():
    page_text = "\n".join(
        [
            "4.2 Additive Manufacturing",
            "[AMR-22] Engineering drawings shall specify build orientation.",
            "Records shall identify the machine serial number.",
        ]
    )

    window = page_window_for_tag(page_text, "AMR 22", before=1, after=3)

    assert "4.2 Additive Manufacturing" in window
    assert "[AMR-22]" in window


def test_infer_standard_id_accepts_unrevised_nasa_standard_names(tmp_path):
    pdf = tmp_path / "2021-04-21_nasa-std-6030-approveddocx.pdf"
    extractor_json = tmp_path / "2021-04-21_nasa-std-6030-approveddocx_shall_statements.json"

    assert infer_standard_id(pdf, extractor_json) == "NASA-STD-6030"


def test_dedupe_requirements_strips_tag_prefix_from_key():
    requirements = [
        {
            "id": "12",
            "source_tag": "NER 12",
            "section": "4.1",
            "shall_text": "[NER 12] Programs shall verify fracture-critical parts.",
            "justification": "",
            "applies_to": ["all_programs"],
        },
        {
            "id": "99",
            "source_tag": None,
            "section": "Appendix A",
            "shall_text": "Programs shall verify fracture-critical parts.",
            "justification": "Matrix repeat",
            "applies_to": ["all_programs"],
        },
    ]

    deduped = dedupe_requirements(requirements)

    assert len(deduped) == 1
    assert deduped[0]["shall_text"] == "Programs shall verify fracture-critical parts."


def test_clean_justification_drops_punctuation_only_tail():
    assert clean_justification(".") == ""


def test_vision_repair_reasons_flags_single_letter_capture():
    requirement = {
        "shall_text": "e",
        "justification": "",
    }

    reasons = vision_repair_reasons(requirement)
    assert "too_short_or_missing_obligation" in reasons


def test_section_pattern_handles_parenthetical_nested_section():
    text = "\n4.2.4.9a(1) Materials Control Requirements"
    match = SECTION_PATTERN.search(text)
    assert match is not None
    assert match.group(1) == "4.2.4.9a(1)"
