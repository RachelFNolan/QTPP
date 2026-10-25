import csv
import json
import tempfile
import unittest
from pathlib import Path

from qtpp import Bonus, Difficulty, load_question_pool_csv
from utilities.generate_question_pool import generate_question_pool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = PROJECT_ROOT / "Test Questions" / "2025 ACF Winter Question Pool.csv"
# Per-packet JSON folder lives in a gitignored directory, so it may be absent.
SAMPLE_PACKETS_DIR = PROJECT_ROOT / "Test Questions" / "2025 ACF Winter"


class LoadQuestionPoolCsvTests(unittest.TestCase):
    def test_imports_checked_in_bom_csv_as_unpacketized_pool(self) -> None:
        question_set = load_question_pool_csv(SAMPLE_CSV)

        self.assertEqual(question_set.metadata.name, "2025 ACF Winter")
        self.assertEqual(question_set.metadata.year, 2025)
        self.assertIsNone(question_set.metadata.standard)
        self.assertIsNone(question_set.metadata.difficulty)
        self.assertEqual(len(question_set.tossups), 330)
        self.assertEqual(len(question_set.bonuses), 331)
        self.assertEqual(question_set.packets, ())

        first_tossup = question_set.tossups[0]
        self.assertEqual(first_tossup.metadata.id, "692330ebf1f28d19289b7f3f")
        self.assertEqual(first_tossup.metadata.topic.category, "Science")
        self.assertEqual(first_tossup.metadata.topic.subcategory, "Biology")
        self.assertIsNone(first_tossup.metadata.difficulty)
        self.assertIn("<i>", first_tossup.question)
        self.assertNotIn("<i>", first_tossup.question_sanitized)

        bonus = question_set.bonuses[0]
        self.assertIsInstance(bonus, Bonus)
        self.assertTrue(bonus.parts)
        self.assertEqual(
            [part.number for part in bonus.parts],
            sorted(part.number for part in bonus.parts),
        )

    def test_parses_set_metadata_and_bonus_part_fields(self) -> None:
        bonus = {
            "part_number": 1,
            "question_raw": "Part question <i>text</i>",
            "question_sanitized": "Part question text",
            "answer_raw": "Part answer",
            "answer_sanitized": "Part answer",
            "value": 10,
            "difficulty_modifier": "standard",
        }
        row = _row(
            question_type="bonus",
            question_id="bonus-1",
            set_standard="false",
            set_difficulty='{"level":"College","sublevel":"Medium"}',
            bonus_leadin_raw="A lead-in",
            bonus_leadin_sanitized="A lead-in",
            bonus_parts_json=json.dumps([bonus]),
        )
        question_set = _load_rows([row])

        self.assertFalse(question_set.metadata.standard)
        self.assertEqual(
            question_set.metadata.difficulty,
            Difficulty(level="College", sublevel="Medium"),
        )
        part = question_set.bonuses[0].parts[0]
        self.assertEqual(part.number, 1)
        self.assertEqual(part.question, "Part question <i>text</i>")
        self.assertEqual(part.question_sanitized, "Part question text")
        self.assertEqual(part.value, 10)

    def test_accepts_extra_columns_and_optional_blanks(self) -> None:
        row = _row(question_sanitized="", answer_sanitized="", alternate_subcategory="")
        row["vendor_extension"] = "ignored"
        question_set = _load_rows([row], extra_columns=("vendor_extension",))
        question = question_set.tossups[0]
        self.assertIsNone(question.question_sanitized)
        self.assertIsNone(question.answer_sanitized)
        self.assertIsNone(question.metadata.topic.alternate_subcategory)

    def test_reports_missing_set_metadata_as_unknown_for_legacy_csv(self) -> None:
        row = _row()
        question_set = _load_rows(
            [row],
            omit_columns=("set_standard", "set_difficulty"),
        )
        self.assertIsNone(question_set.metadata.standard)
        self.assertIsNone(question_set.metadata.difficulty)

    def test_rejects_invalid_rows_with_row_context(self) -> None:
        cases = (
            (_row(question_type="unknown"), "CSV row 2.*question_type"),
            (_row(question_id=""), "CSV row 2.*question_id must be non-empty"),
            (_row(difficulty="not-json"), "CSV row 2.*difficulty is invalid JSON"),
            (
                _row(question_type="bonus", bonus_leadin_raw="A lead-in", bonus_parts_json="{"),
                "CSV row 2.*bonus_parts_json is invalid JSON",
            ),
            (
                _row(question_type="bonus", bonus_leadin_raw="A lead-in", bonus_parts_json="[]"),
                "CSV row 2.*bonus_parts_json must be a non-empty array",
            ),
        )
        for row, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                _load_rows([row])

    def test_rejects_duplicate_ids_and_inconsistent_set_metadata(self) -> None:
        first = _row(question_id="same")
        duplicate = _row(question_id="same")
        with self.assertRaisesRegex(ValueError, "duplicate question_id"):
            _load_rows([first, duplicate])

        inconsistent = _row(question_id="other", set_name="Different Set")
        with self.assertRaisesRegex(ValueError, "set ID, name, or year differs"):
            _load_rows([first, inconsistent])

    def test_rejects_malformed_csv_width(self) -> None:
        row = _row()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pool.csv"
            _write_rows(path, [row], extra_columns=("extra",))
            with path.open("a", encoding="utf-8") as output:
                output.write(",".join(["extra"] * (len(row) + 2)) + "\n")
            with self.assertRaisesRegex(ValueError, "CSV row 3.*more fields"):
                load_question_pool_csv(path)

    @unittest.skipUnless(SAMPLE_PACKETS_DIR.is_dir(), "sample packet JSON folder is not checked in")
    def test_pool_generator_writes_new_set_metadata_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "Question Pool.csv"
            generate_question_pool(SAMPLE_PACKETS_DIR, output)
            with output.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                self.assertIn("set_standard", reader.fieldnames)
                self.assertIn("set_difficulty", reader.fieldnames)
                first = next(reader)
            self.assertEqual(first["set_standard"], "true")
            self.assertEqual(first["set_difficulty"], "")
            imported = load_question_pool_csv(output)
            self.assertTrue(imported.metadata.standard)


def _row(**overrides: str) -> dict[str, str]:
    row = {
        "question_id": "q-1",
        "question_type": "tossup",
        "set_id": "set-1",
        "set_name": "Test Set",
        "set_year": "2025",
        "set_standard": "true",
        "set_difficulty": "",
        "question_raw": "Question text",
        "question_sanitized": "Question text",
        "answer_raw": "Answer text",
        "answer_sanitized": "Answer text",
        "category": "History",
        "subcategory": "American History",
        "alternate_subcategory": "",
        "difficulty": "",
        "bonus_leadin_raw": "",
        "bonus_leadin_sanitized": "",
        "bonus_parts_json": "",
    }
    row.update(overrides)
    return row


def _load_rows(
    rows: list[dict[str, str]],
    *,
    omit_columns: tuple[str, ...] = (),
    extra_columns: tuple[str, ...] = (),
):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "pool.csv"
        _write_rows(path, rows, omit_columns=omit_columns, extra_columns=extra_columns)
        return load_question_pool_csv(path)


def _write_rows(
    path: Path,
    rows: list[dict[str, str]],
    *,
    omit_columns: tuple[str, ...] = (),
    extra_columns: tuple[str, ...] = (),
) -> None:
    columns = [column for column in rows[0] if column not in omit_columns]
    columns.extend(column for column in extra_columns if column not in columns)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(
            {key: value for key, value in row.items() if key in columns}
            for row in rows
        )


if __name__ == "__main__":
    unittest.main()
