import sys
import tempfile
import types
import zipfile
from pathlib import Path

from oracle import cli


def _write_minimal_docx(path: Path, text: str) -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    with zipfile.ZipFile(path, "w") as docx_zip:
        docx_zip.writestr("[Content_Types].xml", content_types)
        docx_zip.writestr("_rels/.rels", rels)
        docx_zip.writestr("word/document.xml", document_xml)


def test_run_review_falls_back_to_builtin_docx_reader(monkeypatch):
    repo_tmp = Path(__file__).resolve().parents[1] / ".tmp_tests"
    repo_tmp.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(dir=repo_tmp) as temp_dir:
        tmp_path = Path(temp_dir)
        docx_path = tmp_path / "sample.docx"
        _write_minimal_docx(docx_path, "Fracture control shall be verified.")

        captured: dict[str, str] = {}

        def fake_pandoc(*args, **kwargs):
            raise FileNotFoundError("pandoc")

        def fake_oracle2_run_review(**kwargs):
            captured["draft"] = kwargs["draft"]
            return types.SimpleNamespace(session_id="session-123")

        fake_oracle2 = types.ModuleType("oracle.oracle2")
        fake_oracle2.run_review = fake_oracle2_run_review

        monkeypatch.setattr(cli.subprocess, "run", fake_pandoc)
        monkeypatch.setitem(sys.modules, "oracle.oracle2", fake_oracle2)

        session = cli.run_review(
            document_path=docx_path,
            pack_names=[],
            pack_dir=tmp_path,
            output_dir=tmp_path / "out",
        )

        assert session.session_id == "session-123"
        assert "Fracture control shall be verified." in captured["draft"]
