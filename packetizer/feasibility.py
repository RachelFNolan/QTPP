from __future__ import annotations

from collections import Counter

from .build_spec import (
    CategoryGroupCountRule,
    CategoryCountRule,
    CountSelector,
    PacketBuildSpec,
    QUESTION_TYPES,
)
from .model import QuestionSet


def pool_counts(pool: QuestionSet) -> Counter[CountSelector]:
    """Count pool questions by exact type/category/subcategory selector."""
    counts: Counter[CountSelector] = Counter()
    for question_type, questions in (("tossup", pool.tossups), ("bonus", pool.bonuses)):
        for question in questions:
            topic = question.metadata.topic
            counts[CountSelector(question_type, topic.category, topic.subcategory)] += 1
    return counts


def check_pool_feasibility(pool: QuestionSet, spec: PacketBuildSpec) -> tuple[str, ...]:
    """Return necessary-condition shortfalls between a pool and a build spec.

    An empty result does not guarantee a solution exists, but any message means
    the hard rules cannot be satisfied with this pool.
    """
    counts = pool_counts(pool)

    def available(selector: CountSelector) -> int:
        return sum(count for key, count in counts.items() if selector.matches(key))

    errors: list[str] = []
    capacities = {"tossup": spec.tossup_capacity, "bonus": spec.bonus_capacity}
    for question_type in QUESTION_TYPES:
        needed = capacities[question_type] * spec.packet_count
        have = sum(c for key, c in counts.items() if key.question_type == question_type)
        if have < needed:
            errors.append(
                f"{question_type}s: need {needed} for {spec.packet_count} packets, pool has {have}"
            )

    for quota in spec.quotas:
        needed = quota.minimum * spec.packet_count
        have = available(quota.selector)
        if have < needed:
            errors.append(
                f"{_describe(quota.selector)}: need {needed} for {spec.packet_count} packets, "
                f"pool has {have}"
            )

    for rule in spec.allowed_patterns:
        if isinstance(rule, CategoryCountRule):
            for question_type, per_packet in (
                ("tossup", rule.tossup_count),
                ("bonus", rule.bonus_count),
            ):
                needed = per_packet * spec.packet_count
                have = sum(
                    available(CountSelector(question_type, category))
                    for category in rule.categories
                )
                if have < needed:
                    errors.append(
                        f"{rule.name}: need {needed} {question_type}s across "
                        f"{', '.join(rule.categories)}, pool has {have}"
                    )
        elif isinstance(rule, CategoryGroupCountRule):
            for question_type, per_packet in (
                ("tossup", rule.tossup_count),
                ("bonus", rule.bonus_count),
            ):
                needed = per_packet * spec.packet_count
                have = sum(
                    available(CountSelector(question_type, category))
                    for group in rule.groups
                    for category in group.categories
                )
                if have < needed:
                    errors.append(
                        f"{rule.name}: need {needed} {question_type}s across its groups, "
                        f"pool has {have}"
                    )
            for group in rule.groups:
                needed = group.total_count * spec.packet_count
                have = sum(
                    available(CountSelector(question_type, category))
                    for question_type in QUESTION_TYPES
                    for category in group.categories
                )
                if have < needed:
                    errors.append(
                        f"{rule.name}: need {needed} questions across "
                        f"{', '.join(group.categories)}, pool has {have}"
                    )
                for category in group.categories:
                    category_needed = (
                        group.minimum_per_category * spec.packet_count
                    )
                    category_have = sum(
                        available(CountSelector(question_type, category))
                        for question_type in QUESTION_TYPES
                    )
                    if category_have < category_needed:
                        errors.append(
                            f"{rule.name}: need {category_needed} questions from "
                            f"{category}, pool has {category_have}"
                        )
                type_needed = group.minimum_per_type * spec.packet_count
                for question_type in QUESTION_TYPES:
                    type_have = sum(
                        available(CountSelector(question_type, category))
                        for category in group.categories
                    )
                    if type_have < type_needed:
                        errors.append(
                            f"{rule.name}: need {type_needed} {question_type}s across "
                            f"{', '.join(group.categories)}, pool has {type_have}"
                        )
    return tuple(errors)


def max_feasible_packets(pool: QuestionSet, spec: PacketBuildSpec) -> int:
    """Largest packet count for which no necessary condition fails."""
    from dataclasses import replace

    count = 0
    while not check_pool_feasibility(pool, replace(spec, packet_count=count + 1)):
        count += 1
        if count > 10_000:
            break
    return count


def _describe(selector: CountSelector) -> str:
    return " / ".join(
        part
        for part in (selector.question_type, selector.category, selector.subcategory)
        if part
    )
