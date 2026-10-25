from __future__ import annotations

import random
import time
from itertools import combinations
from typing import Iterable

from .build_spec import (
    AllowedCountPatterns,
    CategoryGroupCountRule,
    CategoryCountRule,
    LeftoverBound,
    PacketBuildSpec,
)
from .feasibility import check_pool_feasibility
from .model import QuestionSet
from .scoring import CachedScorer, PacketLayout, SoftWeights
from .similarity import PairScorer
from .solving import (
    InfeasibleError,
    PoolIndex,
    SolverResult,
    finish_result,
    optimize_order,
)

try:
    from ortools.sat.python import cp_model
except ImportError:  # pragma: no cover - exercised only without ortools
    cp_model = None

PENALTY_SCALE = 100


def solve_cpsat(
    pool: QuestionSet,
    spec: PacketBuildSpec,
    scorer: PairScorer,
    weights: SoftWeights = SoftWeights(),
    *,
    seed: int = 0,
    time_limit: float = 30.0,
    top_pairs: int = 1500,
    workers: int = 1,
    separate: Iterable[tuple[str, str]] = (),
) -> SolverResult:
    """OR-Tools CP-SAT solver.

    Hard rules are exact constraints. The objective penalizes the most similar
    pairs placed in the same packet; ordering within packets is then optimized
    with the shared local search. ``separate`` pairs may never share a packet.
    """
    if cp_model is None:
        raise RuntimeError("cpsat_solver requires ortools: pip install -r requirements-dev.txt")
    started = time.perf_counter()
    reasons = check_pool_feasibility(pool, spec)
    if reasons:
        raise InfeasibleError(reasons)
    index = PoolIndex.from_pool(pool)
    scorer = CachedScorer(scorer)

    model = cp_model.CpModel()
    packets = range(spec.packet_count)
    ids = (*index.tossup_ids, *index.bonus_ids)
    x = {(q, p): model.NewBoolVar(f"x_{n}_{p}") for n, q in enumerate(ids) for p in packets}
    for q in ids:
        model.AddAtMostOne(x[q, p] for p in packets)

    def matching(selector) -> list[str]:
        return [q for q in ids if selector.matches(index.selector_of[q])]

    def packet_sum(questions, p):
        return sum(x[q, p] for q in questions)

    by_type = {"tossup": index.tossup_ids, "bonus": index.bonus_ids}
    capacities = {"tossup": spec.tossup_capacity, "bonus": spec.bonus_capacity}
    for p in packets:
        for question_type, capacity in capacities.items():
            model.Add(packet_sum(by_type[question_type], p) == capacity)
        for quota in spec.quotas:
            expr = packet_sum(matching(quota.selector), p)
            model.Add(expr >= quota.minimum)
            if quota.maximum is not None:
                model.Add(expr <= quota.maximum)
        for rule_number, rule in enumerate(spec.allowed_patterns):
            if isinstance(rule, AllowedCountPatterns):
                counts = []
                for selector in rule.selectors:
                    var = model.NewIntVar(0, spec.tossup_capacity + spec.bonus_capacity, "")
                    model.Add(var == packet_sum(matching(selector), p))
                    counts.append(var)
                model.AddAllowedAssignments(counts, [list(pattern) for pattern in rule.patterns])
            elif isinstance(rule, CategoryCountRule):
                in_rule = {
                    question_type: [
                        q
                        for q in by_type[question_type]
                        if index.category_of[q] in rule.categories
                    ]
                    for question_type in by_type
                }
                model.Add(packet_sum(in_rule["tossup"], p) == rule.tossup_count)
                model.Add(packet_sum(in_rule["bonus"], p) == rule.bonus_count)
                if rule.distinct_categories:
                    for category in rule.categories:
                        questions = [
                            q for q in ids if index.category_of[q] == category
                        ]
                        model.Add(packet_sum(questions, p) <= 1)
            else:
                for question_type, target in (
                    ("tossup", rule.tossup_count),
                    ("bonus", rule.bonus_count),
                ):
                    questions = [
                        q
                        for group in rule.groups
                        for q in by_type[question_type]
                        if index.category_of[q] in group.categories
                    ]
                    model.Add(packet_sum(questions, p) == target)
                for group in rule.groups:
                    questions = [
                        q
                        for q in ids
                        if index.category_of[q] in group.categories
                    ]
                    model.Add(packet_sum(questions, p) == group.total_count)
                    maximum_per_type = group.total_count - group.minimum_per_type
                    for question_type in ("tossup", "bonus"):
                        group_questions = [
                            q
                            for q in by_type[question_type]
                            if index.category_of[q] in group.categories
                        ]
                        model.Add(
                            packet_sum(group_questions, p) >= group.minimum_per_type
                        )
                        model.Add(packet_sum(group_questions, p) <= maximum_per_type)
                    for category in group.categories:
                        category_questions = [
                            q for q in questions if index.category_of[q] == category
                        ]
                        model.Add(
                            packet_sum(category_questions, p)
                            >= group.minimum_per_category
                        )
                        if group.maximum_per_category_per_type is not None:
                            for question_type in ("tossup", "bonus"):
                                category_type_questions = [
                                    q
                                    for q in by_type[question_type]
                                    if index.category_of[q] == category
                                ]
                                model.Add(
                                    packet_sum(category_type_questions, p)
                                    <= group.maximum_per_category_per_type
                                )
                    if group.distinct_categories:
                        for category in group.categories:
                            category_questions = [
                                q
                                for q in ids
                                if index.category_of[q] == category
                            ]
                            model.Add(packet_sum(category_questions, p) <= 1)
                    if (
                        group.minimum_distinct_categories
                        or group.maximum_distinct_categories is not None
                        or group.disjoint_types
                    ):
                        used_flags = []
                        for category in group.categories:
                            type_flags = {}
                            for question_type in ("tossup", "bonus"):
                                category_type_questions = [
                                    q
                                    for q in by_type[question_type]
                                    if index.category_of[q] == category
                                ]
                                flag = model.NewBoolVar(f"g_{p}_{category}_{question_type}")
                                if category_type_questions:
                                    total = packet_sum(category_type_questions, p)
                                    model.Add(total >= 1).OnlyEnforceIf(flag)
                                    model.Add(total == 0).OnlyEnforceIf(flag.Not())
                                else:
                                    model.Add(flag == 0)
                                type_flags[question_type] = flag
                            used = model.NewBoolVar(f"g_{p}_{category}_used")
                            model.AddMaxEquality(used, list(type_flags.values()))
                            used_flags.append(used)
                            if group.disjoint_types:
                                model.AddBoolOr(
                                    [type_flags["tossup"].Not(), type_flags["bonus"].Not()]
                                )
                        model.Add(sum(used_flags) >= group.minimum_distinct_categories)
                        if group.maximum_distinct_categories is not None:
                            model.Add(sum(used_flags) <= group.maximum_distinct_categories)

    for quota in spec.aggregate_quotas:
        total = sum(packet_sum(matching(quota.selector), p) for p in packets)
        model.Add(total >= quota.minimum)
        if quota.maximum is not None:
            model.Add(total <= quota.maximum)

    for question_type, questions in by_type.items():
        bound = next(
            (b for b in spec.leftover_bounds if b.question_type == question_type),
            LeftoverBound(question_type),
        )
        leftover = len(questions) - sum(packet_sum(questions, p) for p in packets)
        model.Add(leftover >= bound.minimum)
        if bound.maximum is not None:
            model.Add(leftover <= bound.maximum)

    for a, b in separate:
        if (a, 0) in x and (b, 0) in x:
            for p in packets:
                model.Add(x[a, p] + x[b, p] <= 1)

    pair_scores = sorted(
        (
            (scorer.score(a, b), a, b)
            for questions in by_type.values()
            for a, b in combinations(questions, 2)
        ),
        reverse=True,
    )[:top_pairs]
    penalties = []
    for score, a, b in pair_scores:
        weight = round(score * weights.same_packet * PENALTY_SCALE)
        if weight <= 0:
            continue
        for p in packets:
            together = model.NewBoolVar("")
            model.Add(together >= x[a, p] + x[b, p] - 1)
            penalties.append(weight * together)
    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    status = solver.Solve(model)
    if status == cp_model.INFEASIBLE:
        raise InfeasibleError(["CP-SAT proved the hard rules infeasible"])
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise InfeasibleError([f"CP-SAT found no solution within {time_limit}s"])

    rng = random.Random(seed)
    layouts = []
    for p in packets:
        tossups = tuple(q for q in index.tossup_ids if solver.BooleanValue(x[q, p]))
        bonuses = tuple(q for q in index.bonus_ids if solver.BooleanValue(x[q, p]))
        layouts.append(
            optimize_order(
                PacketLayout(tossups, bonuses), index.category_of, scorer, weights, rng,
                separation=spec.separation, selector_of=index.selector_of,
            )
        )
    return finish_result(
        "cp-sat",
        seed,
        index,
        spec,
        layouts,
        scorer,
        weights,
        time.perf_counter() - started,
        {
            "status": solver.StatusName(status),
            "objective": solver.ObjectiveValue() / PENALTY_SCALE,
            "bound": solver.BestObjectiveBound() / PENALTY_SCALE,
        },
    )
