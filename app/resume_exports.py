"""Create final files only after review. No network calls or claims are generated."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from docx import Document
from docx.shared import Inches, Pt
from reportlab import rl_config
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


def export_resume(content):
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(.65)
    document.styles['Normal'].font.name = 'Arial'
    document.styles['Normal'].font.size = Pt(10)
    document.styles['Normal'].paragraph_format.space_after = Pt(4)
    lines = content.splitlines()
    for index, line in enumerate(lines):
        para = document.add_paragraph(line)
        if index == 0:
            for run in para.runs:
                run.bold = True
                run.font.size = Pt(16)
    word = BytesIO()
    document.save(word)
    # ReportLab ships this font; no system fonts or network dependencies needed.
    font_path = next(Path(p) / 'Vera.ttf' for p in rl_config.TTFSearchPath if (Path(p) / 'Vera.ttf').exists())
    if 'ResumeVera' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('ResumeVera', str(font_path)))
    style = ParagraphStyle('resume', fontName='ResumeVera', fontSize=10, leading=14, alignment=TA_LEFT, spaceAfter=4)
    title = ParagraphStyle('name', parent=style, fontSize=16, leading=20, spaceAfter=8)
    pdf = BytesIO()
    flow = [Paragraph(escape(line), title if i == 0 else style) if line.strip() else Spacer(1, 7) for i, line in enumerate(lines)]
    SimpleDocTemplate(pdf, leftMargin=48, rightMargin=48, topMargin=46, bottomMargin=46).build(flow)
    return pdf.getvalue(), word.getvalue()
