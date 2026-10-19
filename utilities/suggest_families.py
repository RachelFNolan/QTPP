"""Suggest topic-family tags for questions with no alternate subcategory.

Suggest (writes a file for human review; nothing is applied to builds):
    python3 -m utilities.suggest_families suggest --pool CSV --labels labels.json \
        --output suggestions.json [--backend fastembed|sentence-transformers|tfidf] \
        [--model NAME] [--curated families.json] [--subcategory "Other History" ...] [--min-score 0.2] [--min-margin 0.02]

Approve (after editing labels in the suggestions file) into a families file
usable with load_curated_families:
    python3 -m utilities.suggest_families approve suggestions.json --output families.json

labels.json: {"labels": {"Military": "battles, wars, armies, campaigns", ...}}
A label value may also be a list of example phrases.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packetizer import load_curated_families, load_question_pool_csv
from packetizer.family_suggest import (
    approve_suggestions,
    get_backend,
    load_labels,
    questions_missing_family,
    save_suggestions,
    suggest_families,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    suggest = commands.add_parser("suggest")
    suggest.add_argument("--pool", type=Path, required=True)
    suggest.add_argument("--labels", type=Path, required=True)
    suggest.add_argument("--output", type=Path, required=True)
    suggest.add_argument(
        "--backend", choices=["tfidf", "fastembed", "sentence-transformers"], default="fastembed"
    )
    suggest.add_argument("--model")
    suggest.add_argument("--curated", type=Path, help="skip questions already in this families file")
    suggest.add_argument(
        "--subcategory", action="append", help="only classify this primary subcategory (repeatable)"
    )
    suggest.add_argument("--min-score", type=float, default=0.2)
    suggest.add_argument("--min-margin", type=float, default=0.02)

    approve = commands.add_parser("approve")
    approve.add_argument("suggestions", type=Path)
    approve.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "approve":
        families = approve_suggestions(args.suggestions)
        args.output.write_text(json.dumps({"families": families}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(families)} families to {args.output}")
        return

    pool = load_question_pool_csv(args.pool)
    curated = load_curated_families(args.curated) if args.curated else None
    suggestions = suggest_families(
        pool,
        load_labels(args.labels),
        get_backend(args.backend, args.model),
        curated=curated,
        subcategories=args.subcategory,
        min_score=args.min_score,
        min_margin=args.min_margin,
    )
    save_suggestions(suggestions, args.output)
    confident = sum(item.label is not None for item in suggestions)
    total = len(questions_missing_family(pool, curated, args.subcategory))
    print(f"{total} questions without an alternate: {confident} proposed, {total - confident} unsure")
    print(f"wrote {args.output}; review it, then run the approve command")


if __name__ == "__main__":
    main()
