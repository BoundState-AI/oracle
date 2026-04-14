"""
Module: document_generator
Purpose: Generate polished .docx and .pptx from oracle2 ReviewResult.

Matches Beth's output style:
  - Centered title block (company name, doc title, tagline)
  - Multi-colored metrics summary line
  - Navy heading hierarchy (#1F3864 / #2E4D8B) with outline levels for Navigation Pane
  - Body text in #333333, callouts in amber/red
  - List Paragraph style for bullets
  - Centered italic footer with confidentiality notice
  - PPTX: Dark title/closing slides, light content slides, multi-slide chunking

__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple, TYPE_CHECKING

if TYPE_CHECKING:
    from oracle.oracle2_adapter import ReviewResult

# ---------------------------------------------------------------------------
# Color palette — matches Beth's docx output
# ---------------------------------------------------------------------------

NAVY_DARK = "1F3864"     # H1, title, stat labels
NAVY_MED = "2E4D8B"      # H2, H3, document subtitle
GRAY_DARK = "333333"     # Body text
GRAY_MED = "444444"      # Tagline, notes, sub-headers
GRAY_LIGHT = "888888"    # Separators (pipes in stats line)
BLACK = "000000"          # Some body text
RED = "C00000"            # Critical findings
AMBER = "7F4D00"         # High findings, warnings
GREEN = "375623"          # Good/resolved items


# ---------------------------------------------------------------------------
# Markdown Parser
# ---------------------------------------------------------------------------

class Block(NamedTuple):
    kind: str       # "h1","h2","h3","paragraph","bullet","numbered","code","hr","table"
    text: str
    level: int
    # WHY: Only populated for kind=="table". Stored as list-of-rows so the
    # renderer can emit a real Word table instead of the raw pipe text that
    # previously collapsed into a single paragraph.
    rows: list[list[str]] | None = None


# WHY: GitHub-Flavored Markdown pipe-table delimiter row. Each column is
# a run of dashes with optional leading/trailing colons (alignment hints),
# segments separated by '|'. Optional leading/trailing '|' on the line.
_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")


def _split_table_row(line: str) -> list[str]:
    """Split a pipe-delimited row into trimmed cells.

    Strips the optional edge pipes (`| a | b |` -> `['a','b']`) so callers
    don't have to worry about empty leading/trailing cells.
    """
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse_markdown(md: str) -> list[Block]:
    """Parse markdown into typed blocks."""
    blocks: list[Block] = []
    lines = md.split("\n")
    i = 0
    code_buf: list[str] = []
    in_code = False

    while i < len(lines):
        line = lines[i]

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

        if not stripped:
            i += 1
            continue

        # WHY: 3+ repetitions of -, *, or _ denote a horizontal rule in
        # standard Markdown (CommonMark spec, thematic break).
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            blocks.append(Block("hr", "", 0))
            i += 1
            continue

        # WHY: ATX-style headings — 1-6 leading '#' chars followed by space.
        # We cap at h3 for docx outline depth.
        hm = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if hm:
            level = len(hm.group(1))
            kind = f"h{min(level, 3)}"
            blocks.append(Block(kind, hm.group(2).strip(), level))
            i += 1
            continue

        # WHY: Unordered list — leading whitespace sets nesting depth (2-space
        # indentation per level), marker is -, *, or +.
        bm = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if bm:
            indent = len(bm.group(1)) // 2
            blocks.append(Block("bullet", bm.group(2).strip(), indent))
            i += 1
            continue

        # WHY: Ordered list — digits followed by . or ) then space.
        # Leading whitespace sets nesting depth, same 2-space convention.
        nm = re.match(r"^(\s*)\d+[.)]\s+(.*)", line)
        if nm:
            indent = len(nm.group(1)) // 2
            blocks.append(Block("numbered", nm.group(2).strip(), indent))
            i += 1
            continue

        # WHY: GFM pipe table — a header line containing '|' followed by a
        # delimiter row of dashes. Detected BEFORE the paragraph fallback
        # because otherwise the continuation loop joins header/delimiter/
        # data rows into one long "Normal" paragraph with raw pipes (the
        # bug this branch exists to fix).
        if "|" in stripped and i + 1 < len(lines) and _TABLE_DELIM_RE.match(lines[i + 1]):
            table_rows: list[list[str]] = [_split_table_row(line)]
            i += 2  # skip header + delimiter
            while i < len(lines):
                nl = lines[i]
                ns = nl.strip()
                if not ns or "|" not in ns:
                    break
                # Stop on a different block-level element.
                if re.match(r"^#{1,6}\s+", ns) or ns.startswith("```"):
                    break
                if re.match(r"^[-*_]{3,}\s*$", ns):
                    break
                table_rows.append(_split_table_row(nl))
                i += 1
            blocks.append(Block("table", "", 0, rows=table_rows))
            continue

        # Regular paragraph — collect continuation lines
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            nl = lines[i].strip()
            if not nl or re.match(r"^#{1,6}\s+", nl) or re.match(r"^[-*+]\s+", nl):
                break
            if re.match(r"^\d+[.)]\s+", nl) or re.match(r"^[-*_]{3,}\s*$", nl):
                break
            if nl.startswith("```"):
                break
            # Don't swallow a table that happens to follow a paragraph with
            # no blank line between them.
            if "|" in nl and i + 1 < len(lines) and _TABLE_DELIM_RE.match(lines[i + 1]):
                break
            para_lines.append(nl)
            i += 1
        blocks.append(Block("paragraph", " ".join(para_lines), 0))

    return blocks


def _strip_md(text: str) -> str:
    """Remove markdown inline formatting."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


