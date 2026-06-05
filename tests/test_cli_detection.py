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
