import unittest
from pathlib import Path

from packetizer import (
    SimilarityWeights,
    TfidfSimilarity,
    build_similarity,
    load_question_pool_csv,
)
from packetizer.similarity import CombinedSimilarity, primary_answer

POOL = Path(__file__).resolve().parents[1] / "Test Questions" / "2025 ACF Winter" / "Question Pool.csv"


class SimilarityTests(unittest.TestCase):
    def test_tfidf_ranks_shared_vocabulary_higher_and_is_symmetric(self) -> None:
        model = TfidfSimilarity(
            {
                "a": "Napoleon crossed the Alps before the battle of Marengo",
                "b": "Napoleon fought at Marengo after crossing the Alps",
                "c": "Mitochondria produce ATP through oxidative phosphorylation",
            }
        )
        self.assertGreater(model.score("a", "b"), model.score("a", "c"))
        self.assertAlmostEqual(model.score("a", "b"), model.score("b", "a"))
        self.assertAlmostEqual(model.score("a", "a"), 1.0)
        self.assertEqual(model.score("a", "c"), 0.0)

    def test_combined_score_adds_topic_agreement_within_unit_interval(self) -> None:
        text = TfidfSimilarity({"a": "alpha beta", "b": "gamma delta", "c": "gamma delta"})
        topics = {
            "a": ("History", "World History", None),
            "b": ("History", "World History", None),
            "c": ("Science", "Biology", None),
        }
        combined = CombinedSimilarity(text, topics, SimilarityWeights(0.5, 0.3, 0.2))
        self.assertAlmostEqual(combined.score("a", "b"), 0.5)
        self.assertAlmostEqual(combined.score("b", "c"), 0.5)
        self.assertAlmostEqual(combined.score("a", "c"), 0.0)

    def test_primary_answer_drops_alternates(self) -> None:
        self.assertEqual(primary_answer("Greece [or Hellenic Republic] (note)"), "Greece")

    def test_builds_scorer_for_sample_pool(self) -> None:
        pool = load_question_pool_csv(POOL)
        scorer = build_similarity(pool)
        first, second = pool.tossups[0].metadata.id, pool.bonuses[0].metadata.id
        self.assertTrue(0.0 <= scorer.score(first, second) <= 1.0)
        self.assertAlmostEqual(scorer.score(first, first), 1.0)

    def test_custom_text_scorer_replaces_tfidf(self) -> None:
        class Constant:
            def score(self, first_id: str, second_id: str) -> float:
                return 1.0

        pool = load_question_pool_csv(POOL)
        scorer = build_similarity(pool, SimilarityWeights(1, 0, 0), text_scorer=Constant())
        first, second = pool.tossups[0].metadata.id, pool.tossups[1].metadata.id
        self.assertAlmostEqual(scorer.score(first, second), 1.0)


if __name__ == "__main__":
    unittest.main()
