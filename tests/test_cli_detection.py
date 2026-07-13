from pathlib import Path

import pytest

from oracle.cli import _detect_document_type


def test_detect_document_type_routes_sparse_nasa_amr_tags_as_tagged_standard(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "2021-04-21_nasa-std-6030-approveddocx.pdf"

    doc = fitz.open()
    for index in range(16):
        page = doc.new_page()
        text = "NASA-STD-6030\nAPPROVED FOR PUBLIC RELEASE"
        if index in {12, 14}:
            text += f"\n[AMR-{index}] Additive manufacturing records shall be retained."
        page.insert_text((72, 72), text)
    doc.save(pdf_path)
    doc.close()

    doc_type, confidence = _detect_document_type(
        Path(pdf_path),
        force_type=None,
        non_interactive=True,
    )

    assert doc_type == "tagged_standard"
    assert confidence >= 0.7


def test_force_type_records_detection_override_in_assembled_pack(tmp_path):
    """--force-type must be recorded in oracle_metadata.detection_override
    (Section 5.1 audit trail) so downstream consumers can see the bypass.
    """
    from datetime import datetime, timezone

    from oracle.cli import _assemble_generic_pack, _slugify

    # Minimal deduped rules and failure list
    rules = [
        {"statement_text": "The unit shall be inspected.", "obligation_keyword": "shall"}
    ]
    pdf = tmp_path / "regs.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")

    pack = _assemble_generic_pack(
        pdf_path=pdf,
        deduped_rules=rules,
        total_pages=3,
        extracted_pages=[1, 2, 3],
        chunk_failures=[],
        name="Forced CFR",
        use_vision=False,
        force_type="generic",
    )

    assert pack["oracle_metadata"]["detection_override"] == "generic"
    assert pack["extraction_method"] == "claude_text"
    assert pack["schema_version"] == "oracle_generic/v1"


def test_chunk_failures_structure_persisted_in_generic_pack(tmp_path):
    """Failed chunks must record the exact schema from Section 4.3/5.4:
    page_start, page_end, retries_used, final_error, extraction_mode.
    """
    from oracle.cli import _assemble_generic_pack

    rules = []
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(b"%PDF")

    failures = [
        {
            "page_start": 21,
            "page_end": 25,
            "retries_used": 2,
            "final_error": "JSON parse failure after markdown fence stripping and re-prompt",
            "extraction_mode": "vision",
        }
    ]

    pack = _assemble_generic_pack(
        pdf_path=pdf,
        deduped_rules=rules,
        total_pages=30,
        extracted_pages=[1, 2],
        chunk_failures=failures,
        name="Partial CFR",
        use_vision=True,
        force_type=None,
    )

    assert pack["extraction_status"] == "partial"
    assert pack["chunk_failures"] == failures
    assert pack["failed_page_ranges"] == ["21-25"]
    assert "21-25" in pack["failed_page_ranges"][0]
