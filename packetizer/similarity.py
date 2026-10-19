from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol

from .model import Bonus, QuestionSet, Tossup

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_STOPWORDS = frozenset(
    """a about after all also an and any are as at be because been before being between both
    but by can could did do does each for from had has have he her his how if in into is it its
    like more most no not of on one only or other out over she so some such than that the their
    them then there these they this those through to two under up was were what when where which
    while who whom why will with would you your points point ten accept prompt or""".split()
)


@dataclass(frozen=True, slots=True)
class SimilarityWeights:
    """Mixing weights for the combined score; they need not sum to one."""

    text: float = 0.9
    subcategory: float = 0.07
    category: float = 0.03


class PairScorer(Protocol):
    def score(self, first_id: str, second_id: str) -> float: ...


def question_text(question: Tossup | Bonus) -> str:
    """Searchable text for a question: sanitized prose plus primary answers."""
    if isinstance(question, Tossup):
        parts = [
            question.question_sanitized or question.question,
            primary_answer(question.answer_sanitized or question.answer),
        ]
    else:
        parts = [question.leadin_sanitized or question.leadin]
        for part in question.parts:
            parts.append(part.question_sanitized or part.question)
            parts.append(primary_answer(part.answer_sanitized or part.answer))
    return " ".join(parts)


def primary_answer(answer: str) -> str:
    """The answer line without bracketed alternates or parenthetical notes."""
    return re.split(r"\s*[\[(]", answer, maxsplit=1)[0]


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


class TfidfSimilarity:
    """Stdlib TF-IDF cosine similarity over a fixed collection of texts."""

    def __init__(self, texts: Mapping[str, str]) -> None:
        documents = {key: Counter(tokenize(text)) for key, text in texts.items()}
        document_frequency: Counter[str] = Counter()
        for counts in documents.values():
            document_frequency.update(counts.keys())
        total = len(documents)
        self._idf = {
            term: math.log((1 + total) / (1 + frequency)) + 1
            for term, frequency in document_frequency.items()
        }
        self._vectors: dict[str, dict[str, float]] = {}
        for key, counts in documents.items():
            vector = {
                term: (1 + math.log(count)) * self._idf[term]
                for term, count in counts.items()
            }
            norm = math.sqrt(sum(value * value for value in vector.values()))
            self._vectors[key] = (
                {term: value / norm for term, value in vector.items()} if norm else {}
            )

    def score(self, first_id: str, second_id: str) -> float:
        first, second = self._vectors[first_id], self._vectors[second_id]
        if len(first) > len(second):
            first, second = second, first
        return sum(value * second.get(term, 0.0) for term, value in first.items())


class CombinedSimilarity:
    """Weighted blend of text similarity and topic-label agreement, in [0, 1]."""

    def __init__(
        self,
        text_scorer: PairScorer,
        topics: Mapping[str, tuple[str, str, str | None]],
        weights: SimilarityWeights = SimilarityWeights(),
    ) -> None:
        self._text = text_scorer
        self._topics = topics
        self._weights = weights
        self._total = weights.text + weights.subcategory + weights.category
        if self._total <= 0:
            raise ValueError("similarity weights must have a positive sum")

    def score(self, first_id: str, second_id: str) -> float:
        first = self._topics[first_id]
        second = self._topics[second_id]
        same_category = first[0] == second[0]
        subcategories_agree = same_category and (
            first[1] == second[1]
            or (first[2] is not None and first[2] in (second[1], second[2]))
            or (second[2] is not None and second[2] == first[1])
        )
        value = (
            self._weights.text * self._text.score(first_id, second_id)
            + self._weights.subcategory * subcategories_agree
            + self._weights.category * same_category
        )
        return value / self._total


def question_topics(
    questions: Iterable[Tossup | Bonus],
) -> dict[str, tuple[str, str, str | None]]:
    return {
        question.metadata.id: (
            question.metadata.topic.category,
            question.metadata.topic.subcategory,
            question.metadata.topic.alternate_subcategory,
        )
        for question in questions
    }


GENERIC_FAMILIES = frozenset({"misc literature", "misc arts", "other social science"})


def _normalize_family(value: str) -> str:
    return " ".join(value.split()).casefold()


def question_families(
    questions: Iterable[Tossup | Bonus],
    curated: Mapping[str, Iterable[str]] | None = None,
    excluded: Iterable[str] = GENERIC_FAMILIES,
) -> dict[str, frozenset[str]]:
    """Topic families per question ID.

    A question's family is its alternate subcategory unless it is a catch-all
    in ``excluded``. A curated entry replaces the automatic family for that ID;
    an empty list removes it.
    """
    skip = {_normalize_family(name) for name in excluded}
    curated = curated or {}
    families: dict[str, frozenset[str]] = {}
    for question in questions:
        question_id = question.metadata.id
        if question_id in curated:
            found = {_normalize_family(name) for name in curated[question_id]}
        else:
            alternate = question.metadata.topic.alternate_subcategory
            found = {_normalize_family(alternate)} if alternate else set()
        families[question_id] = frozenset(found - skip)
    return families


class FamilyPenaltyScorer:
    """Raises the score of pairs that share a topic family, capped at 1.

    Wrapping a pair scorer makes every solver's same-packet and nearby penalties
    discourage repeated families without changing their code.
    """

    def __init__(
        self,
        scorer: PairScorer,
        families: Mapping[str, frozenset[str]],
        penalty: float,
    ) -> None:
        if penalty < 0:
            raise ValueError("family penalty must be non-negative")
        self._scorer = scorer
        self._families = families
        self._penalty = penalty

    def score(self, first_id: str, second_id: str) -> float:
        value = self._scorer.score(first_id, second_id)
        if self._penalty and self._families[first_id] & self._families[second_id]:
            return min(1.0, value + self._penalty)
        return value


def load_curated_families(path: str | Path) -> dict[str, list[str]]:
    """Read {"families": {question_id: [family, ...]}} for per-question overrides."""
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error}") from error
    families = data.get("families") if isinstance(data, dict) else None
    if not isinstance(families, dict) or any(
        not isinstance(names, list) or any(not isinstance(name, str) for name in names)
        for names in families.values()
    ):
        raise ValueError(f"{source}: expected {{\"families\": {{question_id: [family, ...]}}}}")
    return families


def build_similarity(
    pool: QuestionSet,
    weights: SimilarityWeights = SimilarityWeights(),
    text_scorer: PairScorer | None = None,
    *,
    family_penalty: float = 0.0,
    curated_families: Mapping[str, Iterable[str]] | None = None,
    excluded_families: Iterable[str] = GENERIC_FAMILIES,
) -> PairScorer:
    """Combined similarity over every tossup and bonus in a pool, keyed by question ID.

    text_scorer replaces the built-in TF-IDF text similarity, for example with
    an embedding model. It must implement score(first_id, second_id) -> [0, 1]
    for any two question IDs in the pool; use question_text() to get the text.

    A positive family_penalty adds to the score of pairs sharing a topic family
    (alternate subcategory such as Math or Poetry, or a curated override), so
    solvers keep them apart. The default of 0 leaves scores unchanged.
    """
    questions: list[Tossup | Bonus] = [*pool.tossups, *pool.bonuses]
    if text_scorer is None:
        texts = {question.metadata.id: question_text(question) for question in questions}
        text_scorer = TfidfSimilarity(texts)
    combined = CombinedSimilarity(text_scorer, question_topics(questions), weights)
    if not family_penalty:
        return combined
    families = question_families(questions, curated_families, excluded_families)
    return FamilyPenaltyScorer(combined, families, family_penalty)
