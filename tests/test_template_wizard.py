import tempfile
from pathlib import Path
import unittest

from qtpp.feasibility import check_pool_feasibility
from qtpp.template_json import template_from_dict, template_to_dict
from qtpp.template_wizard import suggest_template
from qtpp.workspace import DEFAULT_DEMO, Workspace, WorkspaceError
from qtpp import load_question_pool_csv


class TemplateWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = load_question_pool_csv(DEFAULT_DEMO)

    def test_suggestion_fills_capacity_and_is_feasible(self) -> None:
        template = suggest_template(
            self.pool, name="T", packet_count=10, tossup_capacity=20, bonus_capacity=20, tolerance=1
        )
        for question_type in ("tossup", "bonus"):
            quotas = [q for q in template.quotas if q.selector.question_type == question_type]
            self.assertGreater(len(quotas), 1)
            self.assertTrue(all(q.maximum - q.minimum <= 2 for q in quotas))
        self.assertEqual(check_pool_feasibility(self.pool, template.create_spec(10)), ())
        round_trip = template_from_dict(template_to_dict(template))
        self.assertEqual(round_trip, template)

    def test_targets_sum_to_capacity(self) -> None:
        template = suggest_template(
            self.pool, name="T", packet_count=5, tossup_capacity=20, bonus_capacity=18, tolerance=0
        )
        for question_type, capacity in (("tossup", 20), ("bonus", 18)):
            total = sum(q.minimum for q in template.quotas if q.selector.question_type == question_type)
            self.assertEqual(total, capacity)

    def test_rejects_bad_input(self) -> None:
        with self.assertRaises(ValueError):
            suggest_template(self.pool, name="T", packet_count=0, tossup_capacity=1, bonus_capacity=1)


class WorkspaceFeasibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace(templates_dir=tempfile.mkdtemp(), labels_path=Path(tempfile.mkdtemp()) / "labels.jsonl")
        self.workspace.import_demo()

    def test_suggest_then_feasibility(self) -> None:
        template = self.workspace.suggest_template(
            {"packet_count": 5, "tossup_capacity": 20, "bonus_capacity": 20}
        )["template"]
        result = self.workspace.feasibility(template, 5)
        self.assertTrue(result["feasible"])
        self.assertGreaterEqual(result["max_packets"], 5)
        self.assertTrue(all(row["ok"] for row in result["requirements"]))

    def test_infeasible_reports_shortfalls(self) -> None:
        template = self.workspace.suggest_template(
            {"packet_count": 5, "tossup_capacity": 20, "bonus_capacity": 20}
        )["template"]
        result = self.workspace.feasibility(template, 500)
        self.assertFalse(result["feasible"])
        self.assertTrue(result["errors"])
        self.assertTrue(any(not row["ok"] for row in result["requirements"]))

    def test_validation_errors(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.feasibility({"schema_version": 1}, 1)
        with self.assertRaises(WorkspaceError):
            self.workspace.suggest_template({"packet_count": 0, "tossup_capacity": 1, "bonus_capacity": 1})


if __name__ == "__main__":
    unittest.main()
