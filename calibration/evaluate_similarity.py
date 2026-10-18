"""Compare similarity scorers against the labeled pair fixture.

Usage:
    python3 -m calibration.evaluate_similarity [--pairs JSON] [--pool CSV] [--embeddings] [--include-borderline]

Requires scikit-learn (see requirements-dev.txt). --embeddings additionally
tries a local fastembed model if installed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import average_precision_score, roc_auc_score

from packetizer import SimilarityWeights, TfidfSimilarity, load_question_pool_csv, question_text
from packetizer.similarity import CombinedSimilarity, question_topics, tokenize

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "Test Questions" / "2025 ACF Winter" / "Question Pool.csv"
DEFAULT_PAIRS = ROOT / "calibration" / "similarity_pairs.json"


class MatrixScorer:
    """Pair scorer backed by row-normalized document vectors."""

    def __init__(self, ids: list[str], vectors: np.ndarray) -> None:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._index = {key: row for row, key in enumerate(ids)}
        self._vectors = vectors / norms

    def score(self, first_id: str, second_id: str) -> float:
        return float(self._vectors[self._index[first_id]] @ self._vectors[self._index[second_id]])


def best_f1(labels: list[int], scores: list[float]) -> tuple[float, float]:
    best = (0.0, 0.0)
    for threshold in sorted(set(scores)):
        predicted = [score >= threshold for score in scores]
        tp = sum(1 for p, y in zip(predicted, labels) if p and y)
        fp = sum(1 for p, y in zip(predicted, labels) if p and not y)
        fn = sum(1 for p, y in zip(predicted, labels) if not p and y)
        if tp:
            f1 = 2 * tp / (2 * tp + fp + fn)
            if f1 > best[0]:
                best = (f1, threshold)
    return best


def build_scorers(pool, with_embeddings: bool, custom_weights=None) -> dict:
    questions = [*pool.tossups, *pool.bonuses]
    ids = [question.metadata.id for question in questions]
    texts = [question_text(question) for question in questions]
    topics = question_topics(questions)

    stdlib = TfidfSimilarity(dict(zip(ids, texts)))
    sk_unigram = TfidfVectorizer(tokenizer=tokenize, lowercase=False, token_pattern=None, sublinear_tf=True)
    sk_bigram = TfidfVectorizer(
        tokenizer=tokenize, lowercase=False, token_pattern=None, sublinear_tf=True, ngram_range=(1, 2)
    )
    unigram_matrix = sk_unigram.fit_transform(texts)
    unigram = MatrixScorer(ids, unigram_matrix.toarray())
    bigram = MatrixScorer(ids, sk_bigram.fit_transform(texts).toarray())
    lsa = MatrixScorer(
        ids, TruncatedSVD(n_components=100, random_state=0).fit_transform(unigram_matrix)
    )

    scorers = {
        "stdlib tf-idf": stdlib,
        "sklearn tf-idf unigram": unigram,
        "sklearn tf-idf 1-2gram": bigram,
        "sklearn LSA(100)": lsa,
        "stdlib + topic (0.7/0.2/0.1)": CombinedSimilarity(stdlib, topics, SimilarityWeights(0.7, 0.2, 0.1)),
        "stdlib + topic (0.9/0.07/0.03)": CombinedSimilarity(stdlib, topics, SimilarityWeights(0.9, 0.07, 0.03)),
        "topic only": CombinedSimilarity(stdlib, topics, SimilarityWeights(0.0, 0.7, 0.3)),
    }
    if custom_weights:
        scorers["custom: stdlib + topic " + "/".join(f"{w:g}" for w in custom_weights)] = (
            CombinedSimilarity(stdlib, topics, SimilarityWeights(*custom_weights))
        )
    if with_embeddings:
        try:
            from fastembed import TextEmbedding
        except ImportError:
            print("fastembed not installed; skipping embeddings")
        else:
            model = TextEmbedding("BAAI/bge-small-en-v1.5")
            embedded = MatrixScorer(ids, np.array(list(model.embed(texts))))
            scorers["embedding bge-small"] = embedded
            scorers["embedding + topic"] = CombinedSimilarity(
                embedded, topics, SimilarityWeights(0.7, 0.2, 0.1)
            )
    return scorers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--embeddings", action="store_true")
    parser.add_argument("--include-borderline", action="store_true")
    parser.add_argument(
        "--weights", type=float, nargs=3, metavar=("TEXT", "SUBCATEGORY", "CATEGORY"),
        help="also score a custom SimilarityWeights blend",
    )
    args = parser.parse_args()

    data = json.loads(args.pairs.read_text(encoding="utf-8"))
    pairs = [
        pair for pair in data["pairs"] if args.include_borderline or not pair["borderline"]
    ]
    labels = [int(pair["label"]) for pair in pairs]
    print(f"{len(pairs)} pairs, {sum(labels)} related, reviewed={data['reviewed']}")
    scorers = build_scorers(load_question_pool_csv(args.pool), args.embeddings, args.weights)
    print(f"{'scorer':34} {'AUC':>6} {'AP':>6} {'bestF1':>7} {'thresh':>7}")
    for name, scorer in scorers.items():
        scores = [scorer.score(pair["first_id"], pair["second_id"]) for pair in pairs]
        f1, threshold = best_f1(labels, scores)
        print(
            f"{name:34} {roc_auc_score(labels, scores):6.3f} "
            f"{average_precision_score(labels, scores):6.3f} {f1:7.3f} {threshold:7.3f}"
        )


if __name__ == "__main__":
    main()
