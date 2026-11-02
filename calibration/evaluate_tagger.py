"""Evaluate local alternate-subcategory taggers (experimental).

Each tagger is trained per slice (for example "Fine Arts / Other Fine Arts").
By default it is scored with stratified cross-validation on development data
(sets through 2024). With --validate it is trained on all development data and
scored on the held-out 2025+ questions; use that sparingly, for formal
validation only. Output is metrics only; no question text.

    python3 -m calibration.evaluate_tagger [DIRECTORY] [--cap N] [--tagger tfidf] [--validate]

Requires scikit-learn (see requirements-dev.txt).
"""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold

from calibration.tagger_corpus import DEFAULT_DIRECTORY
from calibration.tagger_dataset import Example, load_examples

DEFAULT_CAP = 150
SEED = 0
THRESHOLDS = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9)
LOW_SUPPORT = 10


@dataclass(frozen=True, slots=True)
class Prediction:
    label: str
    confidence: float


class Tagger(Protocol):
    name: str

    def fit(self, train: Sequence[Example]) -> None: ...

    def predict(self, examples: Sequence[Example]) -> list[Prediction]: ...


class TfidfTagger:
    """Word and bigram TF-IDF with class-weighted logistic regression."""

    name = "tfidf"

    def __init__(self) -> None:
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), min_df=2, sublinear_tf=True, stop_words="english"
        )
        self._model = LogisticRegression(max_iter=2000, class_weight="balanced")

    def fit(self, train: Sequence[Example]) -> None:
        features = self._vectorizer.fit_transform([e.text for e in train])
        self._model.fit(features, [e.label for e in train])

    def _matrix(self, examples: Sequence[Example]):
        return self._vectorizer.transform([e.text for e in examples])

    def predict(self, examples: Sequence[Example]) -> list[Prediction]:
        probabilities = self._model.predict_proba(self._matrix(examples))
        classes = self._model.classes_
        return [
            Prediction(str(classes[row.argmax()]), float(row.max())) for row in probabilities
        ]


class EmbeddingTagger:
    """Sentence embeddings plus class-weighted logistic regression.

    Embeddings are computed once per distinct text and shared across instances,
    so cross-validation folds only refit the classifier.
    """

    name = "embeddings"
    model_name = "all-MiniLM-L6-v2"
    _encoder = None
    _cache: dict[str, "np.ndarray"] = {}

    def __init__(self) -> None:
        self._model = LogisticRegression(max_iter=2000, class_weight="balanced", C=10.0)

    @classmethod
    def _embed(cls, texts: Sequence[str]) -> "np.ndarray":
        missing = sorted({t for t in texts if t not in cls._cache})
        if missing:
            if cls._encoder is None:
                from sentence_transformers import SentenceTransformer

                cls._encoder = SentenceTransformer(cls.model_name)
            vectors = cls._encoder.encode(
                missing, batch_size=64, normalize_embeddings=True, show_progress_bar=False
            )
            cls._cache.update(zip(missing, vectors))
        return np.stack([cls._cache[t] for t in texts])

    def fit(self, train: Sequence[Example]) -> None:
        self._model.fit(self._embed([e.text for e in train]), [e.label for e in train])

    def _matrix(self, examples: Sequence[Example]):
        return self._embed([e.text for e in examples])

    def predict(self, examples: Sequence[Example]) -> list[Prediction]:
        probabilities = self._model.predict_proba(self._matrix(examples))
        classes = self._model.classes_
        return [Prediction(str(classes[row.argmax()]), float(row.max())) for row in probabilities]


class ConcatTagger:
    """One classifier over TF-IDF features concatenated with scaled embeddings."""

    name = "concat"
    embedding_weight = 1.0

    def __init__(self) -> None:
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), min_df=2, sublinear_tf=True, stop_words="english"
        )
        self._model = LogisticRegression(max_iter=3000, class_weight="balanced", C=10.0)

    def _features(self, texts: Sequence[str], fit: bool = False):
        words = (
            self._vectorizer.fit_transform(texts) if fit else self._vectorizer.transform(texts)
        )
        dense = EmbeddingTagger._embed(texts) * self.embedding_weight
        return hstack([words, csr_matrix(dense)]).tocsr()

    def fit(self, train: Sequence[Example]) -> None:
        self._model.fit(self._features([e.text for e in train], fit=True), [e.label for e in train])

    def predict(self, examples: Sequence[Example]) -> list[Prediction]:
        probabilities = self._model.predict_proba(self._features([e.text for e in examples]))
        classes = self._model.classes_
        return [Prediction(str(classes[row.argmax()]), float(row.max())) for row in probabilities]


class BlendTagger:
    """Average of the TF-IDF and embedding classifiers' probabilities."""

    name = "blend"

    def __init__(self) -> None:
        self._parts = (TfidfTagger(), EmbeddingTagger())

    def fit(self, train: Sequence[Example]) -> None:
        for part in self._parts:
            part.fit(train)

    def predict(self, examples: Sequence[Example]) -> list[Prediction]:
        probabilities = np.mean(
            [part._model.predict_proba(part._matrix(examples)) for part in self._parts], axis=0
        )
        classes = self._parts[0]._model.classes_
        return [Prediction(str(classes[row.argmax()]), float(row.max())) for row in probabilities]


