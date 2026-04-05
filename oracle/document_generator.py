"""
Module: document_generator
Purpose: Generate polished .docx and .pptx from oracle2 final_draft markdown.

Replaces the bare-minimum generation in server.py with professional formatting:
  - DOCX: Calibri fonts, styled headings, bullet lists, page numbers, margins, colors
  - PPTX: Multi-slide deck with title slide, section slides, proper typography

__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Markdown Parser — turns final_draft into structured blocks
# ---------------------------------------------------------------------------

class Block(NamedTuple):
    kind: str           # "h1", "h2", "h3", "paragraph", "bullet", "numbered", "code", "hr"
    text: str
    level: int          # heading level or bullet indent


def parse_markdown(md: str) -> list[Block]:
    """Parse markdown text into a flat list of typed blocks."""
    blocks: list[Block] = []
    lines = md.split("\n")
    i = 0
    code_buf: list[str] = []
    in_code = False

    while i < len(lines):
        line = lines[i]

        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code:
                blocks.append(Block("code", "\n".join(code_buf), 0))
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        stripped = line.strip()

        # Empty line
        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            blocks.append(Block("hr", "", 0))
            i += 1
            continue

        # Headings
        hm = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if hm:
            level = len(hm.group(1))
            kind = f"h{min(level, 3)}"
            blocks.append(Block(kind, hm.group(2).strip(), level))
            i += 1
            continue

        # Bullet list
        bm = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if bm:
            indent = len(bm.group(1)) // 2
            blocks.append(Block("bullet", bm.group(2).strip(), indent))
            i += 1
            continue

        # Numbered list
        nm = re.match(r"^(\s*)\d+[.)]\s+(.*)", line)
        if nm:
            indent = len(nm.group(1)) // 2
            blocks.append(Block("numbered", nm.group(2).strip(), indent))
            i += 1
            continue

        # Regular paragraph — collect continuation lines
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line:
                break
            if re.match(r"^#{1,6}\s+", next_line):
                break
            if re.match(r"^[-*+]\s+", next_line):
                break
            if re.match(r"^\d+[.)]\s+", next_line):
                break
            if re.match(r"^[-*_]{3,}\s*$", next_line):
                break
            if next_line.startswith("```"):
                break
            para_lines.append(next_line)
            i += 1
        blocks.append(Block("paragraph", " ".join(para_lines), 0))

    return blocks


def _strip_md_inline(text: str) -> str:
    """Remove markdown bold/italic markers for plain-text contexts."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Color Palette
# ---------------------------------------------------------------------------

# BoundState brand-adjacent: dark navy + teal accent
PRIMARY = "1B2A4A"      # Dark navy
ACCENT = "0891B2"       # Teal
LIGHT_BG = "F0F7FA"     # Ice blue for table headers / callouts
TEXT_DARK = "1F2937"     # Near-black body text
TEXT_MED = "4B5563"      # Medium gray for captions
BORDER = "CBD5E1"        # Light border


# ---------------------------------------------------------------------------
# DOCX Generator
# ---------------------------------------------------------------------------

