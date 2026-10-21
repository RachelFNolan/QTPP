from __future__ import annotations

from collections import Counter

from .build_spec import CategoryQuota, CountSelector, QUESTION_TYPES
from .feasibility import pool_counts
from .model import QuestionSet
from .templates import BuildTemplate


def suggest_template(
    pool: QuestionSet,
    *,
    name: str,
    packet_count: int,
    tossup_capacity: int,
    bonus_capacity: int,
    tolerance: int = 1,
) -> BuildTemplate:
    """Propose per-category quotas that mirror the pool's category mix.

    Each category's per-packet target is its share of the pool applied to the packet
    capacity (largest-remainder rounding, limited to what the pool can supply across
    all packets). Quotas allow ``tolerance`` questions either side of the target.
    """
    if packet_count < 1 or tossup_capacity < 0 or bonus_capacity < 0 or tolerance < 0:
        raise ValueError("packet count must be positive; capacities and tolerance cannot be negative")
    counts = pool_counts(pool)
    capacities = {"tossup": tossup_capacity, "bonus": bonus_capacity}
    quotas: list[CategoryQuota] = []
    for question_type in QUESTION_TYPES:
        by_category: Counter[str] = Counter()
        for selector, count in counts.items():
            if selector.question_type == question_type:
                by_category[selector.category or ""] += count
        targets = _allocate(by_category, capacities[question_type], packet_count)
        for category in sorted(targets):
            target = targets[category]
            quotas.append(
                CategoryQuota(
                    CountSelector(question_type, category),
                    minimum=max(0, target - tolerance),
                    maximum=target + tolerance,
                )
            )
    return BuildTemplate(
        name=name,
        tossup_capacity=tossup_capacity,
        bonus_capacity=bonus_capacity,
        quotas=tuple(quotas),
        allowed_patterns=(),
    )


def _allocate(available: Counter[str], capacity: int, packet_count: int) -> dict[str, int]:
    total = sum(available.values())
    if total == 0 or capacity == 0:
        return {}
    limits = {category: count // packet_count for category, count in available.items()}
    exact = {category: capacity * count / total for category, count in available.items()}
    targets = {category: min(int(value), limits[category]) for category, value in exact.items()}
    remaining = capacity - sum(targets.values())
    by_remainder = sorted(exact, key=lambda category: (-(exact[category] - int(exact[category])), category))
    while remaining > 0:
        progressed = False
        for category in by_remainder:
            if remaining > 0 and targets[category] < limits[category]:
                targets[category] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    return {category: target for category, target in targets.items() if target > 0}
