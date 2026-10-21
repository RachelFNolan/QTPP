"""Apply saved human similarity judgments on top of an automatic pair scorer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .label_store import load_labels, pair_key
from .model import Bonus, Tossup
from .scoring import PacketLayout
from .similarity import PairScorer, question_text

# Similarity scores sit roughly in 0..1, so 1.0 ranks a flagged pair above any automatic pair.
SOFT_FLOOR = 1.0
# Large enough that solvers avoid a flagged pair unless nothing else is feasible.
HARD_FLOOR = 1000.0


@dataclass(frozen=True, slots=True)
class Judgments:
    """Saved judgments whose question IDs and text hashes match the current pool."""

    similar: frozenset[tuple[str, str]] = frozenset()
    different: frozenset[tuple[str, str]] = frozenset()
    borderline: int = 0

    @property
    def applied(self) -> int:
        return len(self.similar) + len(self.different)

    def flagged_together(self, packets: list[set[str]]) -> int:
        """Count 'similar' pairs that share a packet."""
        return sum(
            any(first in packet and second in packet for packet in packets)
            for first, second in self.similar
        )


def _pair(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first <= second else (second, first)


def load_judgments(
    path: str | Path, questions: Mapping[str, Tossup | Bonus]
) -> Judgments:
    similar: set[tuple[str, str]] = set()
    different: set[tuple[str, str]] = set()
    borderline = 0
    for key, record in load_labels(path).items():
        first_id, second_id = record.get("first_id"), record.get("second_id")
        first, second = questions.get(first_id), questions.get(second_id)
        if first is None or second is None or first_id == second_id:
            continue
        if pair_key(question_text(first), question_text(second)) != key:
            continue
        if record["label"] == "similar":
            similar.add(_pair(first_id, second_id))
        elif record["label"] == "different":
            different.add(_pair(first_id, second_id))
        else:
            borderline += 1
    return Judgments(frozenset(similar), frozenset(different), borderline)


class JudgedPairScorer:
    """'Similar' pairs are raised to a floor penalty; 'different' pairs score zero."""

    def __init__(
        self, base: PairScorer, judgments: Judgments, floor: float = SOFT_FLOOR
    ) -> None:
        self._base = base
        self._similar = judgments.similar
        self._different = judgments.different
        self._floor = floor

    def score(self, first_id: str, second_id: str) -> float:
        pair = _pair(first_id, second_id)
        if pair in self._similar:
            return max(self._base.score(first_id, second_id), self._floor)
        if pair in self._different:
            return 0.0
        return self._base.score(first_id, second_id)


def flagged_pairs_from_layouts(judgments: Judgments, layouts: Sequence[PacketLayout]) -> int:
    return judgments.flagged_together([{*l.tossups, *l.bonuses} for l in layouts])