def generate_docx(
    final_draft: str,
    output_path: Path,
    title: str = "Oracle Review — Final Document",
    subtitle: str | None = None,
) -> Path:
    """Generate a polished .docx from markdown final_draft.

    Features:
      - US Letter, 1" margins
      - Calibri font family
      - Styled headings (navy, bold, spaced)
      - Proper bullet and numbered lists
      - Page numbers in footer
      - Title page section
    """
    from docx import Document
    from docx.shared import Pt, Inches, Cm, RGBColor, Emu
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn

    doc = Document()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Page setup ---
    for section in doc.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # --- Default style ---
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)
    font.color.rgb = RGBColor.from_string(TEXT_DARK)
    pf = style.paragraph_format
    pf.space_after = Pt(6)
    pf.space_before = Pt(0)
    pf.line_spacing = 1.15

    # --- Heading styles ---
    _style_heading(doc, "Heading 1", size=20, color=PRIMARY, space_before=18, space_after=8, bold=True)
    _style_heading(doc, "Heading 2", size=15, color=ACCENT, space_before=14, space_after=6, bold=True)
    _style_heading(doc, "Heading 3", size=12, color=TEXT_DARK, space_before=10, space_after=4, bold=True)

    # --- List styles (use built-in List Bullet / List Number) ---
    for sname in ("List Bullet", "List Bullet 2", "List Bullet 3"):
        if sname in doc.styles:
            ls = doc.styles[sname]
            ls.font.name = "Calibri"
            ls.font.size = Pt(11)
            ls.font.color.rgb = RGBColor.from_string(TEXT_DARK)

    for sname in ("List Number", "List Number 2", "List Number 3"):
        if sname in doc.styles:
            ls = doc.styles[sname]
            ls.font.name = "Calibri"
            ls.font.size = Pt(11)
            ls.font.color.rgb = RGBColor.from_string(TEXT_DARK)

    # --- Page numbers in footer ---
    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fp.style = doc.styles["Normal"]
        _add_page_number(fp)
        if fp.runs:
            fp.runs[0].font.size = Pt(9)
            fp.runs[0].font.color.rgb = RGBColor.from_string(TEXT_MED)

    # --- Title block ---
    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    tp.paragraph_format.space_before = Pt(72)
    tp.paragraph_format.space_after = Pt(4)
    run = tp.add_run(title)
    run.bold = True
    run.font.size = Pt(26)
    run.font.color.rgb = RGBColor.from_string(PRIMARY)
    run.font.name = "Calibri"

    if subtitle:
        sp = doc.add_paragraph()
        sp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        sp.paragraph_format.space_after = Pt(2)
        sr = sp.add_run(subtitle)
        sr.font.size = Pt(13)
        sr.font.color.rgb = RGBColor.from_string(ACCENT)
        sr.font.name = "Calibri"

    # Divider line
    divider = doc.add_paragraph()
    divider.paragraph_format.space_before = Pt(8)
    divider.paragraph_format.space_after = Pt(24)
    _add_bottom_border(divider, ACCENT)

    # --- Body content ---
    blocks = parse_markdown(final_draft)

    for block in blocks:
        if block.kind == "h1":
            p = doc.add_heading(_strip_md_inline(block.text), level=1)
        elif block.kind == "h2":
            p = doc.add_heading(_strip_md_inline(block.text), level=2)
        elif block.kind == "h3":
            p = doc.add_heading(_strip_md_inline(block.text), level=3)
        elif block.kind == "paragraph":
            p = doc.add_paragraph()
            _add_rich_runs(p, block.text)
        elif block.kind == "bullet":
            style_name = "List Bullet" if block.level == 0 else f"List Bullet {min(block.level + 1, 3)}"
            if style_name in doc.styles:
                p = doc.add_paragraph(style=style_name)
            else:
                p = doc.add_paragraph(style="List Bullet")
            _add_rich_runs(p, block.text)
        elif block.kind == "numbered":
            style_name = "List Number" if block.level == 0 else f"List Number {min(block.level + 1, 3)}"
            if style_name in doc.styles:
                p = doc.add_paragraph(style=style_name)
            else:
                p = doc.add_paragraph(style="List Number")
            _add_rich_runs(p, block.text)
        elif block.kind == "code":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(block.text)
            run.font.name = "Consolas"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor.from_string(TEXT_DARK)
            _shade_paragraph(p, "F1F5F9")
        elif block.kind == "hr":
            hr = doc.add_paragraph()
            hr.paragraph_format.space_before = Pt(8)
            hr.paragraph_format.space_after = Pt(8)
            _add_bottom_border(hr, BORDER)

    # --- BoundState footer line ---
    doc.add_paragraph()  # spacer
    fp = doc.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = fp.add_run("Generated by ORACLE \u2014 BoundState AI")
    fr.font.size = Pt(8)
    fr.font.color.rgb = RGBColor.from_string(TEXT_MED)
    fr.font.name = "Calibri"
    fr.italic = True

    doc.save(str(output_path))
    return output_path


def _style_heading(doc, style_name: str, size: int, color: str,
                   space_before: int, space_after: int, bold: bool = True):
    """Configure a built-in heading style."""
    from docx.shared import Pt, RGBColor
    style = doc.styles[style_name]
    style.font.name = "Calibri"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor.from_string(color)
    style.paragraph_format.space_before = Pt(space_before)
    style.paragraph_format.space_after = Pt(space_after)
    style.paragraph_format.keep_with_next = True


def _add_rich_runs(paragraph, text: str):
    """Add runs with bold/italic/code support from markdown inline formatting."""
    from docx.shared import Pt, RGBColor

    parts = re.split(r"(\*\*.+?\*\*|__.+?__|`.+?`|\*.+?\*|_.+?_)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("__") and part.endswith("__"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor.from_string("B91C1C")
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        elif part.startswith("_") and part.endswith("_"):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            paragraph.add_run(part)


def _add_page_number(paragraph):
    """Add auto page number field to a paragraph."""
    from docx.oxml.ns import qn
    run = paragraph.add_run()
    fld_char_begin = run._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "begin"})
    run._element.append(fld_char_begin)

    run2 = paragraph.add_run()
    instr = run2._element.makeelement(qn("w:instrText"), {})
    instr.text = " PAGE "
    run2._element.append(instr)

    run3 = paragraph.add_run()
    fld_char_end = run3._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "end"})
    run3._element.append(fld_char_end)


