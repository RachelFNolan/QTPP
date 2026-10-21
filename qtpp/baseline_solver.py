from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import replace
from itertools import product

from .build_spec import (
    AllowedCountPatterns,
    CategoryGroupCountRule,
    CategoryCountRule,
    CountSelector,
    PacketBuildSpec,
    validate_distribution,
)
from .feasibility import check_pool_feasibility
from .model import QuestionSet
from .scoring import CachedScorer, PacketLayout, SoftWeights, placement_penalty
from .similarity import PairScorer
from .solving import (
    InfeasibleError,
    PoolIndex,
    SolverResult,
    finish_result,
    optimize_order,
    validate_layouts,
)


def solve_baseline(
    pool: QuestionSet,
    spec: PacketBuildSpec,
    scorer: PairScorer,
    weights: SoftWeights = SoftWeights(),
    *,
    seed: int = 0,
    iterations: int = 20000,
    max_attempts: int = 500,
) -> SolverResult:
    """Pure-Python solver: random hard-rule-valid construction plus swap local search.

    Every accepted move preserves each packet's per-selector counts, so hard
    rules established during construction are never relaxed.
    """
    started = time.perf_counter()
    reasons = check_pool_feasibility(pool, spec)
    if reasons:
        raise InfeasibleError(reasons)
    index = PoolIndex.from_pool(pool)
    scorer = CachedScorer(scorer)
    rng = random.Random(seed)

    tossups, bonuses, attempts = construct_random(spec, index, rng, max_attempts)

    accepted = _local_search(index, tossups, bonuses, scorer, weights, rng, iterations)
    layouts = [
        optimize_order(
            PacketLayout(tuple(t), tuple(b)), index.category_of, scorer, weights, rng,
            separation=spec.separation, selector_of=index.selector_of,
        )
        for t, b in zip(tossups, bonuses)
    ]
    return finish_result(
        "python-baseline",
        seed,
        index,
        spec,
        layouts,
        scorer,
        weights,
        time.perf_counter() - started,
        {"construction_attempts": attempts, "accepted_moves": accepted},
    )


def construct_random(
    spec: PacketBuildSpec,
    index: PoolIndex,
    rng: random.Random,
    max_attempts: int = 500,
) -> tuple[list[list[str]], list[list[str]], int]:
    """Random hard-rule-valid packet contents (unoptimized); returns tossups, bonuses, attempts."""
    for attempts in range(1, max_attempts + 1):
        profiles = _sample_profiles(spec, index, rng)
        if profiles is None:
            continue
        tossups, bonuses = _assign(profiles, index, rng)
        layouts = [PacketLayout(tuple(t), tuple(b)) for t, b in zip(tossups, bonuses)]
        # Separation depends on ordering, which is optimized afterwards.
        errors, _ = validate_layouts(index, replace(spec, separation=None), layouts)
        if not errors:
            return tossups, bonuses, attempts
    raise InfeasibleError(
        [f"no hard-rule-valid construction found in {max_attempts} attempts"]
    )


def _sample_profiles(
    spec: PacketBuildSpec, index: PoolIndex, rng: random.Random
) -> list[Counter[CountSelector]] | None:
    supply: Counter[CountSelector] = Counter(
        {selector: len(ids) for selector, ids in index.by_selector.items()}
    )
    single = replace(spec, packet_count=1, aggregate_quotas=(), leftover_bounds=())
    profiles: list[Counter[CountSelector]] = []
    for _ in range(spec.packet_count):
        profile = _sample_profile(spec, single, supply, rng)
        if profile is None:
            return None
        supply.subtract(profile)
        profiles.append(profile)
    return profiles


