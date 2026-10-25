from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

from .build_spec import (
    CountSelector,
    PacketBuildSpec,
    TossupBonusSeparation,
    validate_distribution,
)
from .model import QuestionSet
from .scoring import PacketLayout, SoftScore, SoftWeights, score_layouts
from .similarity import PairScorer


class InfeasibleError(ValueError):
    """Raised when the hard rules cannot be satisfied; carries the reasons."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons) or "no feasible packet assignment found")


@dataclass(frozen=True, slots=True)
class SolverResult:
    solver: str
    seed: int
    layouts: tuple[PacketLayout, ...]
    score: SoftScore
    hard_errors: tuple[str, ...]
    leftover_ids: tuple[str, ...]
    seconds: float
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PoolIndex:
    """Question lookups shared by the solvers."""

    selector_of: Mapping[str, CountSelector]
    category_of: Mapping[str, str]
    by_selector: Mapping[CountSelector, tuple[str, ...]]
    tossup_ids: tuple[str, ...]
    bonus_ids: tuple[str, ...]

    @classmethod
    def from_pool(cls, pool: QuestionSet) -> PoolIndex:
        selector_of: dict[str, CountSelector] = {}
        by_selector: dict[CountSelector, list[str]] = {}
        for question_type, questions in (("tossup", pool.tossups), ("bonus", pool.bonuses)):
            for question in questions:
                topic = question.metadata.topic
                selector = CountSelector(question_type, topic.category, topic.subcategory)
                selector_of[question.metadata.id] = selector
                by_selector.setdefault(selector, []).append(question.metadata.id)
        return cls(
            selector_of=selector_of,
            category_of={key: value.category for key, value in selector_of.items()},
            by_selector={key: tuple(value) for key, value in by_selector.items()},
            tossup_ids=tuple(question.metadata.id for question in pool.tossups),
            bonus_ids=tuple(question.metadata.id for question in pool.bonuses),
        )


def separation_conflicts(
    tossups: Sequence[str],
    bonuses: Sequence[str],
    selector_of: Mapping[str, CountSelector],
    separation: TossupBonusSeparation,
) -> list[tuple[int, int]]:
    """1-based (tossup, bonus) positions that share a topic within the window."""

    def keys(question_id: str) -> tuple[str, tuple[str, str | None]]:
        selector = selector_of[question_id]
        return selector.category, (selector.category, selector.subcategory)

    tossup_keys = [keys(question_id) for question_id in tossups]
    bonus_keys = [keys(question_id) for question_id in bonuses]
    conflicts = []
    for t, (t_category, t_sub) in enumerate(tossup_keys):
        for b in range(
            max(0, t - separation.window), min(len(bonus_keys), t + separation.window + 1)
        ):
            b_category, b_sub = bonus_keys[b]
            if (separation.by_category and t_category == b_category) or (
                separation.by_subcategory and t_sub == b_sub
            ):
                conflicts.append((t + 1, b + 1))
    return conflicts


def validate_layouts(
    index: PoolIndex, spec: PacketBuildSpec, layouts: Sequence[PacketLayout]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Check hard rules for ordered layouts; returns (errors, leftover question IDs)."""
    errors: list[str] = []
    seen: set[str] = set()
    packet_counts = []
    for number, layout in enumerate(layouts, start=1):
        counts: dict[CountSelector, int] = {}
        for expected_type, ids in (("tossup", layout.tossups), ("bonus", layout.bonuses)):
            for question_id in ids:
                selector = index.selector_of.get(question_id)
                if selector is None or selector.question_type != expected_type:
                    errors.append(f"packet {number}: unknown or mistyped {expected_type} {question_id}")
                    continue
                if question_id in seen:
                    errors.append(f"packet {number}: question {question_id} assigned twice")
                seen.add(question_id)
                counts[selector] = counts.get(selector, 0) + 1
        packet_counts.append(counts)
    all_ids = (*index.tossup_ids, *index.bonus_ids)
    leftover_ids = tuple(question_id for question_id in all_ids if question_id not in seen)
    leftovers = {
        "tossup": sum(1 for question_id in leftover_ids if index.selector_of[question_id].question_type == "tossup"),
        "bonus": sum(1 for question_id in leftover_ids if index.selector_of[question_id].question_type == "bonus"),
    }
    errors.extend(validate_distribution(spec, packet_counts, leftovers))
    if spec.separation is not None:
        for number, layout in enumerate(layouts, start=1):
            if any(q not in index.selector_of for q in (*layout.tossups, *layout.bonuses)):
                continue
            for t, b in separation_conflicts(
                layout.tossups, layout.bonuses, index.selector_of, spec.separation
            ):
                errors.append(
                    f"packet {number}: tossup {t} and bonus {b} share a "
                    f"{'category' if spec.separation.by_category else 'subcategory'}"
                    f" within a window of {spec.separation.window}"
                )
    return tuple(errors), leftover_ids