def _add_bottom_border(paragraph, color: str):
    """Add a bottom border to a paragraph (acts as a horizontal rule)."""
    from docx.oxml.ns import qn
    pPr = paragraph._element.get_or_add_pPr()
    pBdr = pPr.makeelement(qn("w:pBdr"), {})
    bottom = pBdr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single",
        qn("w:sz"): "6",
        qn("w:space"): "1",
        qn("w:color"): color,
    })
    pBdr.append(bottom)
    pPr.append(pBdr)


def _shade_paragraph(paragraph, color: str):
    """Apply background shading to a paragraph."""
    from docx.oxml.ns import qn
    pPr = paragraph._element.get_or_add_pPr()
    shd = pPr.makeelement(qn("w:shd"), {
        qn("w:val"): "clear",
        qn("w:color"): "auto",
        qn("w:fill"): color,
    })
    pPr.append(shd)


# ---------------------------------------------------------------------------
# PPTX Generator
# ---------------------------------------------------------------------------

def generate_pptx(
    final_draft: str,
    output_path: Path,
    title: str = "Oracle Review \u2014 Final Document",
    subtitle: str | None = None,
) -> Path:
    """Generate a polished multi-slide .pptx from markdown final_draft.

    Features:
      - Title slide with branding
      - One slide per H1/H2 section
      - Proper typography (Calibri family)
      - Dark title/conclusion slides, light content slides
      - Content broken across slides (not crammed onto one)
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

    prs = Presentation()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    blocks = parse_markdown(final_draft)

    # --- Group blocks into sections ---
    sections: list[dict] = []
    current: dict | None = None

    for block in blocks:
        if block.kind in ("h1", "h2"):
            if current:
                sections.append(current)
            current = {"title": _strip_md_inline(block.text), "level": block.kind, "blocks": []}
        else:
            if current is None:
                current = {"title": title, "level": "h1", "blocks": []}
            current["blocks"].append(block)

    if current:
        sections.append(current)

    if not sections:
        sections = [{"title": title, "level": "h1", "blocks": blocks}]

    # --- Title slide (dark) ---
    _add_title_slide(prs, title, subtitle or "Reviewed by ORACLE \u2014 BoundState AI")

    # --- Content slides ---
    for sec in sections:
        content_lines = _blocks_to_slide_text(sec["blocks"])
        if not content_lines:
            continue

        # Split into chunks of ~8 bullets per slide
        chunks = _chunk_lines(content_lines, max_lines=8)
        for ci, chunk in enumerate(chunks):
            slide_title = sec["title"]
            if len(chunks) > 1:
                slide_title += f" ({ci + 1}/{len(chunks)})"
            _add_content_slide(prs, slide_title, chunk)

    # --- Closing slide (dark) ---
    _add_closing_slide(prs)

    prs.save(str(output_path))
    return output_path


def _add_title_slide(prs, title: str, subtitle: str):
    """Add a dark-background title slide."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _fill_slide_bg(slide, PRIMARY)

    # Title
    txBox = slide.shapes.add_textbox(Inches(1.2), Inches(2.2), Inches(10.9), Inches(1.8))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(40)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    p.font.name = "Calibri"
    p.alignment = PP_ALIGN.LEFT

    # Subtitle
    txBox2 = slide.shapes.add_textbox(Inches(1.2), Inches(4.2), Inches(10.9), Inches(0.8))
    tf2 = txBox2.text_frame
    tf2.word_wrap = True
    p2 = tf2.paragraphs[0]
    p2.text = subtitle
    p2.font.size = Pt(18)
    p2.font.color.rgb = RGBColor.from_string(ACCENT)
    p2.font.name = "Calibri"
    p2.alignment = PP_ALIGN.LEFT

    # Accent line
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE.RECTANGLE
        Inches(1.2), Inches(4.0), Inches(3), Pt(3)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(ACCENT)
    shape.line.fill.background()