def _sample_profile(
    spec: PacketBuildSpec,
    single: PacketBuildSpec,
    supply: Counter[CountSelector],
    rng: random.Random,
) -> Counter[CountSelector] | None:
    counts: Counter[CountSelector] = Counter()
    controlled_selectors: set[CountSelector] = set()
    controlled_categories: set[tuple[str, str]] = set()

    def remaining(selector: CountSelector) -> int:
        return supply[selector] - counts[selector]

    def pick(candidates: list[CountSelector]) -> CountSelector | None:
        candidates = [selector for selector in candidates if remaining(selector) > 0]
        if not candidates:
            return None
        return rng.choices(candidates, [remaining(item) for item in candidates])[0]

    for rule in spec.allowed_patterns:
        if isinstance(rule, AllowedCountPatterns):
            if any(selector.subcategory is None for selector in rule.selectors):
                raise NotImplementedError(
                    "the Python baseline requires exact selectors in pattern rules"
                )
            controlled_selectors.update(rule.selectors)
            options = [
                pattern
                for pattern in rule.patterns
                if all(remaining(selector) >= count for selector, count in zip(rule.selectors, pattern))
            ]
            if not options:
                return None
            for selector, count in zip(rule.selectors, rng.choice(options)):
                counts[selector] += count
        elif isinstance(rule, CategoryCountRule):
            used: set[str] = set()
            for question_type, needed in (("tossup", rule.tossup_count), ("bonus", rule.bonus_count)):
                controlled_categories.update((question_type, c) for c in rule.categories)
                for _ in range(needed):
                    candidates = [
                        selector
                        for selector in supply
                        if selector.question_type == question_type
                        and selector.category in rule.categories
                        and not (rule.distinct_categories and selector.category in used)
                    ]
                    chosen = pick(candidates)
                    if chosen is None:
                        return None
                    counts[chosen] += 1
                    used.add(chosen.category)
        elif isinstance(rule, CategoryGroupCountRule):
            for group in rule.groups:
                controlled_categories.update(
                    (question_type, category)
                    for question_type in ("tossup", "bonus")
                    for category in group.categories
                )
            tossup_ranges = [
                range(
                    group.minimum_per_type,
                    group.total_count - group.minimum_per_type + 1,
                )
                for group in rule.groups
            ]
            allocations = [
                values
                for values in product(*tossup_ranges)
                if sum(values) == rule.tossup_count
            ]
            if not allocations:
                return None
            allocation = rng.choice(allocations)
            for group, tossup_count in zip(rule.groups, allocation):
                needed = {
                    "tossup": tossup_count,
                    "bonus": group.total_count - tossup_count,
                }
                used_categories: set[str] = set()
                category_counts: Counter[str] = Counter()
                picked_count = 0
                for question_type in ("tossup", "bonus"):
                    for _ in range(needed[question_type]):
                        missing_categories = {
                            category
                            for category in group.categories
                            if category_counts[category] < group.minimum_per_category
                        }
                        missing_category_slots = sum(
                            max(
                                0,
                                group.minimum_per_category - category_counts[category],
                            )
                            for category in group.categories
                        )
                        slots_left = group.total_count - picked_count
                        candidates = [
                            selector
                            for selector in supply
                            if selector.question_type == question_type
                            and selector.category in group.categories
                            and not (
                                group.distinct_categories
                                and selector.category in used_categories
                            )
                            and (
                                group.maximum_per_category_per_type is None
                                or sum(
                                    count
                                    for existing, count in counts.items()
                                    if existing.question_type == question_type
                                    and existing.category == selector.category
                                )
                                < group.maximum_per_category_per_type
                            )
                            and (
                                slots_left > missing_category_slots
                                or missing_category_slots == 0
                                or selector.category in missing_categories
                            )
                        ]
                        chosen = pick(candidates)
                        if chosen is None:
                            return None
                        counts[chosen] += 1
                        used_categories.add(chosen.category)
                        category_counts[chosen.category] += 1
                        picked_count += 1

    def current(selector: CountSelector) -> int:
        return sum(count for key, count in counts.items() if selector.matches(key))

    for quota in spec.quotas:
        while current(quota.selector) < quota.minimum:
            chosen = pick([key for key in supply if quota.selector.matches(key)])
            if chosen is None:
                return None
            counts[chosen] += 1

    capacities = {"tossup": spec.tossup_capacity, "bonus": spec.bonus_capacity}
    for question_type, capacity in capacities.items():
        while sum(c for key, c in counts.items() if key.question_type == question_type) < capacity:
            candidates = [
                selector
                for selector in supply
                if selector.question_type == question_type
                and selector not in controlled_selectors
                and (question_type, selector.category) not in controlled_categories
                and all(
                    quota.maximum is None
                    or not quota.selector.matches(selector)
                    or current(quota.selector) < quota.maximum
                    for quota in spec.quotas
                )
            ]
            chosen = pick(candidates)
            if chosen is None:
                return None
            counts[chosen] += 1

    if validate_distribution(single, [counts], {"tossup": 0, "bonus": 0}):
        return None
    return counts


