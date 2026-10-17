import unittest
from dataclasses import replace
from pathlib import Path

from packetizer import (
    AggregateQuota,
    AllowedCountPatterns,
    CategoryCountRule,
    CategoryQuota,
    CountSelector,
    LeftoverBound,
    PacketBuildSpec,
    validate_distribution,
)
from packetizer import load_template

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def acf_winter_final_template():
    return load_template(TEMPLATES / "acf-winter-final.json")


def acf_winter_submitted_template():
    return load_template(TEMPLATES / "acf-winter-submitted.json")


def acf_fall_final_template():
    return load_template(TEMPLATES / "acf-fall-final.json")


class PacketBuildSpecTests(unittest.TestCase):
    def test_validates_packet_counts_quotas_aggregates_and_leftovers(self) -> None:
        history = CountSelector("tossup", "History")
        spec = PacketBuildSpec(
            packet_count=2,
            tossup_capacity=2,
            bonus_capacity=1,
            quotas=(CategoryQuota(history, minimum=1, maximum=2),),
            aggregate_quotas=(AggregateQuota(history, minimum=3, maximum=3),),
            leftover_bounds=(
                LeftoverBound("tossup", minimum=1, maximum=1),
                LeftoverBound("bonus", minimum=0, maximum=0),
            ),
        )
        packets = (
            {
                CountSelector("tossup", "History", "American History"): 1,
                CountSelector("tossup", "Science", "Biology"): 1,
                CountSelector("bonus", "History", "World History"): 1,
            },
            {
                CountSelector("tossup", "History", "World History"): 2,
                CountSelector("bonus", "Science", "Biology"): 1,
            },
        )
        self.assertEqual(
            validate_distribution(
                spec,
                packets,
                leftovers={"tossup": 1, "bonus": 0},
            ),
            (),
        )

        errors = validate_distribution(
            spec,
            (packets[0], {CountSelector("tossup", "History", "World History"): 1}),
            leftovers={"tossup": 0, "bonus": 1},
        )
        self.assertTrue(any("expected 1 bonuses" in error for error in errors))
        self.assertTrue(any("aggregate count" in error for error in errors))
        self.assertTrue(any("leftovers" in error for error in errors))

    def test_rejects_invalid_specification_and_patterns(self) -> None:
        with self.assertRaisesRegex(ValueError, "packet_count must be a positive integer"):
            PacketBuildSpec(packet_count=0, tossup_capacity=0, bonus_capacity=0)
        with self.assertRaisesRegex(ValueError, "minimum cannot exceed maximum"):
            CategoryQuota(CountSelector("bonus", "History"), minimum=2, maximum=1)
        with self.assertRaisesRegex(ValueError, "match the selector count"):
            AllowedCountPatterns(
                name="invalid",
                selectors=(CountSelector("bonus", "History"),),
                patterns=((1, 0),),
            )
        with self.assertRaisesRegex(ValueError, "categories must be unique"):
            CategoryCountRule(
                name="invalid",
                categories=("History", "History"),
                tossup_count=1,
                bonus_count=1,
            )

    def test_acf_winter_templates_have_published_capacities_and_patterns(self) -> None:
        submitted = acf_winter_submitted_template()
        final = acf_winter_final_template()
        self.assertEqual((submitted.tossup_capacity, submitted.bonus_capacity), (24, 24))
        self.assertEqual((final.tossup_capacity, final.bonus_capacity), (20, 20))

        submitted_spec = submitted.create_spec(packet_count=1)
        final_spec = final.create_spec(packet_count=1)
        self.assertEqual(validate_distribution(
            submitted_spec, (_first_valid_counts(submitted),), {"tossup": 0, "bonus": 0}
        ), ())
        self.assertEqual(validate_distribution(
            final_spec, (_first_valid_counts(final),), {"tossup": 0, "bonus": 0}
        ), ())

        submitted_other = next(
            rule for rule in submitted.allowed_patterns
            if "Other distribution" in rule.name
        )
        self.assertEqual(len(submitted_other.patterns), 6)
        self.assertTrue(
            all(sum(pattern[index] for index in range(0, len(pattern), 2)) == 2
                and sum(pattern[index] for index in range(1, len(pattern), 2)) == 2
                for pattern in submitted_other.patterns)
        )

        final_other = final.allowed_patterns[0]
        self.assertIsInstance(final_other, CategoryCountRule)
        self.assertEqual(
            final_other.categories,
            ("Geography", "Current Events", "Pop Culture", "Other Academic"),
        )
        self.assertEqual((final_other.tossup_count, final_other.bonus_count), (1, 1))
        self.assertTrue(final_other.distinct_categories)

    def test_acf_fall_final_template_allows_only_three_flexible_questions_each(self) -> None:
        template = acf_fall_final_template()
        self.assertEqual((template.tossup_capacity, template.bonus_capacity), (20, 20))
        rule = template.allowed_patterns[0]
        self.assertEqual(len(rule.patterns), 48)
        self.assertTrue(
            all(
                sum(pattern[0::2]) == 3 and sum(pattern[1::2]) == 3
                for pattern in rule.patterns
            )
        )
        self.assertEqual(
            validate_distribution(
                template.create_spec(packet_count=1),
                (_first_valid_counts(template),),
                {"tossup": 0, "bonus": 0},
            ),
            (),
        )

    def test_template_rules_are_independently_editable(self) -> None:
        template = acf_winter_final_template()
        edited = replace(template, tossup_capacity=19)
        self.assertEqual(template.tossup_capacity, 20)
        self.assertEqual(edited.create_spec(packet_count=3).packet_count, 3)
        self.assertEqual(edited.create_spec(packet_count=3).tossup_capacity, 19)

    def test_final_other_rule_rejects_two_questions_from_same_category(self) -> None:
        template = acf_winter_final_template()
        spec = template.create_spec(packet_count=1)
        counts = _first_valid_counts(template)
        rule = template.allowed_patterns[0]
        for selector in tuple(counts):
            if selector.category in rule.categories:
                del counts[selector]
        counts[CountSelector("tossup", "Geography", "Physical Geography")] = 1
        counts[CountSelector("bonus", "Geography", "Human Geography")] = 1
        errors = validate_distribution(
            spec,
            (counts,),
            leftovers={"tossup": 0, "bonus": 0},
        )
        self.assertTrue(any("distinct categories" in error for error in errors))

    def test_final_other_rule_accepts_different_categories(self) -> None:
        template = acf_winter_final_template()
        counts = _first_valid_counts(template)
        rule = template.allowed_patterns[0]
        for selector in tuple(counts):
            if selector.category in rule.categories:
                del counts[selector]
        counts[CountSelector("tossup", "Geography", "Physical Geography")] = 1
        counts[CountSelector("bonus", "Current Events", "International")] = 1
        self.assertEqual(
            validate_distribution(
                template.create_spec(packet_count=1),
                (counts,),
                leftovers={"tossup": 0, "bonus": 0},
            ),
            (),
        )


def _first_valid_counts(template):
    counts = {
        quota.selector: quota.minimum
        for quota in template.quotas
    }
    for rule in template.allowed_patterns:
        if isinstance(rule, AllowedCountPatterns):
            counts.update(zip(rule.selectors, rule.patterns[0]))
        else:
            counts[CountSelector("tossup", rule.categories[0], rule.categories[0])] = (
                rule.tossup_count
            )
            bonus_category = rule.categories[-1]
            if rule.distinct_categories and rule.tossup_count:
                bonus_category = rule.categories[1 % len(rule.categories)]
            counts[CountSelector("bonus", bonus_category, bonus_category)] = (
                rule.bonus_count
            )
    return counts


if __name__ == "__main__":
    unittest.main()
