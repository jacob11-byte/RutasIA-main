from pathlib import Path
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "documentacion" / "Proyecto_Tecnico_Flamia_Tesis.docx"
OUTPUT = ROOT / "documentacion" / "Proyecto_Tecnico_Flamia_Tesis_APA_7.docx"


def set_font(run, name="Arial", size=11, bold=None, italic=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, end])
    set_font(run)


def insert_before(element, text, *, bold=False, italic=False, align=None, keep=True):
    p = document.add_paragraph()
    p._element.getparent().remove(p._element)
    element.addprevious(p._element)
    if align is not None:
        p.alignment = align
    p.paragraph_format.line_spacing = 2
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.keep_with_next = keep
    r = p.add_run(text)
    set_font(r, bold=bold, italic=italic)
    return p


document = Document(SOURCE)

# APA 7 plus the institutional left-margin exception stated in the supplied UMG deck.
for section in document.sections:
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.0)
    section.right_margin = Cm(2.54)
    section.header_distance = Cm(1.27)
    section.footer_distance = Cm(1.27)
    header = section.header
    for p in header.paragraphs:
        p.clear()
    add_page_number(header.paragraphs[0])
    for p in section.footer.paragraphs:
        p.clear()

normal = document.styles["Normal"]
normal.font.name = "Arial"
normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
normal.font.size = Pt(11)
normal.paragraph_format.line_spacing = 2
normal.paragraph_format.space_before = Pt(0)
normal.paragraph_format.space_after = Pt(0)
normal.paragraph_format.first_line_indent = Inches(0.5)

title = document.styles["Title"]
title.font.name = "Arial"
title._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
title.font.size = Pt(14)
title.font.bold = True
title.font.color.rgb = None
title.paragraph_format.line_spacing = 2
title.paragraph_format.space_after = Pt(0)

subtitle = document.styles["Subtitle"]
subtitle.font.name = "Arial"
subtitle._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
subtitle.font.size = Pt(11)
subtitle.font.italic = False
subtitle.font.color.rgb = None
subtitle.paragraph_format.line_spacing = 2
subtitle.paragraph_format.space_after = Pt(0)

# APA heading hierarchy.
for name, size, alignment, italic in (
    ("Heading 1", 11, WD_ALIGN_PARAGRAPH.CENTER, False),
    ("Heading 2", 11, WD_ALIGN_PARAGRAPH.LEFT, False),
    ("Heading 3", 11, WD_ALIGN_PARAGRAPH.LEFT, True),
):
    style = document.styles[name]
    style.font.name = "Arial"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    style.font.size = Pt(size)
    style.font.bold = True
    style.font.italic = italic
    style.font.color.rgb = None
    style.paragraph_format.alignment = alignment
    style.paragraph_format.line_spacing = 2
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.keep_with_next = True

# Paragraph and list formatting. Cover-page elements remain centered and unindented.
first_break_seen = False
for i, p in enumerate(document.paragraphs):
    for r in p.runs:
        set_font(r, size=11)
    is_heading = p.style and p.style.name.startswith("Heading")
    is_list = p.style and p.style.name.startswith("List")
    has_page_break = bool(p._element.xpath('.//w:br[@w:type="page"]'))
    if not first_break_seen:
        p.paragraph_format.first_line_indent = None
        if i > 0:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif not is_heading and not is_list and not p._element.xpath('.//w:drawing'):
        p.paragraph_format.first_line_indent = Inches(0.5)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if is_list:
        p.paragraph_format.first_line_indent = None
        p.paragraph_format.left_indent = Inches(0.5)
    p.paragraph_format.line_spacing = 2
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    if has_page_break:
        first_break_seen = True

# Add brief in-text attributions where external standards or documentation support a claim.
replacements = {
    "El proyecto declara Python 3.12.8 para producción y Django 6.0.4 como framework web.":
        "El proyecto declara Python 3.12.8 para producción y Django 6.0.4 como framework web (Django Software Foundation, 2026; Python Software Foundation, 2026).",
    "En producción utiliza PostgreSQL por medio de psycopg.":
        "En producción utiliza PostgreSQL por medio de psycopg (PostgreSQL Global Development Group, 2026).",
    "OWASP Top 10 se adopta como referencia de concientización para riesgos web.":
        "OWASP Top 10 se adopta como referencia de concientización para riesgos web (OWASP Foundation, 2026).",
}
for p in document.paragraphs:
    original = p.text
    updated = original
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    if updated != original:
        p.clear()
        r = p.add_run(updated)
        set_font(r)

# APA figure labels and titles appear above the image.
for p in list(document.paragraphs):
    m = re.match(r"^(Figura\s+\d+)\.\s*(.+)$", p.text.strip())
    if not m:
        continue
    prev = p._element.getprevious()
    if prev is None or not prev.xpath('.//w:drawing'):
        continue
    insert_before(prev, m.group(1), bold=True)
    insert_before(prev, m.group(2), italic=True)
    p._element.getparent().remove(p._element)

# Give every table an APA number and a concise title above it.
for number, table in enumerate(document.tables, start=1):
    headers = [c.text.strip() for c in table.rows[0].cells]
    title_text = "Información de " + " y ".join(h.lower() for h in headers[:2])
    insert_before(table._element, f"Tabla {number}", bold=True)
    insert_before(table._element, title_text, italic=True)
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.first_line_indent = None
                p.paragraph_format.line_spacing = 1
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                for r in p.runs:
                    set_font(r, size=9, bold=True if row_index == 0 else None)

# Rename the source list and apply APA hanging indents.
for p in document.paragraphs:
    if p.text.strip() == "5 Bibliografía":
        p.text = "5 Referencias"
        p.style = document.styles["Heading 1"]
        for r in p.runs:
            set_font(r, bold=True)
        continue
    if p.text.startswith(("Django Software Foundation.", "Python Software Foundation.", "PostgreSQL Global Development Group.",
                          "OWASP Foundation.", "MapLibre.", "HeiGIT.", "Render.", "WhiteNoise.", "Evans,", "Fowler,",
                          "Gamma,", "Documentación interna")):
        p.paragraph_format.left_indent = Inches(0.5)
        p.paragraph_format.first_line_indent = Inches(-0.5)
        p.paragraph_format.line_spacing = 2

document.core_properties.title = "Proyecto técnico del sistema Flamia en formato APA séptima edición"
document.core_properties.subject = "Documento técnico de tesis con formato APA 7"
document.save(OUTPUT)
print(OUTPUT)
