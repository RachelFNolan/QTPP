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
)
from .model import Packet, QuestionSet

if TYPE_CHECKING:
    from reportlab.platypus import Flowable


def render_packet_pdf(document: PacketDocument) -> bytes:
    """Render a packet document as PDF bytes."""
    try:
        import reportlab
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
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

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "QTPPTitle",
            parent=styles["Title"],
            fontName="QTPPVera-Bold",
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPHeading",
            parent=styles["Heading2"],
            fontName="QTPPVera-Bold",
            fontSize=13,
            leading=16,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPBody",
            parent=styles["BodyText"],
            fontName="QTPPVera",
            fontSize=10.5,
            leading=14,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPAnswer",
            parent=styles["BodyText"],
            fontName="QTPPVera",
            fontSize=9.5,
            leading=12,
            leftIndent=18,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPDetails",
            parent=styles["BodyText"],
            fontName="QTPPVera-Italic",
            fontSize=8,
            leading=10,
            leftIndent=18,
            textColor=colors.HexColor("#555555"),
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            "QTPPPart",
            parent=styles["BodyText"],
            fontName="QTPPVera",
            fontSize=10,
            leading=13,
            leftIndent=18,
            spaceAfter=4,
        )
    )

    story: list[Flowable] = []
    front = document.front_matter
    if front.set_name:
        title = front.set_name
        if front.set_year is not None:
            title = f"{front.set_year} {title}"
        story.append(Paragraph(_safe(title), styles["QTPPTitle"]))
    if front.packet_name:
        packet_label = front.packet_name
        if front.packet_number is not None:
            packet_label = f"Packet {front.packet_number}: {packet_label}"
        story.append(Paragraph(_safe(packet_label), styles["Heading2"]))
    if front.authors:
        story.append(Paragraph(_safe(", ".join(front.authors)), styles["QTPPBody"]))
    if story:
        story.append(Spacer(1, 0.12 * inch))

    if document.tossups:
        story.append(Paragraph("Tossups", styles["QTPPHeading"]))
        for tossup in document.tossups:
            story.append(
                Paragraph(
                    f"<b>{tossup.number}.</b> {_runs_markup(tossup.question)}",
                    styles["QTPPBody"],
                )
            )
            if tossup.answer is not None:
                story.append(
                    Paragraph(
                        f"<b>Answer:</b> {_runs_markup(tossup.answer)}",
                        styles["QTPPAnswer"],
                    )
                )
            if tossup.details:
                    story.append(
                        Paragraph(_details_markup(tossup.details), styles["QTPPDetails"])
                    )

    if document.bonuses:
        story.append(Paragraph("Bonuses", styles["QTPPHeading"]))
        for bonus in document.bonuses:
            story.append(
                Paragraph(
                    f"<b>{bonus.number}.</b> {_runs_markup(bonus.leadin)}",
                    styles["QTPPBody"],
                )
            )
            if bonus.details:
                story.append(
                    Paragraph(_details_markup(bonus.details), styles["QTPPDetails"])
                )
            for part in bonus.parts:
                markers = []
                if part.value is not None:
                    markers.append(f"{part.value} points")
                if part.modifier:
                    markers.append(part.modifier)
                prefix = f"<b>{part.number}.</b> "
                if markers:
                    prefix += f"<i>({'; '.join(_safe(marker) for marker in markers)})</i> "
                story.append(
                    Paragraph(prefix + _runs_markup(part.question), styles["QTPPPart"])
                )
                if part.answer is not None:
                    story.append(
                        Paragraph(
                            f"<b>Answer:</b> {_runs_markup(part.answer)}",
                            styles["QTPPAnswer"],
                        )
                    )

    stream = BytesIO()
    pdf = SimpleDocTemplate(
        stream,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
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
        text = _safe(run.text).replace("\n", "<br/>")
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


def _details_markup(details: Mapping[str, str]) -> str:
    fields: list[str] = [
        f"<b>{_safe(label.replace('_', ' ').title())}:</b> {_safe(value)}"
        for label, value in details.items()
    ]
    return " · ".join(fields)
