"""Audit a local corpus of question pools for tagger evaluation.

Reads every CSV/JSON file in ``tagger_data/`` (untracked) through QTPP's field
mapping and reports counts and label coverage. Prints aggregate statistics
only; question text is never written anywhere.

    python3 calibration/tagger_corpus.py [DIRECTORY]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qtpp import QuestionSet  # noqa: E402
from qtpp.csv_import import load_question_pool_csv  # noqa: E402
from qtpp.field_mapping import (  # noqa: E402
    inspect_csv,
    inspect_json,
    mapped_csv_text,
    mapped_pool_json,
)
from qtpp.pool_json_import import parse_question_pool_json  # noqa: E402
from qtpp.similarity import question_text  # noqa: E402

DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "tagger_data"
MIN_PER_LABEL = 20


def load_source(path: Path) -> QuestionSet:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        mapping = inspect_csv(text, path.name)["suggestion"]["mapping"]
        mapped = mapped_csv_text(text, mapping, path.name)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", suffix=".csv", delete=False
        ) as temporary:
            temporary.write(mapped)
            temporary_path = Path(temporary.name)
        try:
            return load_question_pool_csv(temporary_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    mapping = inspect_json(text, path.name)["suggestion"]["mapping"]
    return parse_question_pool_json(mapped_pool_json(text, mapping, path.name), path.name)


def _questions(pool: QuestionSet):
    yield from pool.tossups
    yield from pool.bonuses


def _fingerprint(question) -> str:
    text = re.sub(r"\W+", " ", question_text(question).lower()).strip()
    return hashlib.sha1(text.encode()).hexdigest()


def report(directory: Path) -> int:
    files = sorted(
        path for path in directory.glob("*") if path.suffix.lower() in {".csv", ".json"}
    )
    if not files:
        print(f"No CSV or JSON files found in {directory}.")
        return 1

    seen: set[str] = set()
    corpus_alternates: Counter[tuple[str, str]] = Counter()
    corpus_total = corpus_labeled = corpus_duplicates = 0

    for path in files:
        try:
            pool = load_source(path)
        except (OSError, ValueError) as error:
            print(f"\n{path.name}: could not import ({error})")
            continue
        questions = list(_questions(pool))
        labeled = [q for q in questions if (q.metadata.topic.alternate_subcategory or "").strip()]
        duplicates = 0
        for question in questions:
            fingerprint = _fingerprint(question)
            if fingerprint in seen:
                duplicates += 1
            else:
                seen.add(fingerprint)
                topic = question.metadata.topic
                alternate = (topic.alternate_subcategory or "").strip()
                if alternate:
                    corpus_alternates[(topic.category, alternate)] += 1
        corpus_total += len(questions)
        corpus_labeled += len(labeled)
        corpus_duplicates += duplicates
        categories = Counter(q.metadata.topic.category for q in questions)
        subcategories = {q.metadata.topic.subcategory for q in questions}
        print(f"\n{path.name}")
        print(f"  tossups {len(pool.tossups)}, bonuses {len(pool.bonuses)}")
        print(f"  categories {len(categories)}, subcategories {len(subcategories)}")
        print(
            f"  alternate subcategory: {len(labeled)} labeled"
            f" ({100 * len(labeled) / max(len(questions), 1):.0f}%)"
        )
        print(f"  already seen in earlier files: {duplicates}")
        print("  top categories:", ", ".join(f"{k} {v}" for k, v in categories.most_common(6)))

    unique = corpus_total - corpus_duplicates
    print(f"\nCorpus: {corpus_total} questions, {unique} unique, {corpus_labeled} with alternate subcategory")
    usable = {key: n for key, n in corpus_alternates.items() if n >= MIN_PER_LABEL}
    print(
        f"Alternate-subcategory labels: {len(corpus_alternates)} distinct,"
        f" {len(usable)} with at least {MIN_PER_LABEL} unique examples"
    )
    for (category, alternate), count in corpus_alternates.most_common(25):
        print(f"  {category} / {alternate}: {count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args()
    return report(args.directory)


if __name__ == "__main__":
    raise SystemExit(main())
