from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qtpp.label_store import load_labels
from qtpp.review_marks import active_marks, append_mark, load_marks
from qtpp.workspace import Workspace, WorkspaceError
from tests.test_workspace import tiny_pool, tiny_template


class ReviewMarkStoreTests(unittest.TestCase):
    def test_latest_record_wins_and_removed_marks_are_hidden(self) -> None:
        path = Path(tempfile.mkdtemp()) / "marks.jsonl"
        first = append_mark(path, question_id="a", other_id="b", note="overlap", pool="p")
        append_mark(path, question_id="a", other_id="b", note="fixed", pool="p", mark_id=first["mark_id"], status="resolved")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        gone = append_mark(path, question_id="c", pool="p")
        append_mark(path, question_id="c", pool="p", mark_id=gone["mark_id"], status="removed")
        append_mark(path, question_id="d", pool="other")
        marks = active_marks(path, "p")
        self.assertEqual([(m["question_id"], m["status"], m["note"]) for m in marks], [("a", "resolved", "fixed")])
        self.assertEqual(len(load_marks(path)), 3)

    def test_rejects_bad_input(self) -> None:
        path = Path(tempfile.mkdtemp()) / "marks.jsonl"
        with self.assertRaises(ValueError):
            append_mark(path, question_id="a", other_id="a")
        with self.assertRaises(ValueError):
            append_mark(path, question_id="a", note="x" * 501)
        with self.assertRaises(ValueError):
            append_mark(path, question_id="a", status="done")


class WorkspaceMarkTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = Path(tempfile.mkdtemp())
        self.labels = directory / "labels.jsonl"
        self.workspace = Workspace(templates_dir=tempfile.mkdtemp(), labels_path=self.labels)
        self.workspace._set_pool(tiny_pool())

    def test_create_update_resolve_remove(self) -> None:
        saved = self.workspace.save_mark({"question_id": "tu-1", "other_id": "b-1", "note": "same topic"})
        mark_id = saved["mark"]["mark_id"]
        self.assertEqual(saved["marks"][0]["note"], "same topic")
        edited = self.workspace.save_mark({"mark_id": mark_id, "note": "still same", "other_id": None})
        self.assertEqual((edited["marks"][0]["note"], edited["marks"][0]["other_id"]), ("still same", None))
        resolved = self.workspace.save_mark({"mark_id": mark_id, "status": "resolved"})
        self.assertEqual(resolved["marks"][0]["status"], "resolved")
        self.assertEqual(resolved["marks"][0]["question_id"], "tu-1")
        self.assertEqual(self.workspace.save_mark({"mark_id": mark_id, "status": "removed"})["marks"], [])
        self.assertEqual(self.workspace.list_marks()["marks"], [])

    def test_validates_ids(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mark({"question_id": "missing"})
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mark({"question_id": "tu-1", "other_id": "tu-1"})
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mark({"question_id": "tu-1", "other_id": "missing"})
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mark({"mark_id": "nope", "note": "x"})
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mark({"question_id": "tu-1", "note": "x" * 501})

    def test_also_label_records_distinct_source(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mark({"question_id": "tu-1", "also_label": "similar"})
        self.workspace.save_mark({"question_id": "tu-1", "other_id": "b-1", "also_label": "similar"})
        labels = list(load_labels(self.labels).values())
        self.assertEqual([(l["label"], l["source"]) for l in labels], [("similar", "review-mark")])

    def test_audit_includes_marks(self) -> None:
        self.workspace.generate(
            {"template": tiny_template(), "packet_count": 1, "solvers": ["baseline"], "similarities": ["balanced-tfidf"]}
        )
        self.workspace.save_mark({"question_id": "tu-1", "note": "check"})
        audit = self.workspace.audit("too much 20th century material")
        self.assertEqual([m["note"] for m in audit["marks"]], ["check"])


if __name__ == "__main__":
    unittest.main()
