import json
import tempfile
import unittest
from pathlib import Path

from qtpp import load_question_pool_json, parse_question_pool_json
from qtpp.workspace import Workspace, WorkspaceError

TOSSUP = {
    "_id": "t1",
    "question": "A <b>tossup</b>.",
    "answer": "Answer",
    "category": "History",
    "subcategory": "European History",
    "difficulty": 5,
}
BONUS = {
    "_id": "b1",
    "leadin": "Lead-in",
    "parts": ["p1", "p2", "p3"],
    "answers": ["a1", "a2", "a3"],
    "values": [10, 10, 10],
    "difficultyModifiers": ["e", "m", "h"],
    "category": "Science",
    "subcategory": "Biology",
}
SET = {"_id": "s1", "name": "My Set", "year": 2024}


class PoolJsonImportTests(unittest.TestCase):
    def test_object_with_set_and_no_packets(self) -> None:
        pool = parse_question_pool_json(
            json.dumps({"set": SET, "tossups": [TOSSUP], "bonuses": [BONUS]})
        )
        self.assertEqual(pool.metadata.name, "My Set")
        self.assertEqual(pool.packets, ())
        self.assertEqual(pool.tossups[0].metadata.id, "t1")
        self.assertIn("<b>", pool.tossups[0].question)
        self.assertEqual(len(pool.bonuses[0].parts), 3)

    def test_bare_list_splits_by_shape_and_defaults_set_from_filename(self) -> None:
        pool = parse_question_pool_json(json.dumps([TOSSUP, BONUS]), "my-pool.json")
        self.assertEqual((len(pool.tossups), len(pool.bonuses)), (1, 1))
        self.assertEqual(pool.metadata.name, "my-pool")

    def test_set_taken_from_first_question(self) -> None:
        pool = parse_question_pool_json(json.dumps({"tossups": [{**TOSSUP, "set": SET}]}))
        self.assertEqual(pool.metadata.id, "s1")

    def test_load_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            path.write_text(json.dumps({"tossups": [TOSSUP]}), encoding="utf-8")
            self.assertEqual(len(load_question_pool_json(path).tossups), 1)

    def test_errors_name_file_and_field(self) -> None:
        with self.assertRaisesRegex(ValueError, r"pool\.json.*invalid JSON"):
            parse_question_pool_json("{", "pool.json")
        with self.assertRaisesRegex(ValueError, "no tossups or bonuses"):
            parse_question_pool_json("{}", "pool.json")
        bad = {**TOSSUP}
        del bad["answer"]
        with self.assertRaisesRegex(ValueError, r"pool\.json.*answer"):
            parse_question_pool_json(json.dumps({"tossups": [bad]}), "pool.json")
        with self.assertRaisesRegex(ValueError, "unique"):
            parse_question_pool_json(json.dumps({"tossups": [TOSSUP, TOSSUP]}))

    def test_workspace_import_json(self) -> None:
        workspace = Workspace()
        summary = workspace.import_json(json.dumps({"tossups": [TOSSUP], "bonuses": [BONUS]}), "p.json")
        self.assertEqual((summary["tossup_count"], summary["bonus_count"]), (1, 1))
        with self.assertRaises(WorkspaceError):
            workspace.import_json("[]", "p.json")


if __name__ == "__main__":
    unittest.main()
