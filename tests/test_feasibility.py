import unittest
from pathlib import Path

from qtpp import (
    check_pool_feasibility,
    load_question_pool_csv,
    load_template,
    max_feasible_packets,
)

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "Test Questions" / "2025 ACF Winter Question Pool.csv"
FINAL = ROOT / "templates" / "acf-winter-final.json"


class FeasibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = load_question_pool_csv(POOL)
        self.template = load_template(FINAL)

    def test_sample_pool_supports_sixteen_final_packets(self) -> None:
        self.assertEqual(
            check_pool_feasibility(self.pool, self.template.create_spec(16)), ()
        )
        self.assertEqual(
            max_feasible_packets(self.pool, self.template.create_spec(1)), 16
        )

    def test_reports_selector_shortfalls(self) -> None:
        errors = check_pool_feasibility(self.pool, self.template.create_spec(17))
        self.assertTrue(any("American History" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
