import tempfile
import unittest
from pathlib import Path

from qtpp import (
    FamilyPenaltyScorer,
    QuestionMetadata,
    QuestionSet,
    QuestionSetMetadata,
    SimilarityWeights,
    TfidfSimilarity,
    Topic,
    Tossup,
    build_similarity,
    load_curated_families,
    load_question_pool_csv,
    question_families,
)
from qtpp.similarity import CombinedSimilarity, primary_answer

POOL = Path(__file__).resolve().parents[1] / "Test Questions" / "2025 ACF Winter Question Pool.csv"


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
    def test_family_penalty_uses_alternate_subcategory_and_skips_catch_alls(self) -> None:
        def tossup(question_id, alternate):
            return Tossup(
                QuestionMetadata(question_id, Topic("Science", "Other Science", alternate)),
                "q",
                "a",
            )

        questions = [
            tossup("m1", "Math"),
            tossup("m2", "math"),
            tossup("c1", "Computer Science"),
            tossup("x1", "Misc Literature"),
            tossup("x2", "Misc Literature"),
            tossup("n1", None),
        ]
        families = question_families(questions)
        self.assertEqual(families["m1"], families["m2"])
        self.assertEqual(families["x1"], frozenset())
        self.assertEqual(families["n1"], frozenset())

        class Constant:
            def score(self, first_id: str, second_id: str) -> float:
                return 0.1

        scorer = FamilyPenaltyScorer(Constant(), families, 0.5)
        self.assertAlmostEqual(scorer.score("m1", "m2"), 0.6)
        self.assertAlmostEqual(scorer.score("m1", "c1"), 0.1)
        self.assertAlmostEqual(scorer.score("x1", "x2"), 0.1)
        self.assertAlmostEqual(FamilyPenaltyScorer(Constant(), families, 0.95).score("m1", "m2"), 1.0)
        with self.assertRaises(ValueError):
            FamilyPenaltyScorer(Constant(), families, -1)

    def test_curated_families_override_and_load(self) -> None:
        questions = [
            Tossup(QuestionMetadata("a", Topic("History", "Other History")), "q", "a"),
            Tossup(QuestionMetadata("b", Topic("History", "Other History")), "q", "a"),
            Tossup(QuestionMetadata("c", Topic("Science", "Other Science", "Math")), "q", "a"),
        ]
        families = question_families(questions, {"a": ["Military"], "b": ["military"], "c": []})
        self.assertEqual(families["a"], families["b"])
        self.assertEqual(families["c"], frozenset())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "families.json"
            path.write_text('{"families": {"a": ["Military"]}}', encoding="utf-8")
            self.assertEqual(load_curated_families(path), {"a": ["Military"]})
            path.write_text('{"families": {"a": "Military"}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_curated_families(path)

    def test_build_similarity_penalty_is_opt_in(self) -> None:
        pool = load_question_pool_csv(POOL)
        math = [
            q.metadata.id
            for q in (*pool.tossups, *pool.bonuses)
            if q.metadata.topic.alternate_subcategory == "Math"
        ]
        plain = build_similarity(pool)
        penalized = build_similarity(pool, family_penalty=0.3)
        self.assertAlmostEqual(plain.score(math[0], math[1]) + 0.3, penalized.score(math[0], math[1]))
        other = next(
            q.metadata.id for q in pool.tossups if q.metadata.topic.alternate_subcategory != "Math"
        )
        self.assertAlmostEqual(plain.score(math[0], other), penalized.score(math[0], other))

    def test_theme_penalty_links_different_categories_by_family_or_keyword(self) -> None:
        def tossup(question_id, category, alternate, text):
            return Tossup(
                QuestionMetadata(question_id, Topic(category, "Sub", alternate)), text, "a"
            )

        pool = QuestionSet(
            QuestionSetMetadata("t", "t", 2025, None),
            (
                tossup("rel", "Religion", "Hinduism", "Describe this faith."),
                tossup("lit", "Literature", None, "The Ramayana tells of Rama."),
                tossup("lit2", "Literature", None, "A play about a Danish prince."),
                tossup("rel2", "Religion", None, "Describe this other faith."),
            ),
        )
        plain = build_similarity(pool, SimilarityWeights(0, 0, 0.0001))
        themed = build_similarity(pool, SimilarityWeights(0, 0, 0.0001), theme_penalty=0.2)
        self.assertAlmostEqual(plain.score("rel", "lit") + 0.2, themed.score("rel", "lit"))
        self.assertAlmostEqual(plain.score("lit2", "rel2"), themed.score("lit2", "rel2"))
        self.assertAlmostEqual(plain.score("lit", "lit2"), themed.score("lit", "lit2"))


if __name__ == "__main__":
    unittest.main()
