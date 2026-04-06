from oracle.shall_extractor import _extract_mpr_blocks


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
