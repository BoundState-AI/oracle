from oracle.gpcm_rulepack_adapter import (
    canonical_requirement_id,
    derive_shall_text,
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
    assert canonical_requirement_id(statement, "FCR 7") == "fcr-7"


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