# ---------------------------------------------------------------------------
# DOCX: XML helpers
# ---------------------------------------------------------------------------

def _set_outline_level(style, level: int):
    """Set outlineLevel on a heading style for Navigation Pane support."""
    from docx.oxml.ns import qn
    pPr = style.element.get_or_add_pPr()
    existing = pPr.find(qn("w:outlineLvl"))
    if existing is not None:
        existing.set(qn("w:val"), str(level))
    else:
        outline = pPr.makeelement(qn("w:outlineLvl"), {qn("w:val"): str(level)})
        pPr.append(outline)


def _add_page_number(paragraph):
    """Add auto page number field to a paragraph."""
    from docx.oxml.ns import qn
    run = paragraph.add_run()
    fld_begin = run._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "begin"})
    run._element.append(fld_begin)

    run2 = paragraph.add_run()
    instr = run2._element.makeelement(qn("w:instrText"), {})
    instr.text = " PAGE "
    run2._element.append(instr)

    run3 = paragraph.add_run()
    fld_end = run3._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "end"})
    run3._element.append(fld_end)


def _shade_paragraph(paragraph, color: str):
    """Apply background shading to a paragraph."""
    from docx.oxml.ns import qn
    pPr = paragraph._element.get_or_add_pPr()
    shd = pPr.makeelement(qn("w:shd"), {
        qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): color,
    })
    pPr.append(shd)


def _shade_cell(cell, color: str):
    """Apply background shading to a table cell.

    WHY: Paragraph-level shading only tints the text line; to fill the
    whole header cell with navy we have to write to the cell's tcPr.
    """
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.makeelement(qn("w:shd"), {
        qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): color,
    })
    tcPr.append(shd)


# ---------------------------------------------------------------------------
# DOCX: Rich text rendering
# ---------------------------------------------------------------------------

