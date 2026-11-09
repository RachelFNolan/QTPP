"""Write a CSV of History questions with suggested era and region tags for hand review (experimental).

The file contains question text, so it is written under the gitignored
``tagger_data/`` folder by default. Fill the ``verdict`` column with y, n or ?.
Run from the repository root: python3 -m calibration.make_tag_review [--per-subcategory N]
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from .soft_tags_updated import ERA_TEMPERATURE, ERAS, REGION_TEMPERATURE, REGIONS, SoftTagger
from .tagger_dataset import DEFAULT_DIRECTORY, load_examples

SEED = 7
THRESHOLD = 0.2
LIMIT = 3
FIELDS = (
    "question_id", "subcategory", "text", "kind", "tag", "confidence", "verdict",
    "missing_era", "missing_region", "note",
)


def spread_sample(indexes: list[int], strength: np.ndarray, count: int) -> list[int]:
    """Pick ``count`` questions evenly across the range of top region confidence."""
    ordered = sorted(indexes, key=lambda i: strength[i])
    if len(ordered) <= count:
        return ordered
    positions = np.linspace(0, len(ordered) - 1, count).round().astype(int)
    return [ordered[p] for p in positions]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-subcategory", type=int, default=10)
    parser.add_argument("--source", choices=("dev", "validation"), default="dev")
    parser.add_argument("--output", type=Path, default=DEFAULT_DIRECTORY / "reviews" / "tag_review.csv")
    args = parser.parse_args()

    dev, validation = load_examples(labeled_only=False)
    pool = validation if args.source == "validation" else dev
    history = [e for e in pool if e.category == "History"]
    texts = [e.text for e in history]
    era_tagger = SoftTagger(ERAS, ERA_TEMPERATURE)
    region_tagger = SoftTagger(REGIONS, REGION_TEMPERATURE)
    strength = region_tagger.confidences(texts).max(axis=1)

    by_subcategory: dict[str, list[int]] = defaultdict(list)
    for index, example in enumerate(history):
        by_subcategory[example.subcategory].append(index)

    chosen: list[int] = []
    for subcategory in sorted(by_subcategory):
        chosen.extend(spread_sample(by_subcategory[subcategory], strength, args.per_subcategory))
    random.Random(SEED).shuffle(chosen)

    chosen_texts = [texts[i] for i in chosen]
    eras = era_tagger.suggest(chosen_texts, THRESHOLD, LIMIT)
    regions = region_tagger.suggest(chosen_texts, THRESHOLD, LIMIT)

    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for index, era_tags, region_tags in zip(chosen, eras, regions):
            example = history[index]
            first = True
            for kind, tags in (("era", era_tags), ("region", region_tags)):
                for tag in tags or []:
                    writer.writerow(
                        {
                            "question_id": example.question_id,
                            "subcategory": example.subcategory,
                            "text": example.text if first else "",
                            "kind": kind,
                            "tag": tag.tag,
                            "confidence": f"{tag.score:.2f}",
                        }
                    )
                    first = False
            if first:
                writer.writerow(
                    {"question_id": example.question_id, "subcategory": example.subcategory,
                     "text": example.text, "kind": "none"}
                )
    print(f"wrote {len(chosen)} questions to {args.output}")


if __name__ == "__main__":
    main()
