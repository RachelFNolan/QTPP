"""Suggest topic-family tags for questions that have no alternate subcategory.

Suggestions are advisory: they are written to a file for human review and only
reach a build after ``approve_suggestions`` converts them into a curated
families file for ``load_curated_families``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .model import Bonus, QuestionSet, Tossup
from .similarity import TfidfSimilarity, question_text
from .taxonomy import Taxonomy, label_texts, normalize

# Maps (question texts, label texts) to a similarity matrix [question][label].
SimilarityFn = Callable[[Sequence[str], Sequence[str]], list[list[float]]]

DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_TRANSFORMERS_MODEL = "all-MiniLM-L6-v2"
SNIPPET_LENGTH = 200


@dataclass(frozen=True, slots=True)
class Suggestion:
    question_id: str
    label: str | None
    best_guess: str
    score: float
    runner_up: str | None
    runner_up_score: float
    text: str
    status: str = "unsure"
    category: str = ""


def load_labels(path: str | Path) -> dict[str, list[str]]:
    """Read {"labels": {name: description-or-[examples]}}; names map to text to match against."""
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error}") from error
    raw = data.get("labels") if isinstance(data, dict) else None
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f'{source}: expected {{"labels": {{name: description, ...}}}}')
    labels: dict[str, list[str]] = {}
    for name, value in raw.items():
        texts = [value] if isinstance(value, str) else value
        if (
            not isinstance(texts, list)
            or not texts
            or any(not isinstance(text, str) or not text.strip() for text in texts)
        ):
            raise ValueError(f"{source}: label {name!r} needs a description or list of examples")
        labels[name] = [f"{name}. {text}" for text in texts]
    return labels


def _cosine_matrix(vectors: Sequence[Sequence[float]], count: int) -> list[list[float]]:
    def unit(vector: Sequence[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else [0.0] * len(vector)

    normalized = [unit(vector) for vector in vectors]
    questions, targets = normalized[: len(normalized) - count], normalized[-count:]
    return [
        [sum(a * b for a, b in zip(question, target)) for target in targets]
        for question in questions
    ]


def _embedding_similarity(embed: Callable[[list[str]], Iterable[Sequence[float]]]) -> SimilarityFn:
    def similarity(questions: Sequence[str], labels: Sequence[str]) -> list[list[float]]:
        vectors = [list(map(float, vector)) for vector in embed([*questions, *labels])]
        return _cosine_matrix(vectors, len(labels))

    return similarity


def tfidf_similarity(questions: Sequence[str], labels: Sequence[str]) -> list[list[float]]:
    """Dependency-free backend; weaker than embeddings."""
    texts = {f"q{index}": text for index, text in enumerate(questions)}
    texts.update({f"l{index}": text for index, text in enumerate(labels)})
    model = TfidfSimilarity(texts)
    return [
        [model.score(f"q{q}", f"l{l}") for l in range(len(labels))]
        for q in range(len(questions))
    ]


def fastembed_similarity(model_name: str = DEFAULT_FASTEMBED_MODEL) -> SimilarityFn:
    try:
        from fastembed import TextEmbedding
    except ImportError as error:
        raise RuntimeError("fastembed is not installed: pip install fastembed") from error
    model = TextEmbedding(model_name)
    return _embedding_similarity(lambda texts: model.embed(texts))


def sentence_transformers_similarity(model_name: str = DEFAULT_TRANSFORMERS_MODEL) -> SimilarityFn:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "sentence-transformers is not installed: pip install sentence-transformers"
        ) from error
    model = SentenceTransformer(model_name)
    return _embedding_similarity(lambda texts: model.encode(texts, show_progress_bar=False))


def get_backend(name: str, model: str | None = None) -> SimilarityFn:
    if name == "tfidf":
        return tfidf_similarity
    if name == "fastembed":
        return fastembed_similarity(model or DEFAULT_FASTEMBED_MODEL)
    if name == "sentence-transformers":
        return sentence_transformers_similarity(model or DEFAULT_TRANSFORMERS_MODEL)
    raise ValueError(f"unknown backend {name!r}; use tfidf, fastembed or sentence-transformers")


def questions_missing_family(
    pool: QuestionSet,
    curated: Mapping[str, object] | None = None,
    subcategories: Iterable[str] | None = None,
) -> list[Tossup | Bonus]:
    """Questions with a blank alternate subcategory and no curated entry.

    subcategories optionally restricts the result to those primary subcategories.
    """
    curated = curated or {}
    allowed = {name.casefold() for name in subcategories} if subcategories else None
    return [
        question
        for question in (*pool.tossups, *pool.bonuses)
        if not (question.metadata.topic.alternate_subcategory or "").strip()
        and question.metadata.id not in curated
        and (allowed is None or question.metadata.topic.subcategory.casefold() in allowed)
    ]


def suggest_families(
    pool: QuestionSet,
    labels: Mapping[str, Sequence[str]],
    similarity: SimilarityFn = tfidf_similarity,
    *,
    curated: Mapping[str, object] | None = None,
    subcategories: Iterable[str] | None = None,
    min_score: float = 0.2,
    min_margin: float = 0.02,
) -> list[Suggestion]:
    """Classify each untagged question against the labels.

    A label is proposed only when its score reaches min_score and beats the
    runner-up by min_margin; otherwise ``label`` is None and ``best_guess``
    shows the closest label for the reviewer.
    """
    names = list(labels)
    if not names:
        raise ValueError("at least one label is required")
    targets = [text for name in names for text in labels[name]]
    owners = [index for index, name in enumerate(names) for _ in labels[name]]
    questions = questions_missing_family(pool, curated, subcategories)
    if not questions:
        return []
    texts = [question_text(question) for question in questions]
    matrix = similarity(texts, targets)
    suggestions = []
    for question, text, row in zip(questions, texts, matrix):
        best = [-math.inf] * len(names)
        for owner, value in zip(owners, row):
            best[owner] = max(best[owner], value)
        ranked = sorted(range(len(names)), key=lambda index: best[index], reverse=True)
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        second_score = best[second] if second is not None else 0.0
        confident = best[top] >= min_score and best[top] - second_score >= min_margin
        suggestions.append(
            Suggestion(
                question_id=question.metadata.id,
                label=names[top] if confident else None,
                best_guess=names[top],
                score=round(best[top], 4),
                runner_up=names[second] if second is not None else None,
                runner_up_score=round(second_score, 4),
                text=" ".join(text.split())[:SNIPPET_LENGTH],
                status="review" if confident else "unsure",
                category=question.metadata.topic.category,
            )
        )
    return suggestions


def _top_k_mean(values: Sequence[float], k: int = 3) -> float:
    top = sorted(values, reverse=True)[:k]
    return sum(top) / len(top)


def suggest_with_taxonomy(
    pool: QuestionSet,
    taxonomy: Taxonomy,
    similarity: SimilarityFn = tfidf_similarity,
    *,
    curated: Mapping[str, object] | None = None,
    use_examples: bool = True,
    min_examples: int = 5,
    min_score: float = 0.0,
    min_margin: float = 0.02,
    auto_margin: float | None = None,
) -> list[Suggestion]:
    """Classify every untagged question against its category's taxonomy labels.

    Zero-shot similarity to the label descriptions is the base. Labels that
    already have at least min_examples tagged questions in the pool (after alias
    mapping) also get an example-based score; when both signals apply to the
    zero-shot winner and disagree, the question is left unsure for review.
    Status is "auto" when the winner leads the runner-up by at least auto_margin
    (margin predicted accuracy better than raw score in testing),
    "review" for other proposals, and "unsure" when no label is proposed.
    """
    curated = curated or {}
    suggestions: list[Suggestion] = []
    for category in taxonomy.categories.values():
        if not category.labels:
            continue
        names = [label.name for label in category.labels]
        candidates = [
            question
            for question in questions_missing_family(pool, curated)
            if normalize(question.metadata.topic.category) == normalize(category.name)
            and category.allows(question.metadata.topic.subcategory)
        ]
        if not candidates:
            continue
        targets = [text for label in category.labels for text in label_texts(label)]
        owners = [index for index, label in enumerate(category.labels) for _ in label_texts(label)]
        texts = [question_text(question) for question in candidates]
        zero_shot = similarity(texts, targets)

        examples: dict[int, list[str]] = {}
        for question in (*pool.tossups, *pool.bonuses):
            topic = question.metadata.topic
            alternate = (topic.alternate_subcategory or "").strip()
            if not alternate or normalize(topic.category) != normalize(category.name):
                continue
            label = category.canonical(alternate)
            if label is not None:
                examples.setdefault(names.index(label), []).append(question_text(question))
        examples = {k: v for k, v in examples.items() if len(v) >= min_examples} if use_examples else {}
        example_scores: list[list[float]] = []
        example_owners: list[int] = []
        if examples:
            example_texts = [text for index in examples for text in examples[index]]
            example_owners = [index for index in examples for _ in examples[index]]
            example_scores = similarity(texts, example_texts)

        for position, (question, text, row) in enumerate(zip(candidates, texts, zero_shot)):
            subcategory = question.metadata.topic.subcategory
            best = [-math.inf] * len(names)
            for owner, value in zip(owners, row):
                best[owner] = max(best[owner], value)
            for index, label in enumerate(category.labels):
                if not label.allows(subcategory):
                    best[index] = -math.inf
            ranked = [i for i in sorted(range(len(names)), key=lambda i: best[i], reverse=True) if best[i] > -math.inf]
            if not ranked:
                continue
            top = ranked[0]
            second = ranked[1] if len(ranked) > 1 else None
            second_score = best[second] if second is not None else 0.0
            confident = best[top] >= min_score and best[top] - second_score >= min_margin
            if confident and top in examples:
                by_label: dict[int, list[float]] = {}
                for owner, value in zip(example_owners, example_scores[position]):
                    by_label.setdefault(owner, []).append(value)
                allowed = [i for i in by_label if category.labels[i].allows(subcategory)]
                if allowed:
                    example_top = max(allowed, key=lambda i: _top_k_mean(by_label[i]))
                    confident = example_top == top
            if not confident:
                status = "unsure"
            elif auto_margin is not None and best[top] - second_score >= auto_margin:
                status = "auto"
            else:
                status = "review"
            suggestions.append(
                Suggestion(
                    question_id=question.metadata.id,
                    label=names[top] if confident else None,
                    best_guess=names[top],
                    score=round(best[top], 4),
                    runner_up=names[second] if second is not None else None,
                    runner_up_score=round(second_score, 4),
                    text=" ".join(text.split())[:SNIPPET_LENGTH],
                    status=status,
                    category=category.name,
                )
            )
    return suggestions


def save_suggestions(suggestions: Sequence[Suggestion], path: str | Path) -> None:
    data = {
        "note": (
            'Review each entry. "label" is the proposed tag (null = unsure; see "best_guess"). '
            '"status" is auto (high confidence), review or unsure. Edit or clear labels, '
            "then run approve to produce a families file."
        ),
        "suggestions": [
            {
                "question_id": item.question_id,
                "label": item.label,
                "best_guess": item.best_guess,
                "score": item.score,
                "runner_up": item.runner_up,
                "runner_up_score": item.runner_up_score,
                "status": item.status,
                "category": item.category,
                "text": item.text,
            }
            for item in suggestions
        ],
    }
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def approve_suggestions(path: str | Path, auto_only: bool = False) -> dict[str, list[str]]:
    """Turn a reviewed suggestions file into {question_id: [label]} for curated families.

    Entries whose label is null or empty are left out. With auto_only, only
    entries with status "auto" are kept, so unreviewed high-confidence tags can
    be accepted without reading the rest.
    """
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error}") from error
    entries = data.get("suggestions") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f'{source}: expected {{"suggestions": [...]}}')
    families: dict[str, list[str]] = {}
    for entry in entries:
        label = entry.get("label") if isinstance(entry, dict) else None
        question_id = entry.get("question_id") if isinstance(entry, dict) else None
        if not isinstance(question_id, str):
            raise ValueError(f"{source}: every suggestion needs a question_id")
        if auto_only and entry.get("status") != "auto":
            continue
        if isinstance(label, str) and label.strip():
            families[question_id] = [label.strip()]
    return families


def suggested_tags(
    pool: QuestionSet,
    taxonomy: Taxonomy | None = None,
    similarity: SimilarityFn = tfidf_similarity,
    **options: object,
) -> dict[str, list[str]]:
    """Proposed {question_id: [label]} for untagged questions, ready for
    build_similarity(suggested_families=...). Unsure questions are omitted."""
    from .taxonomy import load_taxonomy

    suggestions = suggest_with_taxonomy(pool, taxonomy or load_taxonomy(), similarity, **options)
    return {item.question_id: [item.label] for item in suggestions if item.label}