def _add_rich_runs(paragraph, text: str, default_color: str = BLACK):
    """Add runs with bold/italic/code from markdown inline formatting."""
    from docx.shared import Pt, RGBColor

    parts = re.split(r"(\*\*.+?\*\*|__.+?__|`.+?`|\*.+?\*|_.+?_)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
            run.font.color.rgb = RGBColor.from_string(default_color)
        elif part.startswith("__") and part.endswith("__"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
            run.font.color.rgb = RGBColor.from_string(default_color)
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor.from_string(NAVY_MED)
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
            run.font.color.rgb = RGBColor.from_string(default_color)
        elif part.startswith("_") and part.endswith("_"):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
            run.font.color.rgb = RGBColor.from_string(default_color)
        else:
            run = paragraph.add_run(part)
            run.font.color.rgb = RGBColor.from_string(default_color)


def _detect_callout(text: str) -> str | None:
    """Detect if a paragraph is a callout/note by its opening words.

    Returns color hex if it is, None otherwise.
    """
    lower = text.lower()
    if lower.startswith("critical:") or lower.startswith("critical finding"):
        return RED
    if lower.startswith("warning:") or lower.startswith("note:"):
        return AMBER
    if lower.startswith("important:"):
        return AMBER
    return None


# ---------------------------------------------------------------------------
# DOCX: Table rendering
# ---------------------------------------------------------------------------

def _render_docx_table(doc, rows: list[list[str]]):
    """Render a GFM table as a Word table with a navy header row.

    WHY: python-docx's built-in "Table Grid" style gives us visible cell
    borders without constructing OOXML by hand. The header gets navy
    shading + bold white text so readers see structure at a glance; body
    cells go through _add_rich_runs so inline **bold**, *italic*, and
    `code` formatting inside cells is preserved.

    Rows are normalized to the widest row's width so python-docx doesn't
    raise on ragged tables (which the model occasionally emits).
    """
    from docx.shared import Pt, RGBColor

    if not rows:
        return

    n_cols = max(len(r) for r in rows)
    norm = [r + [""] * (n_cols - len(r)) for r in rows]

    table = doc.add_table(rows=len(norm), cols=n_cols)
    if "Table Grid" in doc.styles:
        table.style = doc.styles["Table Grid"]

    for r_idx, row in enumerate(norm):
        for c_idx, cell_text in enumerate(row):
            cell = table.rows[r_idx].cells[c_idx]
            para = cell.paragraphs[0]
            # Clear the default empty run python-docx inserts so we can
            # write styled runs into a pristine paragraph.
            para.text = ""

            if r_idx == 0:
                _shade_cell(cell, NAVY_DARK)
                run = para.add_run(_strip_md(cell_text))
                run.bold = True
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor.from_string("FFFFFF")
            else:
                _add_rich_runs(para, cell_text, default_color=GRAY_DARK)
                for run in para.runs:
                    run.font.size = Pt(10)


# ---------------------------------------------------------------------------
# DOCX Generator
# ---------------------------------------------------------------------------

def generate_docx(
    final_draft: str,
    output_path: Path,
    title: str = "Oracle Review",
    subtitle: str | None = None,
    review_result: "ReviewResult | None" = None,
) -> Path:
    """Generate a polished .docx matching Beth's output style.

    Features:
      - Centered title block with BoundState branding
      - Metrics summary with multi-colored runs (if review_result provided)
      - Heading 1/2/3 with outline levels → Word Navigation Pane
      - List Paragraph for bullets
      - Callout detection (Critical/Warning → colored bold)
      - Page numbers in footer
      - Confidentiality footer
    """
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    doc = Document()

    # --- Page setup: US Letter, 1" margins ---
    for section in doc.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # --- Heading styles with outline levels ---
    h1 = doc.styles["Heading 1"]
    h1.font.size = Pt(14)
    h1.font.bold = True
    h1.font.color.rgb = RGBColor.from_string(NAVY_DARK)
    h1.paragraph_format.space_before = Pt(18)
    h1.paragraph_format.space_after = Pt(6)
    h1.paragraph_format.keep_with_next = True
    _set_outline_level(h1, 0)

    h2 = doc.styles["Heading 2"]
    h2.font.size = Pt(12)
    h2.font.bold = True
    h2.font.color.rgb = RGBColor.from_string(NAVY_MED)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(5)
    h2.paragraph_format.keep_with_next = True
    _set_outline_level(h2, 1)

    if "Heading 3" in doc.styles:
        h3s = doc.styles["Heading 3"]
        h3s.font.bold = True
        h3s.font.color.rgb = RGBColor.from_string(NAVY_MED)
        h3s.paragraph_format.space_before = Pt(9)
        h3s.paragraph_format.space_after = Pt(4)
        h3s.paragraph_format.keep_with_next = True
        _set_outline_level(h3s, 2)

    # --- Page numbers in footer ---
    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_page_number(fp)
        for r in fp.runs:
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor.from_string(GRAY_MED)

    # ===================================================================
    # TITLE BLOCK (centered, matching Beth's style)
    # ===================================================================

    # Company name — 16pt bold navy, centered
    p_co = doc.add_paragraph()
    p_co.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_co.paragraph_format.space_after = Pt(3)
    r_co = p_co.add_run("BoundState AI LLC")
    r_co.bold = True
    r_co.font.size = Pt(16)
    r_co.font.color.rgb = RGBColor.from_string(NAVY_DARK)

    # Document title — 13pt bold medium navy, centered
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.space_after = Pt(3)
    r_title = p_title.add_run(title)
    r_title.bold = True
    r_title.font.size = Pt(13)
    r_title.font.color.rgb = RGBColor.from_string(NAVY_MED)

    # Subtitle / tagline — italic gray, centered
    if subtitle:
        p_sub = doc.add_paragraph()
        p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_sub.paragraph_format.space_after = Pt(12)
        r_sub = p_sub.add_run(subtitle)
        r_sub.italic = True
        r_sub.font.color.rgb = RGBColor.from_string(GRAY_MED)

    # Spacers (matches Beth's empty paragraph spacing)
    for _ in range(2):
        sp = doc.add_paragraph()
        sp.paragraph_format.space_after = Pt(0)

    # ===================================================================
    # METRICS SUMMARY (if review_result provided)
    # ===================================================================

    if review_result is not None:
        m = review_result.metrics

        # "Session Results" heading
        doc.add_heading("Session Results", level=1)
        doc.add_paragraph()  # spacer

        # Multi-colored stats line
        total_accepted = m.total_issues_accepted
        crit_count = m.accepted_by_severity.get("critical", 0)
        high_count = m.accepted_by_severity.get("high", 0)
        rejected = m.rejected_count

        p_stats = doc.add_paragraph()
        p_stats.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_stats.paragraph_format.space_before = Pt(3)
        p_stats.paragraph_format.space_after = Pt(3)

        def _stat_run(text, color, bold=True):
            r = p_stats.add_run(text)
            r.bold = bold
            r.font.size = Pt(13)
            r.font.color.rgb = RGBColor.from_string(color)

        def _pipe():
            _stat_run("   |   ", GRAY_LIGHT, bold=False)

        _stat_run(f"{total_accepted} Accepted Defects", NAVY_DARK)
        _pipe()
        _stat_run(f"{crit_count} Critical", RED)
        _pipe()
        _stat_run(f"{high_count} High", AMBER)
        _pipe()
        _stat_run(f"{rejected} Rejected", GREEN)

        doc.add_paragraph()  # spacer

        # Convergence note
        if not review_result.converged:
            p_note_title = doc.add_paragraph()
            p_note_title.paragraph_format.space_before = Pt(3)
            r_nt = p_note_title.add_run("Why Not Converged Does Not Mean Weak")
            r_nt.bold = True
            r_nt.font.color.rgb = RGBColor.from_string(NAVY_DARK)

            p_note = doc.add_paragraph()
            p_note.paragraph_format.space_after = Pt(6)
            r_nb = p_note.add_run(
                f"Oracle2 ran {review_result.total_rounds} round(s). "
                f"Non-convergence typically means later rounds surfaced novel "
                f"issues rather than repeating prior ones \u2014 a sign of thorough review."
            )
            r_nb.font.color.rgb = RGBColor.from_string(GRAY_DARK)

        doc.add_paragraph()  # spacer

    # ===================================================================
    # BODY CONTENT
    # ===================================================================

    blocks = parse_markdown(final_draft)

    for block in blocks:
        if block.kind == "h1":
            doc.add_heading(_strip_md(block.text), level=1)

        elif block.kind == "h2":
            doc.add_heading(_strip_md(block.text), level=2)

        elif block.kind == "h3":
            doc.add_heading(_strip_md(block.text), level=3)

        elif block.kind == "paragraph":
            clean = _strip_md(block.text)

            # Detect callout paragraphs (Critical:, Warning:, Note:)
            callout_color = _detect_callout(clean)
            if callout_color:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(3)
                r = p.add_run(clean)
                r.bold = True
                r.font.color.rgb = RGBColor.from_string(callout_color)
            else:
                p = doc.add_paragraph()
                _add_rich_runs(p, block.text, default_color=BLACK)

        elif block.kind == "bullet":
            p = doc.add_paragraph(style="List Paragraph" if "List Paragraph" in doc.styles else "List Bullet")
            _add_rich_runs(p, block.text, default_color=BLACK)

        elif block.kind == "numbered":
            style_name = "List Number" if "List Number" in doc.styles else "List Paragraph"
            p = doc.add_paragraph(style=style_name)
            _add_rich_runs(p, block.text, default_color=BLACK)

        elif block.kind == "code":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(block.text)
            run.font.name = "Consolas"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor.from_string(GRAY_DARK)
            _shade_paragraph(p, "F1F5F9")

        elif block.kind == "table":
            _render_docx_table(doc, block.rows or [])

        elif block.kind == "hr":
            doc.add_paragraph()  # empty spacer, matching Beth's style

    # ===================================================================
    # CONFIDENTIALITY FOOTER
    # ===================================================================

    for _ in range(3):
        doc.add_paragraph()

    p_footer = doc.add_paragraph()
    p_footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_text = (
        "This communication and its attachments are privileged and confidential. "
        "Generated by ORACLE \u2014 BoundState AI LLC."
    )
    r_ft = p_footer.add_run(footer_text)
    r_ft.italic = True
    r_ft.font.size = Pt(9)
    r_ft.font.color.rgb = RGBColor.from_string(GRAY_MED)

    doc.save(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# PPTX Generator
# ---------------------------------------------------------------------------

def generate_pptx(
    final_draft: str,
    output_path: Path,
    title: str = "Oracle Review",
    subtitle: str | None = None,
    review_result: "ReviewResult | None" = None,
) -> Path:
    """Generate a polished multi-slide .pptx.

    Features:
      - Dark navy title slide + teal accent
      - Metrics summary slide (if review_result provided)
      - Content grouped by H1/H2 → one slide per section
      - Auto-chunking at ~8 lines per slide
      - Dark closing slide with branding
      - Widescreen 13.333" x 7.5"
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    blocks = parse_markdown(final_draft)

    # --- Group blocks into sections by H1/H2 ---
    sections: list[dict] = []
    current: dict | None = None

    for block in blocks:
        if block.kind in ("h1", "h2"):
            if current:
                sections.append(current)
            current = {"title": _strip_md(block.text), "level": block.kind, "blocks": []}
        else:
            if current is None:
                current = {"title": title, "level": "h1", "blocks": []}
            current["blocks"].append(block)

    if current:
        sections.append(current)
    if not sections:
        sections = [{"title": title, "level": "h1", "blocks": blocks}]

    # --- Title slide (dark) ---
    _pptx_title_slide(prs, title, subtitle or "Reviewed by ORACLE \u2014 BoundState AI")

    # --- Metrics slide (if available) ---
    if review_result is not None:
        _pptx_metrics_slide(prs, review_result)

    # --- Content slides ---
    for sec in sections:
        content_lines = _blocks_to_lines(sec["blocks"])
        if not content_lines:
            continue
        chunks = _chunk_lines(content_lines, max_lines=8)
        for ci, chunk in enumerate(chunks):
            slide_title = sec["title"]
            if len(chunks) > 1:
                slide_title += f" ({ci + 1}/{len(chunks)})"
            _pptx_content_slide(prs, slide_title, chunk)

    # --- Closing slide (dark) ---
    _pptx_closing_slide(prs)

    prs.save(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# PPTX: Slide builders
# ---------------------------------------------------------------------------

def _pptx_fill_bg(slide, color_hex: str):
    from pptx.dml.color import RGBColor
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(color_hex)


def _pptx_title_slide(prs, title: str, subtitle: str):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _pptx_fill_bg(slide, NAVY_DARK)

    # Title
    tb = slide.shapes.add_textbox(Inches(1.2), Inches(2.0), Inches(10.9), Inches(1.8))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(40)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    p.alignment = PP_ALIGN.LEFT

    # Accent bar
    bar = slide.shapes.add_shape(1, Inches(1.2), Inches(3.9), Inches(3), Pt(3))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor.from_string("0891B2")  # teal
    bar.line.fill.background()

    # Subtitle
    tb2 = slide.shapes.add_textbox(Inches(1.2), Inches(4.2), Inches(10.9), Inches(0.8))
    tf2 = tb2.text_frame
    tf2.word_wrap = True
    p2 = tf2.paragraphs[0]
    p2.text = subtitle
    p2.font.size = Pt(18)
    p2.font.color.rgb = RGBColor.from_string("0891B2")
    p2.alignment = PP_ALIGN.LEFT

    # Company name (bottom)
    tb3 = slide.shapes.add_textbox(Inches(1.2), Inches(6.5), Inches(4), Inches(0.5))
    tf3 = tb3.text_frame
    p3 = tf3.paragraphs[0]
    p3.text = "BoundState AI LLC"
    p3.font.size = Pt(12)
    p3.font.color.rgb = RGBColor.from_string(GRAY_LIGHT)


def _pptx_metrics_slide(prs, review_result):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _pptx_fill_bg(slide, "FFFFFF")

    m = review_result.metrics

    # Title bar
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.333), Inches(1.1))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor.from_string("F0F7FA")
    bar.line.fill.background()

    tb = slide.shapes.add_textbox(Inches(0.8), Inches(0.2), Inches(11.7), Inches(0.7))
    p = tb.text_frame.paragraphs[0]
    p.text = "Session Results"
    p.font.size = Pt(26)
    p.font.bold = True
    p.font.color.rgb = RGBColor.from_string(NAVY_DARK)

    # Big stat boxes
    stats = [
        (str(m.total_issues_accepted), "Accepted\nDefects", NAVY_DARK),
        (str(m.accepted_by_severity.get("critical", 0)), "Critical", RED),
        (str(m.accepted_by_severity.get("high", 0)), "High", AMBER),
        (str(m.rejected_count), "Rejected", GREEN),
        (str(review_result.total_rounds), "Rounds", NAVY_MED),
    ]

    x_start = 0.8
    box_w = 2.2
    gap = 0.3
    for i, (num, label, color) in enumerate(stats):
        x = x_start + i * (box_w + gap)

        # Number
        ntb = slide.shapes.add_textbox(Inches(x), Inches(2.5), Inches(box_w), Inches(1.2))
        np = ntb.text_frame.paragraphs[0]
        np.text = num
        np.font.size = Pt(48)
        np.font.bold = True
        np.font.color.rgb = RGBColor.from_string(color)
        np.alignment = PP_ALIGN.CENTER

        # Label
        ltb = slide.shapes.add_textbox(Inches(x), Inches(3.8), Inches(box_w), Inches(0.5))
        lp = ltb.text_frame.paragraphs[0]
        lp.text = label
        lp.font.size = Pt(14)
        lp.font.color.rgb = RGBColor.from_string(GRAY_MED)
        lp.alignment = PP_ALIGN.CENTER

    # Convergence status
    status = "Converged" if review_result.converged else "Did Not Converge (novel issues in later rounds)"
    stb = slide.shapes.add_textbox(Inches(0.8), Inches(5.5), Inches(11.7), Inches(0.5))
    sp = stb.text_frame.paragraphs[0]
    sp.text = status
    sp.font.size = Pt(14)
    sp.font.italic = True
    sp.font.color.rgb = RGBColor.from_string(GRAY_MED)
    sp.alignment = PP_ALIGN.CENTER


def _pptx_content_slide(prs, title: str, lines: list[str]):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _pptx_fill_bg(slide, "FFFFFF")

    # Title bar
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.333), Inches(1.1))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor.from_string("F0F7FA")
    bar.line.fill.background()

    tb = slide.shapes.add_textbox(Inches(0.8), Inches(0.2), Inches(11.7), Inches(0.7))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(26)
    p.font.bold = True
    p.font.color.rgb = RGBColor.from_string(NAVY_DARK)

    # Content body
    ctb = slide.shapes.add_textbox(Inches(0.8), Inches(1.4), Inches(11.7), Inches(5.5))
    ctf = ctb.text_frame
    ctf.word_wrap = True

    for i, line in enumerate(lines):
        p = ctf.paragraphs[0] if i == 0 else ctf.add_paragraph()

        clean = line
        is_bullet = False
        if line.startswith("\u2022 ") or line.startswith("- "):
            clean = line[2:]
            is_bullet = True

        # Bold "Label: value" patterns
        bm = re.match(r"^(.+?):\s*(.+)$", clean)
        if bm and len(bm.group(1)) < 60:
            prefix = "\u2022 " if is_bullet else ""
            r1 = p.add_run()
            r1.text = prefix + bm.group(1) + ": "
            r1.font.bold = True
            r1.font.size = Pt(14)
            r1.font.color.rgb = RGBColor.from_string(NAVY_DARK)

            r2 = p.add_run()
            r2.text = bm.group(2)
            r2.font.size = Pt(14)
            r2.font.color.rgb = RGBColor.from_string(GRAY_DARK)
        else:
            prefix = "\u2022 " if is_bullet else ""
            p.text = prefix + clean
            p.font.size = Pt(14)
            p.font.color.rgb = RGBColor.from_string(GRAY_DARK)

        p.space_after = Pt(6)
        p.space_before = Pt(2)

    # Footer
    ftb = slide.shapes.add_textbox(Inches(0.8), Inches(7.0), Inches(4), Inches(0.3))
    fp = ftb.text_frame.paragraphs[0]
    fp.text = "ORACLE \u2014 BoundState AI"
    fp.font.size = Pt(8)
    fp.font.color.rgb = RGBColor.from_string(GRAY_MED)
    fp.font.italic = True


def _pptx_closing_slide(prs):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _pptx_fill_bg(slide, NAVY_DARK)

    tb = slide.shapes.add_textbox(Inches(1.2), Inches(2.8), Inches(10.9), Inches(1.2))
    p = tb.text_frame.paragraphs[0]
    p.text = "Review Complete"
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    p.alignment = PP_ALIGN.LEFT

    tb2 = slide.shapes.add_textbox(Inches(1.2), Inches(4.2), Inches(10.9), Inches(0.6))
    p2 = tb2.text_frame.paragraphs[0]
    p2.text = "Generated by ORACLE \u2022 BoundState AI LLC"
    p2.font.size = Pt(16)
    p2.font.color.rgb = RGBColor.from_string("0891B2")
    p2.alignment = PP_ALIGN.LEFT


# ---------------------------------------------------------------------------
# PPTX: helpers
# ---------------------------------------------------------------------------

def _blocks_to_lines(blocks: list[Block]) -> list[str]:
    """Convert blocks into simple text lines for slides."""
    lines: list[str] = []
    for b in blocks:
        if b.kind == "paragraph":
            text = _strip_md(b.text)
            if text:
                lines.append(text)
        elif b.kind == "bullet":
            lines.append(f"\u2022 {_strip_md(b.text)}")
        elif b.kind == "numbered":
            lines.append(f"\u2022 {_strip_md(b.text)}")
        elif b.kind == "h3":
            lines.append(_strip_md(b.text))
        elif b.kind == "code":
            snippet = b.text[:200]
            if len(b.text) > 200:
                snippet += "..."
            lines.append(snippet)
        elif b.kind == "table" and b.rows:
            # WHY: Slides are a poor venue for real tables. Flatten to
            # "header: value | header: value" bullets keyed off the
            # header row — readable at a glance, no layout gymnastics.
            header = b.rows[0]
            for row in b.rows[1:]:
                pieces = [
                    f"{_strip_md(h)}: {_strip_md(c)}"
                    for h, c in zip(header, row)
                    if c.strip()
                ]
                if pieces:
                    lines.append("\u2022 " + " | ".join(pieces))
    return lines


def _chunk_lines(lines: list[str], max_lines: int = 8) -> list[list[str]]:
    """Split lines into slide-sized chunks."""
    if not lines:
        return []
    return [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]
