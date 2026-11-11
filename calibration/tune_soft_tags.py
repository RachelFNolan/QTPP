"""Score hand-reviewed History tags against the current 7-era, 22-region vocabulary (experimental).

Reads verdicts from a review Markdown file (default ``tagger_data/reviews/tag_review.md``).
Old review names are mapped to current tags; current tag names are accepted as-is. Old tags
that span two current tags are ignored. Prints counts and metrics only; no question text.
Use ``--fixed`` to score only the current default temperatures, without re-tuning.
Run from the repository root: python3 -m calibration.tune_soft_tags
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

from .soft_tags_updated import ERA_TEMPERATURE, ERAS, REGION_TEMPERATURE, REGIONS, SoftTagger
from .tagger_dataset import DEFAULT_DIRECTORY, load_examples

REVIEW = DEFAULT_DIRECTORY / "reviews" / "tag_review.md"

# Old review names -> current tag. ``None`` means the old tag spans two current tags.
OLD_ERAS: dict[str, str | None] = {
    "Prehistory and early civilizations": "Ancient",
    "Classical antiquity": "Ancient",
    "Late antiquity and early medieval": "Medieval",
    "High and late medieval": "Medieval",
    "Renaissance and Reformation": "Early modern",
    "Absolutism and early modern": "Early modern",
    "Enlightenment and revolutions": None,
    "Industrial age and nationalism": "Revolutionary and industrial age",
    "Imperialism and the Gilded Age": "Imperial age and World War I",
    "World War I and the interwar years": None,
    "World War II and early Cold War": None,
    "Late Cold War to present": "Postwar to present",
}
OLD_REGIONS: dict[str, str | None] = {
    "United States": "United States",
    "Canada": "Canada",
    "Britain": "British Isles",
    "Ireland": "British Isles",
    "Iberia": "Iberia",
    "France": "France",
    "Italy": "Italy",
    "Germany and Central Europe": "Germany and Central Europe",
    "Low Countries and Scandinavia": "Low Countries and Scandinavia",
    "Russia and the Soviet Union": "Russia and the Soviet Union",
    "Eastern Europe and the Balkans": "Eastern Europe and the Balkans",
    "Rome and the Roman world": "Ancient/Classical Mediterranean",
    "Greece and the Aegean": "Ancient/Classical Mediterranean",
    "Egypt": "Egypt and North Africa",
    "North Africa": "Egypt and North Africa",
    "West Africa": "Sub-Saharan Africa",
    "East and Southern Africa": "Sub-Saharan Africa",
    "Mesopotamia and Persia": "Southwest Asia",
    "Levant and Arabia": "Southwest Asia",
    "Ottoman Empire and Turkey": "Southwest Asia",
    "India and South Asia": "India and South Asia",
    "China": "China",
    "Japan": "Japan",
    "Central Asia and the Steppe": "Central Asia and the Steppe",
    "Australia and the Pacific": "Australia and the Pacific",
    "Mexico and Central America": "Latin America",
    "Caribbean": "Latin America",
    "Andes and Southern Cone": "Latin America",
}

HEADING = re.compile(r"^## .*\(`([^`]+)`\)")
VERDICT = re.compile(r"^- (era|region): (.+?)(?: \([\d.]+\))?\s+verdict:\s*(\S*)\s*$")
MISSING = re.compile(r"^- missing (era|region):\s*(.*)$")


def name_mapping(kind: str) -> dict[str, str | None]:
    """Review names -> current tags: old names from the first review plus current names as-is."""
    old = OLD_ERAS if kind == "era" else OLD_REGIONS
    vocabulary = ERAS if kind == "era" else REGIONS
    return {**{tag: tag for tag in vocabulary}, **old}


def parse_review(path: Path) -> tuple[dict, dict[str, int]]:
    """Return {question id: {current tag: True/False}} for eras and regions, plus parse counts."""
    labels: dict[str, dict[str, dict[str, bool]]] = {"era": defaultdict(dict), "region": defaultdict(dict)}
    skipped = {"ambiguous": 0, "unmapped": 0, "unknown_verdict": 0}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = HEADING.match(line)
        if heading:
            current = heading.group(1)
            continue
        if current is None:
            continue
        verdict = VERDICT.match(line)
        if verdict:
            kind, old, value = verdict.group(1), verdict.group(2).strip(), verdict.group(3).lower()
            if value not in ("y", "n"):
                skipped["unknown_verdict"] += 1
                continue
            if old == "(none suggested)":
                continue
            mapping = name_mapping(kind)
            if old not in mapping:
                skipped["unmapped"] += 1
                continue
            new = mapping[old]
            if new is None:
                skipped["ambiguous"] += 1
                continue
            labels[kind][current][new] = value == "y"
            continue
        missing = MISSING.match(line)
        if missing:
            kind = missing.group(1)
            mapping = name_mapping(kind)
            for name in (part.strip() for part in missing.group(2).split(",")):
                if not name:
                    continue
                if name not in mapping:
                    skipped["unmapped"] += 1
                    continue
                new = mapping[name]
                if new is None:
                    skipped["ambiguous"] += 1
                    continue
                labels[kind][current][new] = True
    return labels, skipped


def evaluate(tagger: SoftTagger, texts: list[str], judged: list[dict[str, bool]], thresholds) -> None:
    confidences = tagger.confidences(texts)
    total_positive = sum(1 for row in judged for value in row.values() if value)
    print(f"  temperature {tagger.temperature}: judged positives {total_positive}")
    print(f"  {'threshold':>9}{'predicted':>10}{'correct':>9}{'precision':>11}{'recall':>9}{'unjudged':>10}")
    for threshold in thresholds:
        predicted = correct = unjudged = found = 0
        for row, labels in zip(confidences, judged):
            for index, value in enumerate(row):
                if value < threshold:
                    continue
                tag = tagger.tags[index]
                if tag not in labels:
                    unjudged += 1
                    continue
                predicted += 1
                correct += labels[tag]
                found += labels[tag]
        precision = correct / predicted if predicted else float("nan")
        recall = found / total_positive if total_positive else float("nan")
        print(f"  {threshold:>9.2f}{predicted:>10}{correct:>9}{precision:>11.0%}{recall:>9.0%}{unjudged:>10}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--source", choices=("dev", "validation"), default="dev",
                        help="question pool the review was drawn from")
    parser.add_argument("--fixed", action="store_true",
                        help="score only the current default temperatures, with no sweep")
    args = parser.parse_args()

    labels, skipped = parse_review(args.review)
    print(f"reviewed questions: {len(labels['era'].keys() | labels['region'].keys())}")
    print(f"skipped entries: {skipped}\n")

    dev, validation = load_examples(labeled_only=False)
    pool = validation if args.source == "validation" else dev
    by_id = {e.question_id: e.text for e in pool if e.category == "History"}
    ids = sorted(set(labels["era"]) | set(labels["region"]))
    missing_text = [i for i in ids if i not in by_id]
    if missing_text:
        raise SystemExit(f"{len(missing_text)} reviewed questions not found in the {args.source} pool")
    texts = [by_id[i] for i in ids]

    if args.fixed:
        thresholds = [0.2, 0.25, 0.3, 0.4, 0.5]
        temperatures = None
    else:
        thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        temperatures = [0.02, 0.03, 0.05, 0.08]
    for kind, vocabulary, default in (("era", ERAS, ERA_TEMPERATURE), ("region", REGIONS, REGION_TEMPERATURE)):
        judged = [labels[kind].get(i, {}) for i in ids]
        print(f"== {kind} ==")
        for temperature in temperatures or [default]:
            evaluate(SoftTagger(vocabulary, temperature), texts, judged, thresholds)
        if not temperatures:
            print(f"  (fixed at current default temperature: {default})\n")
        else:
            print(f"  (current default temperature: {default})\n")


if __name__ == "__main__":
    main()
