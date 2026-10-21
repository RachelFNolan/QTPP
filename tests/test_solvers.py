import unittest
from pathlib import Path

from qtpp import (
    InfeasibleError,
    build_similarity,
    load_question_pool_csv,
    load_template,
    solve_baseline,
    solve_cpsat,
)
from qtpp.cpsat_solver import cp_model
from qtpp.scoring import PacketLayout, SoftWeights, placement_penalty, score_packet

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "Test Questions" / "2025 ACF Winter" / "Question Pool.csv"
TEMPLATE = ROOT / "templates" / "acf-winter-final.json"
FALL_POOL = ROOT / "Test Questions" / "2025 ACF Fall" / "Question Pool.csv"
FALL_TEMPLATE = ROOT / "templates" / "acf-fall-final.json"


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

    def test_separation_window_is_enforced_and_reported(self) -> None:
        from dataclasses import replace
        from qtpp.build_spec import TossupBonusSeparation
        from qtpp.solving import PoolIndex, separation_conflicts, validate_layouts

        index = PoolIndex.from_pool(self.pool)
        for sep in (
            TossupBonusSeparation(2),
            TossupBonusSeparation(1, by_category=False, by_subcategory=True),
        ):
            spec = replace(self.template.create_spec(4), separation=sep)
            result = solve_baseline(self.pool, spec, self.scorer, seed=3, iterations=500)
            self.assertEqual(result.hard_errors, ())
            for layout in result.layouts:
                self.assertEqual(
                    separation_conflicts(layout.tossups, layout.bonuses, index.selector_of, sep), []
                )
        # An impossible window is reported, not raised.
        spec = replace(self.template.create_spec(4), separation=TossupBonusSeparation(40))
        result = solve_baseline(self.pool, spec, self.scorer, seed=3, iterations=100)
        self.assertTrue(any("within a window" in e for e in result.hard_errors))

    def test_separation_spec_and_json_round_trip(self) -> None:
        from dataclasses import replace
        from qtpp.build_spec import TossupBonusSeparation
        from qtpp.template_json import template_from_dict, template_to_dict

        with self.assertRaises(ValueError):
            TossupBonusSeparation(0)
        with self.assertRaises(ValueError):
            TossupBonusSeparation(3, by_category=False, by_subcategory=False)
        template = replace(self.template, separation=TossupBonusSeparation(3, True, True))
        self.assertEqual(template_from_dict(template_to_dict(template)), template)
        self.assertIsNone(template_from_dict(template_to_dict(self.template)).separation)

    def test_baseline_reports_infeasible_requests(self) -> None:
        with self.assertRaises(InfeasibleError):
            solve_baseline(self.pool, self.template.create_spec(40), self.scorer)

    def test_baseline_supports_grouped_fall_distribution(self) -> None:
        pool = load_question_pool_csv(FALL_POOL)
        template = load_template(FALL_TEMPLATE)
        result = solve_baseline(
            pool, template.create_spec(4), build_similarity(pool), seed=5, iterations=500
        )
        self.assertEqual(result.hard_errors, ())

    @unittest.skipIf(cp_model is None, "ortools not installed")
    def test_cpsat_meets_hard_rules(self) -> None:
        result = solve_cpsat(
            self.pool, self.template.create_spec(4), self.scorer, time_limit=10
        )
        self.assertEqual(result.hard_errors, ())

    @unittest.skipIf(cp_model is None, "ortools not installed")
    def test_cpsat_supports_grouped_fall_distribution(self) -> None:
        pool = load_question_pool_csv(FALL_POOL)
        template = load_template(FALL_TEMPLATE)
        result = solve_cpsat(
            pool,
            template.create_spec(4),
            build_similarity(pool),
            time_limit=10,
            top_pairs=300,
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
