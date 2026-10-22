"""Sensitivity of builds to the soft-score weights.

Each weight is varied on its own (the others stay at their current values) and the
Python baseline solver is re-run with the same seed. Every result is then measured
on one fixed yardstick (all three terms at weight 1) so rows are comparable, along
with how much the packets changed relative to the build at the current weights.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Sequence

from .baseline_solver import solve_baseline
from .build_spec import PacketBuildSpec
from .model import QuestionSet
from .scoring import PacketLayout, SoftScore, SoftWeights, score_layouts
from .similarity import PairScorer
from .solving import PoolIndex

TERMS = ("adjacent_category", "same_packet", "nearby")
DEFAULT_FACTORS = (0.0, 0.5, 2.0, 4.0)
MAX_FACTORS = 8
MAX_FACTOR = 100.0


@dataclass(frozen=True, slots=True)
class SweepRow:
    term: str
    factor: float
    weight: float
    raw: dict[str, float]
    weighted_total: float
    membership_change: float
    order_change: float
    is_current: bool = False


def _pairs_together(layouts: Sequence[PacketLayout]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for layout in layouts:
        ids = sorted((*layout.tossups, *layout.bonuses))
        pairs.update((a, b) for i, a in enumerate(ids) for b in ids[i + 1 :])
    return pairs


def _membership_change(base: Sequence[PacketLayout], other: Sequence[PacketLayout]) -> float:
    """Share of the base build's same-packet pairs that are no longer together."""
    base_pairs = _pairs_together(base)
    if not base_pairs:
        return 0.0
    return 1.0 - len(base_pairs & _pairs_together(other)) / len(base_pairs)


def _order_change(base: Sequence[PacketLayout], other: Sequence[PacketLayout]) -> float:
    """Share of slots holding a different question than in the base build."""
    slots = changed = 0
    for first, second in zip(base, other):
        for left, right in ((first.tossups, second.tossups), (first.bonuses, second.bonuses)):
            slots += len(left)
            changed += sum(1 for a, b in zip(left, right) if a != b) + abs(len(left) - len(right))
    return changed / slots if slots else 0.0


def _raw(score: SoftScore) -> dict[str, float]:
    return {term: getattr(score, term) for term in TERMS}


def sweep_weights(
    pool: QuestionSet,
    spec: PacketBuildSpec,
    scorer: PairScorer,
    weights: SoftWeights,
    *,
    seed: int = 0,
    factors: Sequence[float] = DEFAULT_FACTORS,
) -> dict[str, object]:
    """Re-run the baseline solver with each weight scaled by each factor."""
    factors = tuple(dict.fromkeys(float(factor) for factor in factors))
    if not factors or len(factors) > MAX_FACTORS:
        raise ValueError(f"Provide between 1 and {MAX_FACTORS} multipliers.")
    if any(not 0 <= factor <= MAX_FACTOR for factor in factors):
        raise ValueError(f"Multipliers must be between 0 and {MAX_FACTOR:g}.")
    index = PoolIndex.from_pool(pool)
    unit = SoftWeights(1.0, 1.0, 1.0, weights.window)

    def build(candidate: SoftWeights) -> tuple[PacketLayout, ...]:
        return solve_baseline(pool, spec, scorer, candidate, seed=seed).layouts

    def measure(layouts: Sequence[PacketLayout]) -> tuple[dict[str, float], float]:
        raw = score_layouts(layouts, index.category_of, scorer, unit)
        return _raw(raw), score_layouts(layouts, index.category_of, scorer, weights).total

    current = build(weights)
    current_raw, current_total = measure(current)
    weighted = {
        term: getattr(weights, term) * value for term, value in current_raw.items()
    }
    total = sum(weighted.values())
    scale = [
        {
            "term": term,
            "weight": getattr(weights, term),
            "raw": current_raw[term],
            "contribution": weighted[term],
            "share": weighted[term] / total if total > 1e-12 else 0.0,
        }
        for term in TERMS
    ]
    rows: list[SweepRow] = []
    for term in TERMS:
        base_weight = getattr(weights, term)
        for factor in factors:
            # A weight currently at zero has nothing to scale, so the factor is the value.
            value = base_weight * factor if base_weight > 0 else factor
            layouts = build(replace(weights, **{term: value}))
            raw, weighted_total = measure(layouts)
            rows.append(
                SweepRow(
                    term=term,
                    factor=factor,
                    weight=value,
                    raw=raw,
                    weighted_total=weighted_total,
                    membership_change=_membership_change(current, layouts),
                    order_change=_order_change(current, layouts),
                    is_current=abs(value - base_weight) < 1e-12,
                )
            )
    insensitive = [
        term
        for term in TERMS
        if all(
            row.membership_change < 0.02 and row.order_change < 0.05
            for row in rows
            if row.term == term and not row.is_current
        )
    ]
    return {
        "weights": {term: getattr(weights, term) for term in TERMS} | {"window": weights.window},
        "current": {"raw": current_raw, "weighted_total": current_total},
        "scale": scale,
        "rows": [asdict(row) for row in rows],
        "insensitive": insensitive,
        "factors": list(factors),
    }
