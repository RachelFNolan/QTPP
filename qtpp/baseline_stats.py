"""Random-layout baselines that put different similarity scorers on one scale.

Each scorer's raw penalty has its own units, so builds are also reported as the
fractional improvement over hard-rule-valid random layouts scored by the same
scorer. A "referee" averages those improvements across scorers; no solver
optimizes it directly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Mapping, Sequence

from .baseline_solver import construct_random
from .build_spec import PacketBuildSpec
from .model import QuestionSet
from .scoring import CachedScorer, PacketLayout, SoftWeights, score_layouts
from .similarity import PairScorer
from .solving import PoolIndex

DEFAULT_SAMPLES = 30
MAX_SAMPLES = 500


@dataclass(frozen=True, slots=True)
class BaselineStat:
    """Penalty distribution of random valid layouts under one scorer."""

    mean: float
    stdev: float
    samples: int

    def improvement(self, penalty: float) -> float:
        """Fraction better than the random mean: 1 is zero penalty, 0 is random, <0 is worse."""
        if self.mean <= 1e-12:
            return 0.0
        return 1.0 - penalty / self.mean

    def z_score(self, penalty: float) -> float:
        """Standard deviations below the random mean (positive is better)."""
        if self.stdev <= 1e-12:
            return 0.0
        return (self.mean - penalty) / self.stdev


def sample_random_layouts(
    pool: QuestionSet,
    spec: PacketBuildSpec,
    samples: int = DEFAULT_SAMPLES,
    seed: int = 0,
) -> list[tuple[PacketLayout, ...]]:
    """Unoptimized hard-rule-valid layouts, shared by every scorer for a fair baseline."""
    if not isinstance(samples, int) or isinstance(samples, bool) or not 1 <= samples <= MAX_SAMPLES:
        raise ValueError(f"baseline samples must be between 1 and {MAX_SAMPLES}")
    index = PoolIndex.from_pool(pool)
    rng = random.Random(seed)
    layouts = []
    for _ in range(samples):
        tossups, bonuses, _attempts = construct_random(spec, index, rng)
        layouts.append(
            tuple(PacketLayout(tuple(t), tuple(b)) for t, b in zip(tossups, bonuses))
        )
    return layouts


def baseline_stats(
    pool: QuestionSet,
    samples: Sequence[Sequence[PacketLayout]],
    scorers: Mapping[str, PairScorer],
    weights: SoftWeights = SoftWeights(),
) -> dict[str, BaselineStat]:
    """Mean and standard deviation of the total penalty of random layouts, per scorer."""
    category_of = PoolIndex.from_pool(pool).category_of
    stats = {}
    for scorer_id, scorer in scorers.items():
        cached = CachedScorer(scorer)
        totals = [
            score_layouts(layouts, category_of, cached, weights).total for layouts in samples
        ]
        stats[scorer_id] = BaselineStat(fmean(totals), pstdev(totals), len(totals))
    return stats


def normalize(
    penalties: Mapping[str, float], stats: Mapping[str, BaselineStat]
) -> dict[str, object]:
    """Per-scorer improvement over random plus their mean (the referee score)."""
    improvements = {key: stats[key].improvement(value) for key, value in penalties.items()}
    return {
        "improvement": improvements,
        "z_score": {key: stats[key].z_score(value) for key, value in penalties.items()},
        "referee": fmean(improvements.values()),
    }
