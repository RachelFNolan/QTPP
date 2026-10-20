from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Sequence

from .baseline_solver import solve_baseline
from .build_spec import PacketBuildSpec
from .cpsat_solver import solve_cpsat
from .model import Packet, QuestionPlacement, QuestionSet
from .scoring import SoftScore, SoftWeights
from .similarity import PairScorer
from .solving import InfeasibleError, SolverResult


@dataclass(frozen=True, slots=True)
class GenerationReport:
    """Reproducibility details and remaining soft penalties for a generated draft."""

    solver: str
    seed: int
    packet_count: int
    score: SoftScore
    leftover_ids: tuple[str, ...]
    seconds: float


@dataclass(frozen=True, slots=True)
class GeneratedPackets:
    question_set: QuestionSet
    report: GenerationReport


def build_question_set(
    pool: QuestionSet,
    result: SolverResult,
    packet_names: Sequence[str] | None = None,
) -> QuestionSet:
    """Attach a solver result's ordered layouts to the pool as numbered packets.

    The pool's questions are kept unchanged, so unassigned questions remain in it.
    Raises InfeasibleError if the result violates a hard rule.
    """
    if result.hard_errors:
        raise InfeasibleError(result.hard_errors)
    if packet_names is not None and len(packet_names) != len(result.layouts):
        raise ValueError("packet_names must have one entry per packet")
    packets = []
    for number, layout in enumerate(result.layouts, start=1):
        packets.append(
            Packet(
                id=f"{pool.metadata.id}-packet-{number:02d}",
                name=packet_names[number - 1] if packet_names else f"Packet {number:02d}",
                number=number,
                tossups=tuple(
                    QuestionPlacement(question_id, position)
                    for position, question_id in enumerate(layout.tossups, start=1)
                ),
                bonuses=tuple(
                    QuestionPlacement(question_id, position)
                    for position, question_id in enumerate(layout.bonuses, start=1)
                ),
            )
        )
    return replace(pool, packets=tuple(packets))


def generate_packets(
    pool: QuestionSet,
    spec: PacketBuildSpec,
    scorer: PairScorer,
    weights: SoftWeights = SoftWeights(),
    *,
    solver: Literal["baseline", "cpsat"] = "baseline",
    seed: int = 0,
    packet_names: Sequence[str] | None = None,
    **solver_options: object,
) -> GeneratedPackets:
    """Solve and materialize a draft; the same seed and inputs reproduce the same draft.

    Raises InfeasibleError when the hard rules cannot be met.
    """
    if solver == "baseline":
        result = solve_baseline(pool, spec, scorer, weights, seed=seed, **solver_options)
    elif solver == "cpsat":
        result = solve_cpsat(pool, spec, scorer, weights, seed=seed, **solver_options)
    else:
        raise ValueError(f"unknown solver {solver!r}")
    question_set = build_question_set(pool, result, packet_names)
    report = GenerationReport(
        solver=result.solver,
        seed=result.seed,
        packet_count=len(result.layouts),
        score=result.score,
        leftover_ids=result.leftover_ids,
        seconds=result.seconds,
    )
    return GeneratedPackets(question_set, report)
