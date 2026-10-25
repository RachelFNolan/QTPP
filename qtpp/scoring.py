from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence

from .similarity import PairScorer


@dataclass(frozen=True, slots=True)
class SoftWeights:
    """Weights for soft preferences; all penalties are minimized."""

    adjacent_category: float = 1.0
    same_packet: float = 1.0
    nearby: float = 3.0
    window: int = 3

    def __post_init__(self) -> None:
        if min(self.adjacent_category, self.same_packet, self.nearby) < 0:
            raise ValueError("soft weights must be non-negative")
        if not isinstance(self.window, int) or self.window < 1:
            raise ValueError("window must be a positive integer")


@dataclass(frozen=True, slots=True)
class PacketLayout:
    """Ordered question IDs for one packet."""

    tossups: tuple[str, ...]
    bonuses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SoftScore:
    adjacent_category: float = 0.0
    same_packet: float = 0.0
    nearby: float = 0.0

    @property
    def total(self) -> float:
        return self.adjacent_category + self.same_packet + self.nearby

    def __add__(self, other: SoftScore) -> SoftScore:
        return SoftScore(
            self.adjacent_category + other.adjacent_category,
            self.same_packet + other.same_packet,
            self.nearby + other.nearby,
        )


class CachedScorer:
    """Memoizes a symmetric pair scorer."""

    def __init__(self, scorer: PairScorer) -> None:
        self._scorer = scorer
        self._cache: dict[tuple[str, str], float] = {}

    def score(self, first_id: str, second_id: str) -> float:
        key = (first_id, second_id) if first_id <= second_id else (second_id, first_id)
        value = self._cache.get(key)
        if value is None:
            value = self._cache[key] = self._scorer.score(*key)
        return value


def score_packet(
    layout: PacketLayout,
    categories: Mapping[str, str],
    scorer: PairScorer,
    weights: SoftWeights = SoftWeights(),
) -> SoftScore:
    """Soft penalty for one packet; lower is better."""
    adjacent = sum(
        1
        for sequence in (layout.tossups, layout.bonuses)
        for first, second in zip(sequence, sequence[1:])
        if categories[first] == categories[second]
    )
    same_packet = sum(
        scorer.score(first, second)
        for first, second in combinations((*layout.tossups, *layout.bonuses), 2)
    )
    nearby = 0.0
    for sequence in (layout.tossups, layout.bonuses):
        for index, first in enumerate(sequence):
            for distance in range(1, weights.window + 1):
                if index + distance < len(sequence):
                    nearby += scorer.score(first, sequence[index + distance]) / distance
    return SoftScore(
        adjacent_category=weights.adjacent_category * adjacent,
        same_packet=weights.same_packet * same_packet,
        nearby=weights.nearby * nearby,
    )


def placement_penalty(
    layout_tossups: Sequence[str],
    layout_bonuses: Sequence[str],
    is_tossup: bool,
    index: int,
    question_id: str,
    categories: Mapping[str, str],
    scorer: PairScorer,
    weights: SoftWeights,
) -> float:
    """Penalty terms involving ``question_id`` placed in the given slot.

    The slot's current occupant is ignored, so the difference between two
    candidates equals the change in the packet's total score from swapping them.
    """
    sequence = layout_tossups if is_tossup else layout_bonuses
    total = 0.0
    for other_is_tossup, others in ((True, layout_tossups), (False, layout_bonuses)):
        for position, other in enumerate(others):
            if other_is_tossup == is_tossup and position == index:
                continue
            total += weights.same_packet * scorer.score(question_id, other)
    for position in range(
        max(0, index - weights.window), min(len(sequence), index + weights.window + 1)
    ):
        if position == index:
            continue
        distance = abs(position - index)
        total += weights.nearby * scorer.score(question_id, sequence[position]) / distance
        if distance == 1 and categories[question_id] == categories[sequence[position]]:
            total += weights.adjacent_category
    return total


def score_layouts(
    layouts: Sequence[PacketLayout],
    categories: Mapping[str, str],
    scorer: PairScorer,
    weights: SoftWeights = SoftWeights(),
) -> SoftScore:
    """Total soft penalty with its per-term breakdown across packets."""
    total = SoftScore()
    for layout in layouts:
        total = total + score_packet(layout, categories, scorer, weights)
    return total
