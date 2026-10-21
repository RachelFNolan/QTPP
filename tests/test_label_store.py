from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qtpp.label_store import append_label, label_summary, load_labels, pair_key


class LabelStoreTests(unittest.TestCase):
    def test_pair_key_ignores_order_case_and_spacing(self) -> None:
        self.assertEqual(pair_key("Alpha  beta", "Gamma"), pair_key("gamma", "alpha BETA"))
        self.assertNotEqual(pair_key("a", "b"), pair_key("a", "c"))

    def test_latest_label_wins_and_bad_lines_are_skipped(self) -> None:
        path = Path(tempfile.mkdtemp()) / "labels.jsonl"
        key = pair_key("a", "b")
        append_label(path, key=key, first_id="1", second_id="2", label="similar")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        append_label(path, key=key, first_id="1", second_id="2", label="different")
        labels = load_labels(path)
        self.assertEqual(labels[key]["label"], "different")
        self.assertEqual(label_summary(labels.values())["total"], 1)

    def test_rejects_unknown_label_and_missing_file(self) -> None:
        path = Path(tempfile.mkdtemp()) / "labels.jsonl"
        with self.assertRaises(ValueError):
            append_label(path, key="k", first_id="1", second_id="2", label="maybe")
        self.assertEqual(load_labels(path), {})


if __name__ == "__main__":
    unittest.main()
