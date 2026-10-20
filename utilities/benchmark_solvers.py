"""Benchmark the baseline and CP-SAT solvers on a pool and template.

Usage:
    python3 -m utilities.benchmark_solvers [--packets 8 12 16] [--seeds 3]
        [--template PATH] [--pool CSV] [--time-limit 30] [--all-scorers]
        [--embeddings]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from statistics import mean

from qtpp import (
    InfeasibleError,
    build_similarity,
    load_question_pool_csv,
    load_template,
    solve_baseline,
    solve_cpsat,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=ROOT / "Test Questions" / "2025 ACF Winter" / "Question Pool.csv")
    parser.add_argument("--template", type=Path, default=ROOT / "templates" / "acf-winter-final.json")
    parser.add_argument("--packets", type=int, nargs="+", default=[8, 12, 16])
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument(
        "--all-scorers",
        action="store_true",
        help="benchmark both solvers with each scorer in calibration.evaluate_similarity",
    )
    parser.add_argument(
        "--embeddings",
        action="store_true",
        help="include the optional bge-small embedding scorers (requires fastembed)",
    )
    args = parser.parse_args()

    pool = load_question_pool_csv(args.pool)
    template = load_template(args.template)
    if args.all_scorers:
        from calibration.evaluate_similarity import build_scorers

        scorers = build_scorers(pool, args.embeddings)
    else:
        scorers = {"default similarity": build_similarity(pool)}
    print(
        f"{'scorer':<36} {'packets':>7} {'solver':<16} {'valid':>5} "
        f"{'soft mean':>10} {'soft best':>10} {'sec mean':>9}"
    )
    for scorer_name, scorer in scorers.items():
        solvers = {
            "python-baseline": lambda spec, seed: solve_baseline(
                pool, spec, scorer, seed=seed
            ),
            "cp-sat": lambda spec, seed: solve_cpsat(
                pool, spec, scorer, seed=seed, time_limit=args.time_limit
            ),
        }
        for packets in args.packets:
            spec = template.create_spec(packets)
            for name, run in solvers.items():
                results = []
                for seed in range(args.seeds):
                    try:
                        results.append(run(spec, seed))
                    except InfeasibleError as error:
                        print(f"{scorer_name:<36} {packets:>7} {name:<16} error: {error}")
                        break
                if not results:
                    continue
                valid = sum(not result.hard_errors for result in results)
                totals = [result.score.total for result in results]
                print(
                    f"{scorer_name:<36} {packets:>7} {name:<16} "
                    f"{valid}/{len(results):<3} {mean(totals):>10.1f} "
                    f"{min(totals):>10.1f} {mean(r.seconds for r in results):>9.1f}"
                )


if __name__ == "__main__":
    main()
