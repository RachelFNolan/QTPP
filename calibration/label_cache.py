"""Manage the committed similarity-label cache (calibration/labels.jsonl).

Usage:
    python3 -m calibration.label_cache seed --pairs JSON --pool CSV [--reviewer NAME]
    python3 -m calibration.label_cache summary

`seed` copies the labels from a reviewed pair file into the cache (skipping
pairs already cached with the same label). The web app's Audit view appends to
the same file. The cache holds IDs and content hashes only, never question text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qtpp import load_question_pool_csv, question_text
from qtpp.label_store import DEFAULT_LABELS, append_label, label_summary, load_labels, pair_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "Test Questions" / "2025 ACF Winter" / "Question Pool.csv"
DEFAULT_PAIRS = ROOT / "calibration" / "similarity_pairs.json"


def seed(pairs_path: Path, pool_path: Path, labels_path: Path, reviewer: str) -> int:
    data = json.loads(pairs_path.read_text(encoding="utf-8"))
    if not data.get("reviewed"):
        raise SystemExit(f"{pairs_path} is not marked reviewed; labels would be heuristic guesses.")
    pool = load_question_pool_csv(pool_path)
    texts = {q.metadata.id: question_text(q) for q in (*pool.tossups, *pool.bonuses)}
    kinds = {q.metadata.id: ("tossup" if q in pool.tossups else "bonus") for q in (*pool.tossups, *pool.bonuses)}
    existing = load_labels(labels_path)
    added = 0
    for pair in data["pairs"]:
        first, second = pair["first_id"], pair["second_id"]
        if first not in texts or second not in texts:
            continue
        label = "borderline" if pair.get("borderline") else ("similar" if pair["label"] else "different")
        key = pair_key(texts[first], texts[second])
        if existing.get(key, {}).get("label") == label:
            continue
        append_label(
            labels_path, key=key, first_id=first, second_id=second, label=label,
            reviewer=reviewer, source="calibration", pool=pool.metadata.name,
            question_types="-".join(sorted((kinds[first], kinds[second]))),
        )
        added += 1
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "summary"])
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--reviewer", default="")
    args = parser.parse_args()
    if args.command == "seed":
        print(f"Added {seed(args.pairs, args.pool, args.labels, args.reviewer)} labels to {args.labels}")
    else:
        counts = label_summary(load_labels(args.labels).values())
        print(", ".join(f"{key}: {value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()
