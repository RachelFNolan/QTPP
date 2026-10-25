from __future__ import annotations

import unittest

from qtpp import cpsat_solver
from qtpp.build_spec import CategoryCountGroup, CategoryGroupCountRule, CountSelector, PacketBuildSpec, validate_distribution
from qtpp.model import (
    Bonus,
    BonusPart,
    QuestionMetadata,
    QuestionSet,
    QuestionSetMetadata,
    Topic,
    Tossup,
)
from qtpp.template_json import template_from_dict, template_to_dict

CATEGORIES = ("Religion", "Mythology", "Geography", "Current Events", "Other Academic")
OTHER = ("Geography", "Current Events", "Other Academic")


def pool() -> QuestionSet:
    tossups, bonuses = [], []
    for category in CATEGORIES:
        for number in range(10):
            topic = Topic(category, category)
            tossups.append(Tossup(QuestionMetadata(f"t-{category}-{number}", topic), f"{category} tu {number}", "a"))
            bonuses.append(
                Bonus(
                    QuestionMetadata(f"b-{category}-{number}", topic),
                    f"{category} lead {number}",
                    (BonusPart(1, "p", "a", 10, "e"),),
                )
            )
    return QuestionSet(QuestionSetMetadata("s", "Set", 2026, True), tuple(tossups), tuple(bonuses))


def template(**other_group) -> dict:
    group = {"categories": list(OTHER), "total": 3, "minimum_per_type": 1}
    group.update(other_group)
    rule = {
        "name": "Other",
        "counts": {"tossup": 3, "bonus": 3},
        "groups": [{"categories": ["Religion", "Mythology"], "total": 3, "minimum_per_type": 1}, group],
    }
    return {
        "schema_version": 1,
        "name": "t",
        "tossup_capacity": 3,
        "bonus_capacity": 3,
        "quotas": [],
        "allowed_patterns": [rule],
        "leftover_bounds": [],
    }


def spec_group(**kwargs) -> PacketBuildSpec:
    group = CategoryCountGroup(OTHER, 3, 1, **kwargs)
    other = CategoryCountGroup(("Religion", "Mythology"), 3, 1)
    rule = CategoryGroupCountRule("Other", 3, 3, (other, group))
    return PacketBuildSpec(1, 3, 3, allowed_patterns=(rule,))


def counts(*items: tuple[str, str, int]) -> dict[CountSelector, int]:
    return {CountSelector(kind, category, category): count for kind, category, count in items}


BASE = (("tossup", "Religion", 1), ("bonus", "Religion", 1), ("bonus", "Mythology", 1))


class ValidationTests(unittest.TestCase):
    def errors(self, spec, *items) -> tuple[str, ...]:
        return validate_distribution(spec, [counts(*BASE, *items)], {"tossup": 0, "bonus": 0})

    def test_disjoint_types_rejects_shared_category(self) -> None:
        spec = spec_group(disjoint_types=True)
        shared = (("tossup", "Geography", 1), ("tossup", "Current Events", 1), ("bonus", "Geography", 1))
        self.assertTrue(any("both" in e for e in self.errors(spec, *shared)))
        split = (("tossup", "Geography", 1), ("tossup", "Current Events", 1), ("bonus", "Other Academic", 1))
        self.assertEqual(self.errors(spec, *split), ())

    def test_distinct_category_bounds(self) -> None:
        spec = spec_group(minimum_distinct_categories=2, maximum_distinct_categories=2)
        three = (("tossup", "Geography", 1), ("tossup", "Current Events", 1), ("bonus", "Other Academic", 1))
        two = (("tossup", "Geography", 1), ("tossup", "Current Events", 1), ("bonus", "Geography", 1))
        self.assertTrue(any("different categories" in e for e in self.errors(spec, *three)))
        self.assertEqual(self.errors(spec, *two), ())

    def test_invalid_group_settings(self) -> None:
        with self.assertRaises(ValueError):
            CategoryCountGroup(OTHER, 3, 1, minimum_distinct_categories=4)
        with self.assertRaises(ValueError):
            CategoryCountGroup(OTHER, 3, 1, minimum_distinct_categories=3, maximum_distinct_categories=2)

    def test_template_json_round_trips(self) -> None:
        data = template(minimum_distinct_categories=2, maximum_distinct_categories=2, disjoint_types=True)
        parsed = template_from_dict(data)
        group = parsed.allowed_patterns[0].groups[1]
        self.assertEqual((group.minimum_distinct_categories, group.maximum_distinct_categories, group.disjoint_types), (2, 2, True))
        self.assertEqual(template_from_dict(template_to_dict(parsed)), parsed)


class SolverTests(unittest.TestCase):
    def generate(self, solver: str, data: dict) -> list[list[tuple[str, str]]]:
        from qtpp.baseline_solver import solve_baseline
        from qtpp.similarity import build_similarity

        question_pool = pool()
        spec = template_from_dict(data).create_spec(5)
        scorer = build_similarity(question_pool)
        if solver == "baseline":
            result = solve_baseline(question_pool, spec, scorer, iterations=200)
        else:
            result = cpsat_solver.solve_cpsat(question_pool, spec, scorer, time_limit=3, top_pairs=100)
        self.assertEqual(result.hard_errors, ())
        kinds = {q.metadata.id: ("tossup", q.metadata.topic.category) for q in question_pool.tossups}
        kinds.update({q.metadata.id: ("bonus", q.metadata.topic.category) for q in question_pool.bonuses})
        return [[kinds[q] for q in (*layout.tossups, *layout.bonuses)] for layout in result.layouts]

    def check(self, solver: str) -> None:
        for settings, predicate in (
            (
                {"disjoint_types": True},
                lambda g: not {c for t, c in g if t == "tossup"} & {c for t, c in g if t == "bonus"},
            ),
            ({"minimum_distinct_categories": 2, "maximum_distinct_categories": 2}, lambda g: len({c for _, c in g}) == 2),
            ({"minimum_distinct_categories": 3}, lambda g: len({c for _, c in g}) == 3),
        ):
            for packet in self.generate(solver, template(**settings)):
                group = [(t, c) for t, c in packet if c in OTHER]
                self.assertEqual(len(group), 3)
                self.assertTrue(predicate(group), (solver, settings, group))

    def test_baseline_honors_distinct_and_disjoint(self) -> None:
        self.check("baseline")

    @unittest.skipIf(cpsat_solver.cp_model is None, "ortools not installed")
    def test_cpsat_honors_distinct_and_disjoint(self) -> None:
        self.check("cpsat")


if __name__ == "__main__":
    unittest.main()
