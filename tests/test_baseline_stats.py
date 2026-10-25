from __future__ import annotations

import unittest
from pathlib import Path

from qtpp import SoftWeights, load_question_pool_csv
from qtpp.baseline_stats import (
    BaselineStat,
    baseline_stats,
    normalize,
    sample_random_layouts,
)
from qtpp.generation import generate_packets
from qtpp.model import QuestionSet
from qtpp.similarity import SimilarityWeights, build_similarity
from qtpp.template_json import load_template

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "Test Questions" / "2025 ACF Winter Question Pool.csv"


class BaselineStatTests(unittest.TestCase):
    def test_improvement_and_z_score(self) -> None:
        stat = BaselineStat(mean=10.0, stdev=2.0, samples=5)
        self.assertAlmostEqual(stat.improvement(10.0), 0.0)
        self.assertAlmostEqual(stat.improvement(4.0), 0.6)
        self.assertLess(stat.improvement(12.0), 0)
        self.assertAlmostEqual(stat.z_score(6.0), 2.0)

    def test_degenerate_baseline_does_not_divide_by_zero(self) -> None:
        stat = BaselineStat(mean=0.0, stdev=0.0, samples=3)
        self.assertEqual(stat.improvement(1.0), 0.0)
        self.assertEqual(stat.z_score(1.0), 0.0)

    def test_normalize_referee_is_mean_of_improvements(self) -> None:
        stats = {"a": BaselineStat(10, 1, 3), "b": BaselineStat(20, 1, 3)}
        result = normalize({"a": 5.0, "b": 10.0}, stats)
        self.assertAlmostEqual(result["referee"], 0.5)

    def test_sample_count_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            sample_random_layouts(None, None, 0)  # type: ignore[arg-type]


@unittest.skipUnless(POOL.exists(), "sample pool unavailable")
class RandomBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool: QuestionSet = load_question_pool_csv(POOL)
        entries = sorted((ROOT / "templates").glob("acf-winter-final.json"))
        cls.spec = load_template(entries[0]).create_spec(2)
        cls.scorer = build_similarity(cls.pool, SimilarityWeights())

    def test_deterministic_and_optimizer_beats_random(self) -> None:
        first = sample_random_layouts(self.pool, self.spec, 5, seed=3)
        second = sample_random_layouts(self.pool, self.spec, 5, seed=3)
        self.assertEqual(first, second)
        stats = baseline_stats(self.pool, first, {"s": self.scorer})["s"]
        built = generate_packets(self.pool, self.spec, self.scorer, SoftWeights(), seed=3)
        self.assertGreater(stats.improvement(built.report.score.total), 0.0)


if __name__ == "__main__":
    unittest.main()