def _add_content_slide(prs, title: str, lines: list[str]):
    """Add a light-background content slide."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _fill_slide_bg(slide, "FFFFFF")

    # Title bar background
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.333), Inches(1.1))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor.from_string(LIGHT_BG)
    bar.line.fill.background()

    # Title text
    txBox = slide.shapes.add_textbox(Inches(0.8), Inches(0.2), Inches(11.7), Inches(0.7))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(26)
    p.font.bold = True
    p.font.color.rgb = RGBColor.from_string(PRIMARY)
    p.font.name = "Calibri"

    # Content
    txBox2 = slide.shapes.add_textbox(Inches(0.8), Inches(1.4), Inches(11.7), Inches(5.5))
    tf2 = txBox2.text_frame
    tf2.word_wrap = True

    for i, line in enumerate(lines):
        if i == 0:
            p = tf2.paragraphs[0]
        else:
            p = tf2.add_paragraph()

        # Detect bullet prefix
        clean = line
        is_bullet = False
        if line.startswith("\u2022 ") or line.startswith("- "):
            clean = line[2:]
            is_bullet = True
            p.level = 0

        # Bold detection for "Label: value" patterns
        bold_match = re.match(r"^(.+?):\s*(.+)$", clean)
        if bold_match and len(bold_match.group(1)) < 60:
            run1 = p.add_run()
            run1.text = ("\u2022 " if is_bullet else "") + bold_match.group(1) + ": "
            run1.font.bold = True
            run1.font.size = Pt(14)
            run1.font.color.rgb = RGBColor.from_string(TEXT_DARK)
            run1.font.name = "Calibri"

            run2 = p.add_run()
            run2.text = bold_match.group(2)
            run2.font.size = Pt(14)
            run2.font.color.rgb = RGBColor.from_string(TEXT_DARK)
            run2.font.name = "Calibri"
        else:
            prefix = "\u2022 " if is_bullet else ""
            p.text = prefix + clean
            p.font.size = Pt(14)
            p.font.color.rgb = RGBColor.from_string(TEXT_DARK)
            p.font.name = "Calibri"

        p.space_after = Pt(6)
        p.space_before = Pt(2)

    # Footer
    footer_box = slide.shapes.add_textbox(Inches(0.8), Inches(7.0), Inches(4), Inches(0.3))
    ftf = footer_box.text_frame
    fp = ftf.paragraphs[0]
    fp.text = "ORACLE \u2014 BoundState AI"
    fp.font.size = Pt(8)
    fp.font.color.rgb = RGBColor.from_string(TEXT_MED)
    fp.font.name = "Calibri"
    fp.font.italic = True


def _add_closing_slide(prs):
    """Add a dark closing/thank-you slide."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _fill_slide_bg(slide, PRIMARY)

    txBox = slide.shapes.add_textbox(Inches(1.2), Inches(2.8), Inches(10.9), Inches(1.2))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = "Review Complete"
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    p.font.name = "Calibri"
    p.alignment = PP_ALIGN.LEFT

    txBox2 = slide.shapes.add_textbox(Inches(1.2), Inches(4.2), Inches(10.9), Inches(0.6))
    tf2 = txBox2.text_frame
    p2 = tf2.paragraphs[0]
    p2.text = "Generated by ORACLE \u2022 BoundState AI"
    p2.font.size = Pt(16)
    p2.font.color.rgb = RGBColor.from_string(ACCENT)
    p2.font.name = "Calibri"
    p2.alignment = PP_ALIGN.LEFT


def _fill_slide_bg(slide, color_hex: str):
    """Fill slide background with a solid color."""
    from pptx.dml.color import RGBColor
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(color_hex)


def _blocks_to_slide_text(blocks: list[Block]) -> list[str]:
    """Convert blocks into simple text lines for slide content."""
    lines: list[str] = []
    for b in blocks:
        if b.kind == "paragraph":
            text = _strip_md_inline(b.text)
            if text:
                lines.append(text)
        elif b.kind == "bullet":
            lines.append(f"\u2022 {_strip_md_inline(b.text)}")
        elif b.kind == "numbered":
            lines.append(f"\u2022 {_strip_md_inline(b.text)}")
        elif b.kind == "h3":
            lines.append(_strip_md_inline(b.text))
        elif b.kind == "code":
            snippet = b.text[:200]
            if len(b.text) > 200:
                snippet += "..."
            lines.append(snippet)
    return lines


def _chunk_lines(lines: list[str], max_lines: int = 8) -> list[list[str]]:
    """Split lines into chunks that fit on one slide."""
    if not lines:
        return []
    chunks = []
    for i in range(0, len(lines), max_lines):
        chunks.append(lines[i:i + max_lines])
    return chunks
