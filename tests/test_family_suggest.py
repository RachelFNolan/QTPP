import tempfile
import unittest
from pathlib import Path

from packetizer import QuestionMetadata, QuestionSet, QuestionSetMetadata, Topic, Tossup
from packetizer.family_suggest import (
    approve_suggestions,
    get_backend,
    load_labels,
    questions_missing_family,
    save_suggestions,
    suggest_families,
)


def tossup(question_id: str, text: str, alternate: str | None = None, subcategory: str = "Other History"):
    return Tossup(QuestionMetadata(question_id, Topic("History", subcategory, alternate)), text, "answer")


def pool() -> QuestionSet:
    return QuestionSet(
        QuestionSetMetadata("test", "Test", 2025, None),
        (
            tossup("war", "The army besieged the fortress and the general won the battle"),
            tossup("treaty", "The ambassadors negotiated a treaty and alliance after diplomacy"),
            tossup("tagged", "The army fought a battle", alternate="Military"),
            tossup("curated", "The army fought a battle"),
            tossup("bio", "Cells divide by mitosis", subcategory="Biology"),
        ),
    )


LABELS = {
    "Military": ["Military. battle army general fortress siege"],
    "Diplomatic": ["Diplomatic. treaty ambassadors negotiations alliance diplomacy"],
}


class FamilySuggestTests(unittest.TestCase):
    def test_only_questions_without_alternate_or_curated_entry(self) -> None:
        ids = [q.metadata.id for q in questions_missing_family(pool(), {"curated": ["X"]})]
        self.assertEqual(ids, ["war", "treaty", "bio"])
        only_history = questions_missing_family(pool(), subcategories=["other history"])
        self.assertEqual([q.metadata.id for q in only_history], ["war", "treaty", "curated"])

    def test_tfidf_suggests_closest_label_and_flags_unsure(self) -> None:
        result = {
            s.question_id: s
            for s in suggest_families(pool(), LABELS, get_backend("tfidf"), curated={"curated": 1})
        }
        self.assertEqual(result["war"].label, "Military")
        self.assertEqual(result["treaty"].label, "Diplomatic")
        self.assertIsNone(result["bio"].label)
        self.assertIn(result["bio"].best_guess, LABELS)

    def test_custom_similarity_function_is_used(self) -> None:
        def similarity(questions, labels):
            return [[0.9, 0.1] for _ in questions]

        suggestions = suggest_families(pool(), LABELS, similarity)
        self.assertTrue(all(s.label == "Military" for s in suggestions))

    def test_review_round_trip_and_labels_file(self) -> None:
        suggestions = suggest_families(pool(), LABELS, get_backend("tfidf"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.json"
            save_suggestions(suggestions, path)
            approved = approve_suggestions(path)
            self.assertEqual(approved["war"], ["Military"])
            self.assertNotIn("bio", approved)
            labels = Path(directory) / "labels.json"
            labels.write_text('{"labels": {"Military": "battles", "X": ["a", "b"]}}', encoding="utf-8")
            self.assertEqual(load_labels(labels)["X"], ["X. a", "X. b"])
            labels.write_text('{"labels": {"Military": 3}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_labels(labels)

    def test_unknown_backend(self) -> None:
        with self.assertRaises(ValueError):
            get_backend("nope")


if __name__ == "__main__":
    unittest.main()
