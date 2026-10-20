"""Suggest topic-family tags for questions with no alternate subcategory.

Suggest (writes a file for human review; nothing is applied to builds):
    python3 -m utilities.suggest_families suggest --pool CSV \
        [--taxonomy taxonomy.json | --labels labels.json] --output suggestions.json \
        [--auto-margin 0.06] [--no-examples] [--min-examples 5] [--backend fastembed|sentence-transformers|tfidf] \
        [--model NAME] [--curated families.json] [--subcategory "Other History" ...] [--min-score 0.2] [--min-margin 0.02]

Approve (after editing labels in the suggestions file) into a families file
usable with load_curated_families (--auto-only keeps just status "auto" entries):
    python3 -m utilities.suggest_families approve suggestions.json --output families.json [--auto-only]

Era and region tags for History/Literature spread penalties (review before use):
    python3 -m utilities.suggest_families time-place --pool CSV --output tags.json

--taxonomy defaults to qtpp/default_taxonomy.json (per-category labels with
descriptions and aliases; the schema is documented in qtpp/taxonomy.py).

labels.json: {"labels": {"Military": "battles, wars, armies, campaigns", ...}}
A label value may also be a list of example phrases.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qtpp import load_curated_families, load_question_pool_csv
from qtpp.taxonomy import DEFAULT_TAXONOMY, load_taxonomy
from qtpp.time_place import detect_eras, detect_regions, save_time_place_tags
from qtpp.family_suggest import (
    approve_suggestions,
    get_backend,
    load_labels,
    questions_missing_family,
    save_suggestions,
    suggest_families,
    suggest_with_taxonomy,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    suggest = commands.add_parser("suggest")
    suggest.add_argument("--pool", type=Path, required=True)
    suggest.add_argument("--labels", type=Path, help="flat labels file (applies to every question)")
    suggest.add_argument(
        "--taxonomy", type=Path, help=f"per-category taxonomy (default {DEFAULT_TAXONOMY.name})"
    )
    suggest.add_argument("--no-examples", action="store_true", help="skip the example-based check")
    suggest.add_argument("--min-examples", type=int, default=5)
    suggest.add_argument(
        "--auto-margin", type=float,
        help="proposals leading the runner-up by at least this get status auto (0.06 is a good start)",
    )
    suggest.add_argument("--output", type=Path, required=True)
    suggest.add_argument(
        "--backend", choices=["tfidf", "fastembed", "sentence-transformers"], default="fastembed"
    )
    suggest.add_argument("--model")
    suggest.add_argument("--curated", type=Path, help="skip questions already in this families file")
    suggest.add_argument(
        "--subcategory", action="append", help="only classify this primary subcategory (repeatable)"
    )
    suggest.add_argument("--min-score", type=float, default=0.0)
    suggest.add_argument("--min-margin", type=float, default=0.02)

    approve = commands.add_parser("approve")
    approve.add_argument("suggestions", type=Path)
    approve.add_argument("--output", type=Path, required=True)
    approve.add_argument("--auto-only", action="store_true")

    time_place = commands.add_parser("time-place")
    time_place.add_argument("--pool", type=Path, required=True)
    time_place.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "approve":
        families = approve_suggestions(args.suggestions, args.auto_only)
        args.output.write_text(json.dumps({"families": families}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(families)} families to {args.output}")
        return

    pool = load_question_pool_csv(args.pool)
    if args.command == "time-place":
        eras, regions = detect_eras(pool), detect_regions(pool)
        save_time_place_tags(eras, regions, args.output)
        print(f"{len(eras)} era tags, {len(regions)} region tags written to {args.output}")
        return

    curated = load_curated_families(args.curated) if args.curated else None
    backend = get_backend(args.backend, args.model)
    if args.labels:
        suggestions = suggest_families(
            pool,
            load_labels(args.labels),
            backend,
            curated=curated,
            subcategories=args.subcategory,
            min_score=args.min_score,
            min_margin=args.min_margin,
        )
    else:
        suggestions = suggest_with_taxonomy(
            pool,
            load_taxonomy(args.taxonomy or DEFAULT_TAXONOMY),
            backend,
            curated=curated,
            use_examples=not args.no_examples,
            min_examples=args.min_examples,
            min_score=args.min_score,
            min_margin=args.min_margin,
            auto_margin=args.auto_margin,
        )
    save_suggestions(suggestions, args.output)
    counts = {status: sum(item.status == status for item in suggestions) for status in ("auto", "review", "unsure")}
    total = len(questions_missing_family(pool, curated, args.subcategory))
    print(f"{total} questions without an alternate; {len(suggestions)} in taxonomy categories: {counts}")
    print(f"wrote {args.output}; review it, then run the approve command")


if __name__ == "__main__":
    main()
