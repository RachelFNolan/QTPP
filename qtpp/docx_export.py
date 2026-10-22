from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Mapping

from .document import (
    FieldSelection,
    PacketDocument,
    Run,
    build_packet_document,
)
from .model import Packet, QuestionSet

if TYPE_CHECKING:
    from docx.document import Document as WordDocument
    from docx.enum.text import WD_BREAK
    from docx.text.paragraph import Paragraph as WordParagraph


def render_packet_docx(document: PacketDocument) -> bytes:
    """Render a packet document as a Microsoft Word DOCX file."""
    try:
        from docx import Document
        from docx.enum.text import WD_BREAK
        from docx.shared import Inches, Pt
    except ImportError as error:
        raise ImportError(
            "DOCX export requires python-docx. Install it with "
            "`python -m pip install -r requirements-export.txt`."
        ) from error

    word = Document()
    section = word.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    normal = word.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(5)

    front = document.front_matter
    if front.set_name:
        title = front.set_name
        if front.set_year is not None:
            title = f"{front.set_year} {title}"
        word.add_heading(title, level=0)
    if front.packet_name:
        label = front.packet_name
        if front.packet_number is not None:
            label = f"Packet {front.packet_number}: {label}"
        word.add_heading(label, level=1)
    if front.authors:
        word.add_paragraph(", ".join(front.authors))

    if document.tossups:
        word.add_heading("Tossups", level=2)
        for tossup in document.tossups:
            paragraph = word.add_paragraph()
            paragraph.add_run(f"{tossup.number}. ")
            _add_runs(paragraph, tossup.question, WD_BREAK.LINE)
            if tossup.answer is not None:
                paragraph = word.add_paragraph()
                paragraph.paragraph_format.left_indent = Inches(0.25)
                label = paragraph.add_run("Answer: ")
                label.bold = True
                _add_runs(paragraph, tossup.answer, WD_BREAK.LINE)
            _add_details(word, tossup.details)

    if document.bonuses:
        word.add_heading("Bonuses", level=2)
        for bonus in document.bonuses:
            paragraph = word.add_paragraph()
            paragraph.add_run(f"{bonus.number}. ")
            _add_runs(paragraph, bonus.leadin, WD_BREAK.LINE)
            _add_details(word, bonus.details)
            for part in bonus.parts:
                paragraph = word.add_paragraph()
                paragraph.paragraph_format.left_indent = Inches(0.25)
                paragraph.add_run(f"{part.number}. ")
                if part.value is not None:
                    paragraph.add_run(f"({part.value} points) ")
                if part.modifier:
                    paragraph.add_run(f"[{part.modifier}] ")
                _add_runs(paragraph, part.question, WD_BREAK.LINE)
                if part.answer is not None:
                    paragraph = word.add_paragraph()
                    paragraph.paragraph_format.left_indent = Inches(0.5)
                    label = paragraph.add_run("Answer: ")
                    label.bold = True
                    _add_runs(paragraph, part.answer, WD_BREAK.LINE)

    stream = BytesIO()
    word.save(stream)
    return stream.getvalue()


def export_packet_docx(
    question_set: QuestionSet,
    packet: Packet,
    selection: FieldSelection = FieldSelection(),
    authors: Mapping[str, str] | None = None,
) -> bytes:
    """Build and render one packet as DOCX bytes."""
    return render_packet_docx(
        build_packet_document(question_set, packet, selection=selection, authors=authors)
    )


def _add_runs(
    paragraph: WordParagraph, runs: tuple[Run, ...], line_break: WD_BREAK
) -> None:
    for source in runs:
        pieces = source.text.split("\n")
        for index, text in enumerate(pieces):
            if index:
                paragraph.add_run().add_break(line_break)
            if not text:
                continue
            run = paragraph.add_run(text)
            run.bold = source.bold
            run.underline = source.underline
            run.italic = source.italic


def _add_details(word: WordDocument, details: Mapping[str, str]) -> None:
    if not details:
        return
    from docx.shared import Inches

    paragraph = word.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.25)
    for index, (label, value) in enumerate(details.items()):
        if index:
            paragraph.add_run(" · ")
        run = paragraph.add_run(f"{label.replace('_', ' ').title()}: {value}")
        run.italic = True