def _assign(
    profiles: list[Counter[CountSelector]], index: PoolIndex, rng: random.Random
) -> tuple[list[list[str]], list[list[str]]]:
    tossups: list[list[str]] = [[] for _ in profiles]
    bonuses: list[list[str]] = [[] for _ in profiles]
    for selector, ids in index.by_selector.items():
        pool_ids = list(ids)
        rng.shuffle(pool_ids)
        target = tossups if selector.question_type == "tossup" else bonuses
        for packet, profile in enumerate(profiles):
            for _ in range(profile[selector]):
                target[packet].append(pool_ids.pop())
    for packet in range(len(profiles)):
        rng.shuffle(tossups[packet])
        rng.shuffle(bonuses[packet])
    return tossups, bonuses


def _local_search(
    index: PoolIndex,
    tossups: list[list[str]],
    bonuses: list[list[str]],
    scorer: PairScorer,
    weights: SoftWeights,
    rng: random.Random,
    iterations: int,
) -> int:
    location: dict[str, tuple[int, bool, int] | None] = {
        question_id: None for question_id in (*index.tossup_ids, *index.bonus_ids)
    }
    for packet, (packet_tossups, packet_bonuses) in enumerate(zip(tossups, bonuses)):
        for position, question_id in enumerate(packet_tossups):
            location[question_id] = (packet, True, position)
        for position, question_id in enumerate(packet_bonuses):
            location[question_id] = (packet, False, position)
    swappable = {
        selector: ids for selector, ids in index.by_selector.items() if len(ids) > 1
    }
    selectors = list(swappable)
    accepted = 0

    def penalty(packet: int, is_tossup: bool, position: int, question_id: str) -> float:
        return placement_penalty(
            tossups[packet], bonuses[packet], is_tossup, position, question_id,
            index.category_of, scorer, weights,
        )

    for _ in range(iterations):
        if not selectors:
            break
        selector = rng.choice(selectors)
        first, second = rng.sample(swappable[selector], 2)
        first_location, second_location = location[first], location[second]
        if first_location is None and second_location is None:
            continue
        if first_location is None:
            first, second = second, first
            first_location, second_location = second_location, first_location
        packet, is_tossup, position = first_location
        if second_location is not None and second_location[0] == packet:
            continue
        delta = penalty(packet, is_tossup, position, second) - penalty(
            packet, is_tossup, position, first
        )
        if second_location is not None:
            other_packet, _, other_position = second_location
            delta += penalty(other_packet, is_tossup, other_position, first) - penalty(
                other_packet, is_tossup, other_position, second
            )
        if delta >= -1e-12:
            continue
        sequences = tossups if is_tossup else bonuses
        sequences[packet][position] = second
        location[second] = first_location
        if second_location is None:
            location[first] = None
        else:
            sequences[second_location[0]][second_location[2]] = first
            location[first] = second_location
        accepted += 1
    return accepted
