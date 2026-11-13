"""Labeled dataset and date-based split for local tagger evaluation (experimental).

Builds alternate-subcategory examples from the gitignored ``tagger_data/``
folder and its subfolders (``reviews/`` is skipped). Questions from sets through 2024 are development data (training and
cross-validation); questions from 2025 onward are held out for formal
validation. Each question's year comes from its raw record (``set.year``, a
top-level ``year``, or the set name), or for CSV files, from a ``set_year`` column
or a year in the file name. Question IDs come from ``_id`` or ``id``. Questions
without a year are skipped. Duplicates are removed, and validation files are read
first so a question present in both is kept only in validation. The CLI prints
counts only.

    python3 -m calibration.tagger_dataset [DIRECTORY]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from calibration.tagger_corpus import DEFAULT_DIRECTORY, _fingerprint, _questions, load_source
from qtpp.model import Tossup
from qtpp.similarity import primary_answer, question_text

VALIDATION_YEAR = 2025
# Categories whose alternate labels span several subcategories are evaluated as one slice.
POOLED_CATEGORIES = ("Literature", "Social Science", "Pop Culture")
MIN_LABEL_EXAMPLES = 2


@dataclass(frozen=True, slots=True)
class Example:
    question_id: str
    text: str
    category: str
    subcategory: str
    label: str
    source: str
    year: int
    kind: str
    slice: str
    leadin: str = ""
    answers: tuple[str, ...] = ()


def slice_name(category: str, subcategory: str) -> str:
    return category if category in POOLED_CATEGORIES else f"{category} / {subcategory}"


def _as_year(value) -> int | None:
    match = re.search(r"(?<!\d)(20\d\d)(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def question_years(path: Path) -> tuple[dict[str, int], int | None]:
    """Return ``({question id: year}, file-level fallback year)`` from the raw file."""
    fallback = _as_year(path.stem)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            years = {
                row["question_id"]: year
                for row in csv.DictReader(handle)
                if row.get("question_id") and (year := _as_year(row.get("set_year")))
            }
        return years, fallback
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = data if isinstance(data, list) else [*data.get("tossups", []), *data.get("bonuses", [])]
    years = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        question_id = row.get("_id", row.get("id"))
        if question_id is None:
            continue
        set_info = row.get("set")
        year = (
            _as_year(set_info.get("year") if isinstance(set_info, dict) else None)
            or _as_year(row.get("year"))
            or _as_year(set_info)
        )
        if year:
            years[str(question_id)] = year
    top = data.get("set") if isinstance(data, dict) else None
    return years, _as_year((top or {}).get("year")) or fallback


def _leadin(question) -> str:
    if isinstance(question, Tossup):
        return ""
    return question.leadin_sanitized or question.leadin


def _answers(question) -> tuple[str, ...]:
    if isinstance(question, Tossup):
        return (primary_answer(question.answer_sanitized or question.answer),)
    return tuple(primary_answer(part.answer_sanitized or part.answer) for part in question.parts)


def load_examples(
    directory: Path = DEFAULT_DIRECTORY,
    validation_year: int = VALIDATION_YEAR,
    labeled_only: bool = True,
) -> tuple[list[Example], list[Example]]:
    """Return ``(development, validation)`` examples.

    By default only questions with an alternate subcategory are kept. With
    ``labeled_only=False`` every dated question is kept and ``label`` may be empty.
    """
    files = [
        p
        for p in directory.rglob("*")
        if p.is_file()
        and p.suffix.lower() in {".csv", ".json"}
        and "reviews" not in p.relative_to(directory).parts
    ]
    file_years = {p: question_years(p) for p in files}

    def newest(path: Path) -> int:
        years, fallback = file_years[path]
        return max([*years.values(), *([fallback] if fallback else [])], default=0)

    paths = sorted(files, key=lambda p: (-newest(p), p.name))
    seen: set[str] = set()
    train: list[Example] = []
    test: list[Example] = []
    for path in paths:
        years, fallback = file_years[path]
        for question in _questions(load_source(path)):
            year = years.get(question.metadata.id, fallback)
            if year is None:
                continue
            fingerprint = _fingerprint(question)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            topic = question.metadata.topic
            label = (topic.alternate_subcategory or "").strip()
            if not label and labeled_only:
                continue
            example = Example(
                question_id=question.metadata.id,
                text=question_text(question),
                category=topic.category,
                subcategory=topic.subcategory,
                label=label,
                source=path.name,
                year=year,
                kind="tossup" if isinstance(question, Tossup) else "bonus",
                slice=slice_name(topic.category, topic.subcategory),
                leadin=_leadin(question),
                answers=_answers(question),
            )
            (test if year >= validation_year else train).append(example)
    return _drop_tiny_slices(train, test) if labeled_only else (train, test)


def _drop_tiny_slices(
    train: list[Example], test: list[Example]
) -> tuple[list[Example], list[Example]]:
    labels: dict[str, set[str]] = defaultdict(set)
    for example in train:
        labels[example.slice].add(example.label)
    keep = {name for name, found in labels.items() if len(found) >= MIN_LABEL_EXAMPLES}
    return (
        [e for e in train if e.slice in keep],
        [e for e in test if e.slice in keep],
    )


def split_summary(train: list[Example], test: list[Example]) -> dict[str, dict[str, tuple[int, int]]]:
    train_counts = Counter((e.slice, e.label) for e in train)
    test_counts = Counter((e.slice, e.label) for e in test)
    summary: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    for slice_, label in sorted(set(train_counts) | set(test_counts)):
        summary[slice_][label] = (train_counts[(slice_, label)], test_counts[(slice_, label)])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args()
    train, test = load_examples(args.directory)
    print(f"development (through {VALIDATION_YEAR - 1}) {len(train)}, validation ({VALIDATION_YEAR}+) {len(test)}")
    for slice_, labels in split_summary(train, test).items():
        print(f"\n{slice_}")
        for label, (n_train, n_test) in sorted(labels.items(), key=lambda kv: -sum(kv[1])):
            flag = "  <-- fewer than 10 validation examples" if n_test < 10 else ""
            print(f"  {label:<24} dev {n_train:>4}   validation {n_test:>3}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
