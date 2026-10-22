"""Sensitivity of builds to the soft-score weights.

Each weight is varied on its own (the others stay at their current values) and the
Python baseline solver is re-run with the same seed. Every result is then measured
on one fixed yardstick (all three terms at weight 1) so rows are comparable, along
with how much the packets changed relative to the build at the current weights.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from itertools import product
from statistics import fmean, pstdev
from typing import Mapping, Sequence

from .baseline_solver import solve_baseline
from .build_spec import PacketBuildSpec
from .model import QuestionSet
from .baseline_stats import sample_random_layouts
from .scoring import CachedScorer, PacketLayout, SoftScore, SoftWeights, score_layouts
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


COARSE_FACTORS = (0.5, 1.0, 2.0)
REFINE_FACTORS = (0.7, 1.4)
MAX_BUILDS = 400
MAX_TIME_LIMIT = 600.0
EPSILON = 1e-9


def _vector(weights: SoftWeights) -> tuple[float, float, float]:
    return tuple(getattr(weights, term) for term in TERMS)


def _with_vector(window: int, vector: Sequence[float]) -> SoftWeights:
    return SoftWeights(*vector, window=window)


def _candidates(weights: SoftWeights) -> list[tuple[float, ...]]:
    """Coarse grid of scaled weights with the current weights first."""
    base = _vector(weights)

    def scaled(value: float, factor: float) -> float:
        # A weight at zero has nothing to scale, so the factor is the value.
        return round(value * factor if value > 0 else factor, 6)

    coarse = [
        tuple(scaled(value, factor) for value, factor in zip(base, factors))
        for factors in product(COARSE_FACTORS, repeat=3)
    ]
    return list(dict.fromkeys([base, *coarse]))


def _refinements(point: Sequence[float]) -> list[tuple[float, ...]]:
    result = []
    for position, value in enumerate(point):
        for factor in REFINE_FACTORS:
            candidate = list(point)
            candidate[position] = round(value * factor, 6) if value > 0 else 0.5
            result.append(tuple(candidate))
    return result


def _term_means(
    pool: QuestionSet,
    spec: PacketBuildSpec,
    scorer: PairScorer,
    category_of: Mapping[str, str],
    window: int,
    samples: int,
    seed: int,
) -> dict[str, float]:
    """Mean raw value of each term over random valid layouts: the fixed yardstick."""
    cached = CachedScorer(scorer)
    unit = SoftWeights(1.0, 1.0, 1.0, window)
    raws = [
        _raw(score_layouts(layouts, category_of, cached, unit))
        for layouts in sample_random_layouts(pool, spec, samples, seed)
    ]
    return {term: fmean(raw[term] for raw in raws) for term in TERMS}


def _quality(
    layouts: Sequence[PacketLayout],
    category_of: Mapping[str, str],
    scorer: PairScorer,
    means: Mapping[str, float],
    window: int,
) -> float:
    """Average per-term improvement over random, with every term at weight 1."""
    raw = _raw(score_layouts(layouts, category_of, scorer, SoftWeights(1.0, 1.0, 1.0, window)))
    parts = [1.0 - raw[term] / means[term] for term in TERMS if means[term] > 1e-12]
    return fmean(parts) if parts else 0.0


def estimated_builds(scorer_count: int, seeds: int, holdout: int) -> int:
    candidates = len(_candidates(SoftWeights())) + 6
    return scorer_count * (candidates * seeds + 2 * holdout)


def tune_weights(
    pool: QuestionSet,
    spec: PacketBuildSpec,
    scorers: Mapping[str, PairScorer],
    weights: SoftWeights,
    *,
    seed: int = 0,
    seeds: int = 2,
    holdout: int = 3,
    samples: int = 30,
    time_limit: float = 120.0,
) -> dict[str, object]:
    """Pick soft weights by building at many candidates and scoring on a fixed yardstick.

    The yardstick (each term at weight 1, scaled by its random-layout mean and
    averaged over terms and scorers) does not depend on the candidate weights, so
    turning a weight down cannot make a build look better. The winner is checked on
    seeds that were not used to choose it.
    """
    if not scorers:
        raise ValueError("Choose at least one similarity scorer.")
    if not 1 <= seeds <= 5 or not 1 <= holdout <= 5:
        raise ValueError("Search seeds and held-out seeds must each be between 1 and 5.")
    if not 0 < time_limit <= MAX_TIME_LIMIT:
        raise ValueError(f"time_limit must be between 0 and {MAX_TIME_LIMIT:g} seconds.")
    needed = estimated_builds(len(scorers), seeds, holdout)
    if needed > MAX_BUILDS:
        raise ValueError(
            f"This search needs about {needed} builds (limit {MAX_BUILDS}); "
            "use fewer seeds or fewer scorers."
        )
    started = time.perf_counter()
    deadline = started + time_limit
    category_of = PoolIndex.from_pool(pool).category_of
    cached = {key: CachedScorer(scorer) for key, scorer in scorers.items()}
    means = {
        key: _term_means(pool, spec, cached[key], category_of, weights.window, samples, seed)
        for key in scorers
    }
    builds = 0

    def evaluate(vector: Sequence[float], run_seed: int) -> float:
        nonlocal builds
        candidate = _with_vector(weights.window, vector)
        values = []
        for key, scorer in cached.items():
            layouts = solve_baseline(pool, spec, scorer, candidate, seed=run_seed).layouts
            builds += 1
            values.append(_quality(layouts, category_of, scorer, means[key], weights.window))
        return fmean(values)

    search_seeds = [seed + 1 + offset for offset in range(seeds)]
    held_seeds = [seed + 101 + offset for offset in range(holdout)]
    results: dict[tuple[float, ...], list[float]] = {}
    truncated = False

    def search(points: Sequence[tuple[float, ...]]) -> None:
        nonlocal truncated
        for point in points:
            if point in results:
                continue
            if results and time.perf_counter() > deadline:
                truncated = True
                return
            results[point] = [evaluate(point, run_seed) for run_seed in search_seeds]

    current = _vector(weights)
    search(_candidates(weights))
    best = max(results, key=lambda point: (fmean(results[point]), point == current))
    if not truncated:
        search(_refinements(best))
        best = max(results, key=lambda point: (fmean(results[point]), point == current))

    held_current = [evaluate(current, run_seed) for run_seed in held_seeds]
    if best == current:
        held_best = held_current
    else:
        held_best = [evaluate(best, run_seed) for run_seed in held_seeds]
    gains = [after - before for before, after in zip(held_current, held_best)]
    gain = fmean(gains)
    error = pstdev(gains) / len(gains) ** 0.5 if len(gains) > 1 else 0.0
    improved = best != current and gain > max(0.005, 2 * error)

    def describe(point: tuple[float, ...]) -> dict[str, object]:
        values = results[point]
        return {
            "weights": dict(zip(TERMS, point)) | {"window": weights.window},
            "quality": fmean(values),
            "spread": pstdev(values) if len(values) > 1 else 0.0,
        }

    ranked = sorted(results, key=lambda point: fmean(results[point]), reverse=True)[:8]
    notes = []
    if truncated:
        notes.append("The time limit was reached before every candidate was tried; results are partial.")
    if not improved:
        notes.append("No candidate beat your current weights by more than the noise on held-out seeds; keep them.")
    return {
        "current": describe(current) | {"held_out": fmean(held_current)},
        "best": describe(best) | {"held_out": fmean(held_best)},
        "improved": improved,
        "gain": gain,
        "gain_error": error,
        "top": [describe(point) for point in ranked],
        "evaluated_candidates": len(results),
        "builds": builds,
        "seeds": seeds,
        "held_out_seeds": holdout,
        "truncated": truncated,
        "seconds": time.perf_counter() - started,
        "yardstick": means,
        "notes": notes,
    }
