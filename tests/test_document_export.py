from __future__ import annotations

from io import BytesIO
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader

from qtpp import (
    Bonus,
    BonusPart,
    FieldSelection,
    Packet,
    QuestionMetadata,
    QuestionPlacement,
    QuestionSet,
    QuestionSetMetadata,
    Topic,
    Tossup,
    export_packet_docx,
    export_packet_pdf,
)


def sample_question_set() -> tuple[QuestionSet, Packet]:
    packet = Packet(
        "packet-1",
        "Round A",
        1,
        (QuestionPlacement("tu-1", 1),),
        (QuestionPlacement("bonus-1", 1),),
    )
    question_set = QuestionSet(
        metadata=QuestionSetMetadata("set-1", "Été Invitational", 2026, True),
        tossups=(
            Tossup(
                QuestionMetadata("tu-1", Topic("History", "World History")),
                "A <b>bold</b> & <u>underlined</u> tossup.\nSecond line.",
                "La réponse",
                question_sanitized="A bold and underlined tossup. Second line.",
            ),
        ),
        bonuses=(
            Bonus(
                QuestionMetadata(
                    "bonus-1", Topic("Literature", "Poetry", "Romanticism")
                ),
                "Name this <i>poem</i>.",
                (BonusPart(1, "Identify the author.", "Jane Doe", 10, "standard"),),
            ),
        ),
        packets=(packet,),
    )
    return question_set, packet


class DocumentExportTests(unittest.TestCase):
    def test_docx_contains_packet_content_and_inline_formatting(self) -> None:
        question_set, packet = sample_question_set()
        content = export_packet_docx(
            question_set,
            packet,
            FieldSelection(
                category_subcategory=True,
                alternate_subcategory=True,
                source_question_id=True,
                author=True,
            ),
            {"tu-1": "Alex"},
        )

        with ZipFile(BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = "".join(node.text or "" for node in root.findall(".//w:t", namespace))
        self.assertIn("Été Invitational", text)
        self.assertIn("Packet 1: Round A", text)
        self.assertIn("La réponse", text)
        self.assertIn("10 points", text)
        self.assertIn("Source Question Id: tu-1", text)
        self.assertIn("Author: Alex", text)
        self.assertGreater(len(root.findall(".//w:b", namespace)), 0)
        self.assertGreater(len(root.findall(".//w:u", namespace)), 0)
        self.assertGreater(len(root.findall(".//w:i", namespace)), 0)

    def test_pdf_preserves_content_and_selection(self) -> None:
        question_set, packet = sample_question_set()
        content = export_packet_pdf(
            question_set,
            packet,
            FieldSelection(
                text_form="sanitized",
                include_answers=False,
                bonus_values=False,
                bonus_modifiers=False,
                category_subcategory=True,
                front_packet_name=False,
            ),
        )
        self.assertTrue(content.startswith(b"%PDF-"))
        reader = PdfReader(BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Été Invitational", text)
        self.assertIn("A bold and underlined tossup.", text)
        self.assertIn("Category: Literature", text)
        self.assertNotIn("Jane Doe", text)
        self.assertNotIn("La réponse", text)
        self.assertNotIn("10 points", text)
