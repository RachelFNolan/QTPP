"""Sample candidate question pairs for tuning the similarity score.

Writes a JSON fixture where every pair carries a heuristic pre-label. Review the
file and edit each pair's "label" (true = related, false = unrelated, optionally
"borderline": true), then set "reviewed" to true at the top level.

Usage:
    python3 -m calibration.sample_similarity_pairs [--pool CSV] [--output JSON] [--seed N]
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
from collections import Counter
from pathlib import Path

from qtpp import (
    TfidfSimilarity,
    load_question_pool_csv,
    question_text,
)
from qtpp.similarity import primary_answer

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "Test Questions" / "2025 ACF Winter" / "Question Pool.csv"
DEFAULT_OUTPUT = ROOT / "calibration" / "similarity_pairs.json"

_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{3,}\b")
_COMMON = frozenset(
    "Name Give This That These Those Each Points Another Identify Description Answer "
    "For Which What One Two Three".split()
)


def proper_nouns(text: str) -> set[str]:
    return {word for word in _PROPER.findall(text) if word not in _COMMON}


def display_text(kind: str, item) -> str:
    topic = item.metadata.topic
    header = f"[{kind}, {topic.category} / {topic.subcategory}]"
    if kind == "tossup":
        return (
            f"{header}\n{item.question_sanitized or item.question}\n"
            f"ANSWER: {item.answer_sanitized or item.answer}"
        )
    parts = "\n".join(
        f"[{part.number}] {part.question_sanitized or part.question}\n"
        f"ANSWER: {part.answer_sanitized or part.answer}"
        for part in item.parts
    )
    return f"{header}\n{item.leadin_sanitized or item.leadin}\n{parts}"


def can_share_packet(first: dict, second: dict) -> bool:
    """Templates cap each subcategory at one question per type per packet."""
    return first["type"] != second["type"] or first["subcategory"] != second["subcategory"]


def heuristic_label(
    first: dict, second: dict, name_frequency: Counter
) -> tuple[bool, str]:
    for source, target in ((first, second), (second, first)):
        answer = primary_answer(source["answer"]).strip()
        if len(answer) >= 4 and answer.lower() in target["text"].lower():
            return True, f"answer of {source['id'][-6:]} appears in {target['id'][-6:]}"
    shared = {
        name
        for name in proper_nouns(first["text"]) & proper_nouns(second["text"])
        if name_frequency[name] <= 3
    }
    if len(shared) >= 2:
        return True, "shares rare names: " + ", ".join(sorted(shared)[:4])
    return False, "no shared answer or rare names"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    pool = load_question_pool_csv(args.pool)
    questions = []
    for kind, items in (("tossup", pool.tossups), ("bonus", pool.bonuses)):
        for item in items:
            answer = (
                item.answer_sanitized or item.answer
                if kind == "tossup"
                else item.parts[0].answer_sanitized or item.parts[0].answer
            )
            topic = item.metadata.topic
            questions.append(
                {
                    "id": item.metadata.id,
                    "type": kind,
                    "category": topic.category,
                    "subcategory": topic.subcategory,
                    "text": question_text(item),
                    "answer": answer,
                    "display": display_text(kind, item),
                }
            )
    by_id = {question["id"]: question for question in questions}
    lexical = TfidfSimilarity({q["id"]: q["text"] for q in questions})
    name_frequency: Counter = Counter()
    for question in questions:
        name_frequency.update(proper_nouns(question["text"]))

    rng = random.Random(args.seed)
    chosen: dict[frozenset, str] = {}

    def add(first: dict, second: dict, source: str, limit: int, taken: list[int]) -> None:
        key = frozenset((first["id"], second["id"]))
        if can_share_packet(first, second) and key not in chosen and taken[0] < limit:
            chosen[key] = source
            taken[0] += 1

    scored = sorted(
        (
            (lexical.score(a["id"], b["id"]), a["id"], b["id"])
            for a, b in itertools.combinations(questions, 2)
        ),
        reverse=True,
    )
    taken = [0]
    for _, first_id, second_id in scored[:200]:
        add(by_id[first_id], by_id[second_id], "high-lexical", 20, taken)

    entity_pairs = [
        (a, b)
        for a, b in itertools.combinations(questions, 2)
        if can_share_packet(a, b) and heuristic_label(a, b, name_frequency)[0]
    ]
    rng.shuffle(entity_pairs)
    taken = [0]
    for first, second in entity_pairs:
        add(first, second, "heuristic-positive", 15, taken)

    pairs = list(itertools.combinations(questions, 2))
    rng.shuffle(pairs)
    taken = [0]
    for first, second in pairs:
        if first["category"] == second["category"]:
            add(first, second, "same-category", 12, taken)
    taken = [0]
    for first, second in pairs:
        if first["category"] != second["category"]:
            add(first, second, "cross-category", 13, taken)

    records = []
    for key, source in chosen.items():
        first_id, second_id = sorted(key)
        first, second = by_id[first_id], by_id[second_id]
        related, reason = heuristic_label(first, second, name_frequency)
        records.append(
            {
                "first_id": first_id,
                "second_id": second_id,
                "source": source,
                "first": first["display"],
                "second": second["display"],
                "heuristic_reason": reason,
                "label": related,
                "borderline": False,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"reviewed": False, "seed": args.seed, "pairs": records}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    positives = sum(1 for record in records if record["label"])
    print(f"Wrote {len(records)} pairs ({positives} heuristic positives) to {args.output}")


if __name__ == "__main__":
    main()
