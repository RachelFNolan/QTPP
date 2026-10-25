import json
import tempfile
import unittest
from pathlib import Path

from qtpp import load_question_pool_csv, parse_question_pool_json
from qtpp.field_mapping import (
    inspect_csv,
    inspect_json,
    mapped_csv_text,
    mapped_pool_json,
    suggest_mapping,
)
from qtpp.workspace import Workspace, WorkspaceError

ODD_CSV = (
    "ID,Kind,Writer,Clue Text,Response,Cat,Sub,Lead,part1,answer1,part2,answer2\n"
    "a1,TU,Ann,Tossup text,Tossup answer,History,American,,,,,\n"
    "b1,bonus,Bob,,,Science,Biology,Bonus intro,Q one,A one,Q two,A two\n"
)
ODD_MAPPING = {
    "question_id": "ID",
    "question_type": "Kind",
    "author": "Writer",
    "question": "Clue Text",
    "answer": "Response",
    "category": "Cat",
    "subcategory": "Sub",
    "bonus_leadin": "Lead",
    "bonus_parts": [
        {"question": "part1", "answer": "answer1"},
        {"question": "part2", "answer": "answer2"},
    ],
}


class SuggestTests(unittest.TestCase):
    def test_exact_known_names_are_matched(self) -> None:
        result = suggest_mapping(["question_raw", "answer_raw", "category", "subcategory", "author"])
        self.assertEqual(result["mapping"]["question"], "question_raw")
        self.assertEqual(result["mapping"]["answer"], "answer_raw")
        self.assertEqual(result["mapping"]["author"], "author")
        self.assertEqual(result["confidence"]["author"], "exact")

    def test_numbered_part_columns_become_pairs_not_answer(self) -> None:
        result = suggest_mapping(["answer", "part1", "answer1", "part2", "answer2"])
        self.assertEqual(result["mapping"]["answer"], "answer")
        self.assertEqual(
            result["mapping"]["bonus_parts"],
            [{"question": "part1", "answer": "answer1"}, {"question": "part2", "answer": "answer2"}],
        )

    def test_fuzzy_guess_and_nested_packet_name_as_author(self) -> None:
        result = suggest_mapping(["Categories", "packet.name", "subcategory"])
        self.assertEqual(result["mapping"]["category"], "Categories")
        self.assertEqual(result["confidence"]["category"], "guess")
        self.assertEqual(result["mapping"]["author"], "packet.name")

    def test_unmatched_fields_stay_none(self) -> None:
        self.assertIsNone(suggest_mapping(["zzz"])["mapping"]["answer"])


class CsvMappingTests(unittest.TestCase):
    def test_inspect_reports_columns_and_sample(self) -> None:
        result = inspect_csv(ODD_CSV, "odd.csv")
        self.assertEqual(result["row_count"], 2)
        self.assertIn("Clue Text", result["columns"])
        self.assertEqual(result["sample"][0]["Writer"], "Ann")

    def test_preview_shows_three_tossups_and_three_bonuses(self) -> None:
        header = "Kind,Clue Text,Response,Cat,Sub,Lead,part1,answer1\n"
        rows = "".join(f"tossup,T{i},A,History,US,,,\n" for i in range(10))
        rows += "".join(f"bonus,,,Science,Bio,L{i},P,A\n" for i in range(10))
        sample = inspect_csv(header + rows, "mixed.csv")["sample"]
        self.assertEqual([r["Kind"] for r in sample], ["tossup"] * 3 + ["bonus"] * 3)

    def test_mapped_csv_round_trips_with_authors_and_defaults(self) -> None:
        text = mapped_csv_text(ODD_CSV, ODD_MAPPING, "odd.csv")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.csv"
            path.write_text(text, encoding="utf-8")
            pool = load_question_pool_csv(path)
        self.assertEqual(pool.metadata.name, "odd")
        self.assertEqual(len(pool.tossups), 1)
        self.assertEqual(len(pool.bonuses), 1)
        self.assertEqual(pool.tossups[0].metadata.id, "a1")
        self.assertEqual(pool.tossups[0].metadata.author, "Ann")
        self.assertEqual([p.answer for p in pool.bonuses[0].parts], ["A one", "A two"])
        self.assertEqual(pool.bonuses[0].metadata.author, "Bob")

    def test_missing_required_mapping_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Category"):
            mapped_csv_text(ODD_CSV, {**ODD_MAPPING, "category": None}, "odd.csv")

    def test_unknown_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not found"):
            mapped_csv_text(ODD_CSV, {**ODD_MAPPING, "answer": "Nope"}, "odd.csv")

    def test_row_error_names_the_row(self) -> None:
        bad = ODD_CSV.replace("Tossup answer", "")
        with self.assertRaisesRegex(ValueError, "row 2"):
            mapped_csv_text(bad, ODD_MAPPING, "odd.csv")


class JsonMappingTests(unittest.TestCase):
    DATA = {
        "tossups": [
            {"_id": "t1", "q": "Tossup text", "a": "Answer", "meta": {"cat": "Science", "sub": "Physics"},
             "packet": {"name": "Packet One"}}
        ],
        "bonuses": [
            {"_id": "b1", "intro": "Lead", "parts": ["P1", "P2"], "answers": ["A1", "A2"],
             "meta": {"cat": "History", "sub": "World"}, "packet": {"name": "Packet Two"}}
        ],
    }
    MAPPING = {
        "question": "q", "answer": "a", "category": "meta.cat", "subcategory": "meta.sub",
        "author": "packet.name", "question_id": "_id", "bonus_leadin": "intro",
        "bonus_parts_list": "parts", "bonus_answers_list": "answers",
    }

    def test_inspect_flattens_nested_keys(self) -> None:
        result = inspect_json(json.dumps(self.DATA), "pool.json")
        self.assertIn("meta.cat", result["columns"])
        self.assertEqual(result["suggestion"]["mapping"]["author"], "packet.name")

    def test_mapped_json_parses_with_author(self) -> None:
        text = mapped_pool_json(json.dumps(self.DATA), self.MAPPING, "pool.json")
        pool = parse_question_pool_json(text, "pool.json")
        self.assertEqual(pool.tossups[0].metadata.topic.subcategory, "Physics")
        self.assertEqual(pool.tossups[0].metadata.author, "Packet One")
        self.assertEqual(pool.bonuses[0].metadata.author, "Packet Two")
        self.assertEqual(len(pool.bonuses[0].parts), 2)

    def test_mismatched_part_and_answer_counts_fail(self) -> None:
        data = json.loads(json.dumps(self.DATA))
        data["bonuses"][0]["answers"] = ["only one"]
        with self.assertRaisesRegex(ValueError, "2 parts but 1 answers"):
            mapped_pool_json(json.dumps(data), self.MAPPING, "pool.json")


class WorkspaceMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace(
            templates_dir=tempfile.mkdtemp(), labels_path=Path(tempfile.mkdtemp()) / "labels.jsonl"
        )

    def test_mapped_import_reports_authors(self) -> None:
        summary = self.workspace.import_csv(ODD_CSV, "odd.csv", ODD_MAPPING)
        self.assertEqual((summary["tossup_count"], summary["bonus_count"]), (1, 1))
        self.assertEqual(summary["author_count"], 2)

    def test_bad_mapping_surfaces_workspace_error(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.import_csv(ODD_CSV, "odd.csv", {**ODD_MAPPING, "answer": None})

    def test_inspect_import(self) -> None:
        result = self.workspace.inspect_import(ODD_CSV, "odd.csv", "csv")
        self.assertEqual(result["kind"], "csv")


if __name__ == "__main__":
    unittest.main()