def order_penalty(
    sequence: Sequence[str],
    categories: Mapping[str, str],
    scorer: PairScorer,
    weights: SoftWeights,
) -> float:
    """Order-dependent penalty for one tossup or bonus sequence."""
    total = 0.0
    for index, first in enumerate(sequence):
        if index + 1 < len(sequence):
            if categories[first] == categories[sequence[index + 1]]:
                total += weights.adjacent_category
        for distance in range(1, weights.window + 1):
            if index + distance < len(sequence):
                total += weights.nearby * scorer.score(first, sequence[index + distance]) / distance
    return total


def optimize_order(
    layout: PacketLayout,
    categories: Mapping[str, str],
    scorer: PairScorer,
    weights: SoftWeights,
    rng: random.Random,
    passes: int = 400,
    *,
    separation: TossupBonusSeparation | None = None,
    selector_of: Mapping[str, CountSelector] | None = None,
) -> PacketLayout:
    """Hill-climb question order within a packet; membership never changes.

    With ``separation``, tossup/bonus topic conflicts are minimized first (with
    restarts) and the soft penalty second.
    """
    if separation is not None and selector_of is not None:
        return _optimize_separated(
            layout, categories, scorer, weights, rng, passes, separation, selector_of
        )
    sequences = [list(layout.tossups), list(layout.bonuses)]
    for kind, sequence in enumerate(sequences):
        if len(sequence) < 2:
            continue
        current = order_penalty(sequence, categories, scorer, weights)
        for _ in range(passes):
            first, second = rng.sample(range(len(sequence)), 2)
            sequence[first], sequence[second] = sequence[second], sequence[first]
            candidate = order_penalty(sequence, categories, scorer, weights)
            if candidate < current - 1e-12:
                current = candidate
            else:
                sequence[first], sequence[second] = sequence[second], sequence[first]
    return replace(layout, tossups=tuple(sequences[0]), bonuses=tuple(sequences[1]))


def _optimize_separated(
    layout: PacketLayout,
    categories: Mapping[str, str],
    scorer: PairScorer,
    weights: SoftWeights,
    rng: random.Random,
    passes: int,
    separation: TossupBonusSeparation,
    selector_of: Mapping[str, CountSelector],
    restarts: int = 20,
) -> PacketLayout:
    def cost(sequences: list[list[str]]) -> tuple[int, float]:
        conflicts = len(separation_conflicts(sequences[0], sequences[1], selector_of, separation))
        soft = order_penalty(sequences[0], categories, scorer, weights)
        soft += order_penalty(sequences[1], categories, scorer, weights)
        return conflicts, soft

    best: list[list[str]] | None = None
    best_cost = (0, 0.0)
    for attempt in range(restarts):
        sequences = [list(layout.tossups), list(layout.bonuses)]
        if attempt:
            for sequence in sequences:
                rng.shuffle(sequence)
        current = cost(sequences)
        for _ in range(passes * 3):
            kind = rng.randrange(2)
            sequence = sequences[kind]
            if len(sequence) < 2:
                continue
            first, second = rng.sample(range(len(sequence)), 2)
            sequence[first], sequence[second] = sequence[second], sequence[first]
            candidate = cost(sequences)
            if candidate < current:
                current = candidate
            else:
                sequence[first], sequence[second] = sequence[second], sequence[first]
        if best is None or current < best_cost:
            best, best_cost = [list(s) for s in sequences], current
        if best_cost[0] == 0:
            break
    assert best is not None
    return replace(layout, tossups=tuple(best[0]), bonuses=tuple(best[1]))


def finish_result(
    solver: str,
    seed: int,
    index: PoolIndex,
    spec: PacketBuildSpec,
    layouts: Sequence[PacketLayout],
    scorer: PairScorer,
    weights: SoftWeights,
    seconds: float,
    details: Mapping[str, object] | None = None,
) -> SolverResult:
    errors, leftover_ids = validate_layouts(index, spec, layouts)
    return SolverResult(
        solver=solver,
        seed=seed,
        layouts=tuple(layouts),
        score=score_layouts(layouts, index.category_of, scorer, weights),
        hard_errors=errors,
        leftover_ids=leftover_ids,
        seconds=seconds,
        details=dict(details or {}),
    )
