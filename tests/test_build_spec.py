import unittest
from dataclasses import replace

from packetizer import (
    AggregateQuota,
    AllowedCountPatterns,
    CategoryQuota,
    CountSelector,
    LeftoverBound,
    PacketBuildSpec,
    validate_distribution,
)
from packetizer.templates import (
    acf_winter_final_template,
    acf_winter_submitted_template,
)


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
        self.assertEqual(len(final_other.patterns), 12)
        self.assertTrue(
            all(
                sum(pattern[index] for index in range(0, len(pattern), 2)) == 1
                and sum(pattern[index] for index in range(1, len(pattern), 2)) == 1
                for pattern in final_other.patterns
            )
        )
        self.assertTrue(
            all(
                pattern.index(1) // 2 != pattern.index(1, pattern.index(1) + 1) // 2
                for pattern in final_other.patterns
            )
        )

    def test_template_rules_are_independently_editable(self) -> None:
        template = acf_winter_final_template()
        edited = replace(template, tossup_capacity=19)
        self.assertEqual(template.tossup_capacity, 20)
        self.assertEqual(edited.create_spec(packet_count=3).packet_count, 3)
        self.assertEqual(edited.create_spec(packet_count=3).tossup_capacity, 19)

    def test_final_other_rule_rejects_same_subcategory_tossup_and_bonus(self) -> None:
        template = acf_winter_final_template()
        spec = template.create_spec(packet_count=1)
        counts = _first_valid_counts(template)
        rule = template.allowed_patterns[0]
        for selector in rule.selectors:
            counts.pop(selector, None)
        counts[CountSelector("tossup", "Geography", "Geography")] = 1
        counts[CountSelector("bonus", "Geography", "Geography")] = 1
        errors = validate_distribution(
            spec,
            (counts,),
            leftovers={"tossup": 0, "bonus": 0},
        )
        self.assertTrue(any("distinct subcategories" in error for error in errors))


def _first_valid_counts(template):
    counts = {
        quota.selector: quota.minimum
        for quota in template.quotas
    }
    for rule in template.allowed_patterns:
        counts.update(zip(rule.selectors, rule.patterns[0]))
    return counts


if __name__ == "__main__":
    unittest.main()