TAGGERS = {
    "tfidf": TfidfTagger,
    "embeddings": EmbeddingTagger,
    "concat": ConcatTagger,
    "blend": BlendTagger,
}


def cap_per_label(train: Sequence[Example], cap: int) -> list[Example]:
    by_label: dict[tuple[str, str], list[Example]] = defaultdict(list)
    for example in train:
        by_label[(example.slice, example.label)].append(example)
    rng = random.Random(SEED)
    capped: list[Example] = []
    for key in sorted(by_label):
        group = sorted(by_label[key], key=lambda e: e.question_id)
        rng.shuffle(group)
        capped.extend(group[:cap])
    return capped


FOLDS = 5


def cross_validate(tagger_name: str, dev: list[Example]) -> None:
    all_truth: list[str] = []
    all_predictions: list[Prediction] = []
    for slice_ in sorted({e.slice for e in dev}):
        examples = sorted((e for e in dev if e.slice == slice_), key=lambda e: e.question_id)
        labels = [e.label for e in examples]
        truth: list[str] = []
        predictions: list[Prediction] = []
        folds = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
        for train_index, test_index in folds.split(examples, labels):
            tagger = TAGGERS[tagger_name]()
            tagger.fit([examples[i] for i in train_index])
            held_out = [examples[i] for i in test_index]
            predictions += tagger.predict(held_out)
            truth += [e.label for e in held_out]
        all_truth += truth
        all_predictions += predictions
        report_slice(slice_, truth, predictions, sorted(set(labels)))
    print("\nOVERALL")
    print_coverage(all_truth, all_predictions)


def evaluate(tagger_name: str, train: list[Example], test: list[Example]) -> None:
    slices = sorted({e.slice for e in test})
    all_truth: list[str] = []
    all_predictions: list[Prediction] = []
    for slice_ in slices:
        slice_train = [e for e in train if e.slice == slice_]
        slice_test = [e for e in test if e.slice == slice_]
        tagger = TAGGERS[tagger_name]()
        tagger.fit(slice_train)
        predictions = tagger.predict(slice_test)
        truth = [e.label for e in slice_test]
        all_truth += truth
        all_predictions += predictions
        report_slice(slice_, truth, predictions, sorted({e.label for e in slice_train}))
    print("\nOVERALL")
    print_coverage(all_truth, all_predictions)


def report_slice(
    slice_: str, truth: list[str], predictions: list[Prediction], labels: list[str]
) -> None:
    predicted = [p.label for p in predictions]
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=labels, zero_division=0
    )
    present = [i for i, n in enumerate(support) if n]
    macro_f1 = sum(f1[i] for i in present) / len(present)
    print(f"\n=== {slice_}  (test n={len(truth)})")
    print(f"accuracy {accuracy_score(truth, predicted):.3f}   macro-F1 {macro_f1:.3f}")
    print(f"  {'label':<22}{'prec':>6}{'recall':>8}{'F1':>6}{'n':>5}")
    for i, label in enumerate(labels):
        note = "  (low support)" if support[i] < LOW_SUPPORT else ""
        print(f"  {label:<22}{precision[i]:>6.2f}{recall[i]:>8.2f}{f1[i]:>6.2f}{support[i]:>5}{note}")
    print("  confusion (rows = true, columns = predicted, in the label order above):")
    for label, row in zip(labels, confusion_matrix(truth, predicted, labels=labels)):
        print(f"    {label:<22}{' '.join(f'{n:>4}' for n in row)}")
    print_coverage(truth, predictions)


def print_coverage(truth: list[str], predictions: list[Prediction]) -> None:
    print("  answer only when confidence >= t:  coverage / accuracy")
    parts = []
    for threshold in THRESHOLDS:
        kept = [(t, p) for t, p in zip(truth, predictions) if p.confidence >= threshold]
        if not kept:
            parts.append(f"{threshold:.1f}: -")
            continue
        correct = sum(t == p.label for t, p in kept)
        parts.append(f"{threshold:.1f}: {len(kept) / len(truth):.0%}/{correct / len(kept):.0%}")
    print("   ", "  ".join(parts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP, help="max training examples per label")
    parser.add_argument("--tagger", choices=sorted(TAGGERS), default="tfidf")
    parser.add_argument(
        "--model", default=None, help="sentence-transformers model for embedding taggers"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="score on the held-out 2025+ questions instead of cross-validating",
    )
    args = parser.parse_args()
    if args.model:
        EmbeddingTagger.model_name = args.model
    dev, validation = load_examples(args.directory)
    dev = cap_per_label(dev, args.cap)
    if args.validate:
        print(f"tagger {args.tagger}; VALIDATION: train {len(dev)} (cap {args.cap}/label), test {len(validation)}")
        evaluate(args.tagger, dev, validation)
    else:
        print(
            f"tagger {args.tagger}; {FOLDS}-fold cross-validation on {len(dev)} "
            f"development examples (cap {args.cap}/label)"
        )
        cross_validate(args.tagger, dev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
