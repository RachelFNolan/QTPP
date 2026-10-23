from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from .document import (
    FieldSelection,
    PacketDocument,
    Run,
    build_packet_document,
    format_bonus_part_marker,
)
from .model import Packet, QuestionSet

if TYPE_CHECKING:
    from reportlab.platypus import Flowable


def render_packet_pdf(document: PacketDocument) -> bytes:
    """Render a packet document as PDF bytes."""
    try:
        import reportlab
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as error:
        raise ImportError(
            "PDF export requires ReportLab. Install it with "
            "`python -m pip install -r requirements-export.txt`."
        ) from error

    font_dir = Path(reportlab.__file__).parent / "fonts"
    fonts = {
        "QTPPVera": "Vera.ttf",
        "QTPPVera-Bold": "VeraBd.ttf",
        "QTPPVera-Italic": "VeraIt.ttf",
        "QTPPVera-BoldItalic": "VeraBI.ttf",
    }
    for name, filename in fonts.items():
        font_path = font_dir / filename
        if not font_path.is_file():
            raise ImportError(f"ReportLab's bundled font is missing: {font_path}")
        pdfmetrics.registerFont(TTFont(name, str(font_path)))
    pdfmetrics.registerFontFamily(
        "QTPPVera",
        normal="QTPPVera",
        bold="QTPPVera-Bold",
        italic="QTPPVera-Italic",
        boldItalic="QTPPVera-BoldItalic",
    )
    pdfmetrics.registerFontFamily(
        "Times-Roman",
        normal="Times-Roman",
        bold="Times-Bold",
        italic="Times-Italic",
        boldItalic="Times-BoldItalic",
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "QTPPTitle",
            parent=styles["Normal"],
            fontName="Times-Bold",
            fontSize=10,
            leading=13.2,
            spaceAfter=0,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPHeading",
            parent=styles["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=13.2,
            spaceBefore=13.2,
            spaceAfter=13.2,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPBody",
            parent=styles["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=13.2,
            spaceAfter=0,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPAnswer",
            parent=styles["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=13.2,
            spaceAfter=0,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPDetails",
            parent=styles["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=13.2,
            spaceAfter=0,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPPart",
            parent=styles["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=13.2,
            spaceAfter=0,
        )
    )

    story: list[Flowable] = []
    front = document.front_matter
    if front.set_name:
        title = front.set_name
        if front.set_year is not None:
            title = f"{front.set_year} {title}"
        story.append(Paragraph(_text_markup(title), styles["QTPPTitle"]))
    if front.packet_name:
        packet_label = front.packet_name
        if front.packet_number is not None:
            packet_label = f"Packet {front.packet_number}: {packet_label}"
        story.append(Paragraph(_text_markup(packet_label), styles["QTPPBody"]))
    if front.authors:
        authors = f"Edited and written by {', '.join(front.authors)}"
        story.append(Paragraph(_text_markup(authors), styles["QTPPBody"]))

    if document.tossups:
        story.append(Paragraph("Tossups", styles["QTPPHeading"]))
        for index, tossup in enumerate(document.tossups):
            story.append(
                Paragraph(
                    f"{tossup.number}. {_runs_markup(tossup.question)}",
                    styles["QTPPBody"],
                )
            )
            if tossup.answer is not None:
                story.append(
                    Paragraph(
                        f"ANSWER: {_runs_markup(tossup.answer)}",
                        styles["QTPPAnswer"],
                    )
                )
            if tossup.details:
                story.append(
                    Paragraph(_details_markup(tossup.details), styles["QTPPDetails"])
                )
            if index + 1 < len(document.tossups):
                story.append(Spacer(1, 13.2))

    if document.bonuses:
        story.append(Paragraph("Bonuses", styles["QTPPHeading"]))
        for index, bonus in enumerate(document.bonuses):
            story.append(
                Paragraph(
                    f"{bonus.number}. {_runs_markup(bonus.leadin)}",
                    styles["QTPPBody"],
                )
            )
            if bonus.details:
                story.append(
                    Paragraph(_details_markup(bonus.details), styles["QTPPDetails"])
                )
            for part in bonus.parts:
                marker = format_bonus_part_marker(part.value, part.modifier)
                prefix = f"{_text_markup(marker)} " if marker else ""
                story.append(
                    Paragraph(prefix + _runs_markup(part.question), styles["QTPPPart"])
                )
                if part.answer is not None:
                    story.append(
                        Paragraph(
                            f"ANSWER: {_runs_markup(part.answer)}",
                            styles["QTPPAnswer"],
                        )
                    )
            if index + 1 < len(document.bonuses):
                story.append(Spacer(1, 13.2))

    stream = BytesIO()
    pdf = SimpleDocTemplate(
        stream,
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=0.9 * inch,
        bottomMargin=inch,
        title=front.packet_name or front.set_name or "Quiz bowl packet",
        author=", ".join(front.authors) if front.authors else None,
        pageCompression=1,
    )
    pdf.build(story)
    return stream.getvalue()


def export_packet_pdf(
    question_set: QuestionSet,
    packet: Packet,
    selection: FieldSelection = FieldSelection(),
    authors: Mapping[str, str] | None = None,
) -> bytes:
    """Build and render one packet as PDF bytes."""
    return render_packet_pdf(
        build_packet_document(question_set, packet, selection=selection, authors=authors)
    )


def _runs_markup(runs: tuple[Run, ...]) -> str:
    fragments: list[str] = []
    for run in runs:
        text = _text_markup(run.text).replace("\n", "<br/>")
        if run.underline:
            text = f"<u>{text}</u>"
        if run.italic:
            text = f"<i>{text}</i>"
        if run.bold:
            text = f"<b>{text}</b>"
        fragments.append(text)
    return "".join(fragments)


def _safe(text: str) -> str:
    return escape(text, quote=False)


def _text_markup(text: str) -> str:
    escaped = _safe(text)
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return f'<font name="QTPPVera">{escaped}</font>'
    return escaped


def _details_markup(details: Mapping[str, str]) -> str:
    fields = [
        f"{_text_markup(label.replace('_', ' ').title())}: {_text_markup(value)}"
        for label, value in details.items()
    ]
    return f"&lt;{' · '.join(fields)}&gt;"
