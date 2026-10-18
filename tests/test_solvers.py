import unittest
from pathlib import Path

from packetizer import (
    InfeasibleError,
    build_similarity,
    load_question_pool_csv,
    load_template,
    solve_baseline,
    solve_cpsat,
)
from packetizer.cpsat_solver import cp_model
from packetizer.scoring import PacketLayout, SoftWeights, placement_penalty, score_packet

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "Test Questions" / "2025 ACF Winter" / "Question Pool.csv"
TEMPLATE = ROOT / "templates" / "acf-winter-final.json"


class SolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = load_question_pool_csv(POOL)
        cls.template = load_template(TEMPLATE)
        cls.scorer = build_similarity(cls.pool)

    def test_baseline_meets_hard_rules_and_is_repeatable(self) -> None:
        spec = self.template.create_spec(4)
        first = solve_baseline(self.pool, spec, self.scorer, seed=3, iterations=500)
        again = solve_baseline(self.pool, spec, self.scorer, seed=3, iterations=500)
        self.assertEqual(first.hard_errors, ())
        self.assertEqual(first.layouts, again.layouts)
        used = [q for layout in first.layouts for q in (*layout.tossups, *layout.bonuses)]
        self.assertEqual(len(used), len(set(used)))

    def test_baseline_reports_infeasible_requests(self) -> None:
        with self.assertRaises(InfeasibleError):
            solve_baseline(self.pool, self.template.create_spec(40), self.scorer)

    @unittest.skipIf(cp_model is None, "ortools not installed")
    def test_cpsat_meets_hard_rules(self) -> None:
        result = solve_cpsat(
            self.pool, self.template.create_spec(4), self.scorer, time_limit=10
        )
        self.assertEqual(result.hard_errors, ())

    def test_placement_penalty_matches_full_score(self) -> None:
        categories = {"a": "X", "b": "X", "c": "Y"}

        class Scorer:
            def score(self, first, second):
                return 0.5

        weights = SoftWeights()
        scorer = Scorer()
        before = score_packet(PacketLayout(("a", "c"), ()), categories, scorer, weights)
        after = score_packet(PacketLayout(("b", "c"), ()), categories, scorer, weights)
        delta = placement_penalty(
            ["a", "c"], [], True, 0, "b", categories, scorer, weights
        ) - placement_penalty(["a", "c"], [], True, 0, "a", categories, scorer, weights)
        self.assertAlmostEqual(delta, after.total - before.total)


if __name__ == "__main__":
    unittest.main()
