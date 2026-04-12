"""Tests for shall extractor block parsing — MPR/NER tag extraction, section detection, and rationale splitting."""
from oracle.shall_extractor import (
    _clean_tagged_requirement_text,
    _detect_current_section,
    _extract_mpr_blocks,
    _split_inline_rationale,
)


def test_extract_mpr_block_keeps_multi_paragraph_subitem_text():
    text = """
4.2.4.6 Welding Requirements
[MPR 58] a.

When drilling, grinding, reaming, or machining is performed on high-strength steels
that can form martensite, a validated process for machining shall be used.

This requirement continues across the paragraph break.

[MPR 59] Components shall be inspected after machining.
""".strip()

    blocks = _extract_mpr_blocks(text, page=23)

    assert len(blocks) == 2
    assert blocks[0]["mpr_id"] == "MPR 58"
    assert "validated process for machining shall be used" in blocks[0]["text"]
    assert "This requirement continues across the paragraph break" in blocks[0]["text"]


def test_extract_mpr_block_stops_at_next_section_header():
    text = """
[MPR 168] The system shall preserve the current section assignment.

4.2.4.9a(1) Materials Control Requirements
Intro text for the next section.
""".strip()

    blocks = _extract_mpr_blocks(text, page=58)

    assert len(blocks) == 1
    assert blocks[0]["text"] == "The system shall preserve the current section assignment"


def test_extract_mpr_blocks_supports_ner_tags():
    text = """
4.1 Fracture Control
[NER 12] Fracture-critical hardware shall be inspected before flight.

[NER 13] Records shall be retained.
""".strip()

    blocks = _extract_mpr_blocks(text, page=12)

    assert len(blocks) == 2
    assert blocks[0]["mpr_id"] == "NER 12"
    assert blocks[0]["text"] == "Fracture-critical hardware shall be inspected before flight"


def test_extract_mpr_block_drops_next_subitem_marker():
    text = """
4.1.4.1.1 Eddy Current
c. [NER 8] Noise levels on the component shall be less than 25% of the reference notch response.

d. [NER 9] Any indication greater than 50% of the reference notch response shall be reported.
""".strip()

    blocks = _extract_mpr_blocks(text, page=19)

    assert blocks[0]["text"] == "Noise levels on the component shall be less than 25% of the reference notch response"


def test_detect_current_section_handles_split_heading_lines():
    text = """
4.1.4.2
Fluorescent Penetrant

[NER 11] Fluorescent penetrant inspection shall be performed.
""".strip()

    tag_pos = text.index("[NER 11]")
    assert _detect_current_section(text, tag_pos) == "4.1.4.2"


def test_detect_current_section_handles_inline_tagged_section_line():
    text = """
4.1.4.1.2 [NER 10] The influence of coatings shall be evaluated.
""".strip()

    tag_pos = text.index("[NER 10]")
    assert _detect_current_section(text, tag_pos) == "4.1.4.1.2"


def test_detect_current_section_uses_carried_section_when_page_starts_with_subitem():
    text = """
c. [NER 18] If etching is not feasible, it shall be demonstrated.
""".strip()

    tag_pos = text.index("[NER 18]")
    assert _detect_current_section(text, tag_pos, "4.1.4.2.3") == "4.1.4.2.3"


def test_detect_current_section_prefers_nearest_prior_heading():
    text = """
4.1.4.1.2 [NER 10] Prior tagged requirement shall be evaluated.
4.1.4.2.3 Etching/Electropolishing Procedure
b. [NER 15] The procedure shall specify removal depth.
""".strip()

    tag_pos = text.index("[NER 15]")
    assert _detect_current_section(text, tag_pos) == "4.1.4.2.3"


def test_extract_mpr_block_stops_before_standalone_section_number_and_title():
    text = """
4.1.4.1.2 [NER 10] The influence of coatings shall be evaluated.
4.1.4.2
Fluorescent Penetrant

[NER 11] Penetrant inspection shall be in accordance with the standard.
""".strip()

    blocks = _extract_mpr_blocks(text, page=19)

    assert blocks[0]["text"] == "The influence of coatings shall be evaluated"


def test_clean_tagged_requirement_text_strips_trailing_section_number():
    text = "Any indication shall be reported. 4.1.4.1.2"
    assert _clean_tagged_requirement_text(text) == "Any indication shall be reported"


def test_split_inline_rationale_extracts_rationale_tail():
    lead, rationale = _split_inline_rationale(
        "Any discontinuity shall be reported. Rationale: Reporting supports 90/95 confidence."
    )

    assert lead == "Any discontinuity shall be reported."
    assert rationale == "Reporting supports 90/95 confidence."
