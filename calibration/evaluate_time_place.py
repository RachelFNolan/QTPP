"""Measure how often the rule-based era and region detectors produce a tag (experimental).

Prints counts only; no question text. Run from the repository root:
python3 -m calibration.evaluate_time_place [DIRECTORY]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from qtpp.time_place import detect_era, detect_region

from .tagger_dataset import DEFAULT_DIRECTORY, load_examples


def coverage(examples) -> None:
    by_category: dict[str, list] = defaultdict(list)
    for example in examples:
        by_category[example.category].append(example)
    print(f"{'category':<24}{'n':>6}{'era %':>8}{'region %':>10}{'either %':>10}")
    for category, items in sorted(by_category.items(), key=lambda pair: -len(pair[1])):
        eras = [detect_era(e.text) for e in items]
        regions = [detect_region(e.text) for e in items]
        either = sum(1 for era, region in zip(eras, regions) if era or region)
        n = len(items)
        print(
            f"{category:<24}{n:>6}"
            f"{100 * sum(1 for x in eras if x) / n:>8.0f}"
            f"{100 * sum(1 for x in regions if x) / n:>10.0f}"
            f"{100 * either / n:>10.0f}"
        )
    print()
    for title, detect in (("era", detect_era), ("region", detect_region)):
        counts = Counter(detect(e.text) or "(none)" for e in examples)
        print(f"{title} distribution")
        for label, count in counts.most_common():
            print(f"  {label:<36}{count:>6}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args()
    dev, validation = load_examples(args.directory, labeled_only=False)
    examples = dev + validation
    print(f"{len(examples)} questions\n")
    coverage(examples)


if __name__ == "__main__":
    main()
