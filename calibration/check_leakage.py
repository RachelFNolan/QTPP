"""Check for near-duplicate leakage between tagger training and test questions (experimental).

For each test question, finds the most similar question in the full (uncapped)
training set by TF-IDF cosine similarity, summarizes the distribution, and
rescores the baseline with near-duplicate test questions removed. Prints
numbers and label names only; no question text.

    python3 -m calibration.check_leakage [DIRECTORY] [--threshold 0.6]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from calibration.evaluate_tagger import DEFAULT_CAP, TAGGERS, cap_per_label
from calibration.tagger_corpus import DEFAULT_DIRECTORY
from calibration.tagger_dataset import load_examples

BUCKETS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4)


def nearest_similarities(train, test) -> np.ndarray:
    vectorizer = TfidfVectorizer(sublinear_tf=True, stop_words="english")
    train_matrix = vectorizer.fit_transform([e.text for e in train])
    test_matrix = vectorizer.transform([e.text for e in test])
    best = np.zeros(len(test))
    for start in range(0, len(test), 200):
        block = (test_matrix[start : start + 200] @ train_matrix.T).toarray()
        best[start : start + 200] = block.max(axis=1)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    args = parser.parse_args()

    train, test = load_examples(args.directory)
    similar = np.zeros(len(test))
    for slice_ in sorted({e.slice for e in test}):
        indexes = [i for i, e in enumerate(test) if e.slice == slice_]
        slice_train = [e for e in train if e.slice == slice_]
        similar[indexes] = nearest_similarities(slice_train, [test[i] for i in indexes])

    print(f"test questions {len(test)}; nearest-training-question similarity:")
    for bucket in BUCKETS:
        print(f"  >= {bucket:.1f}: {int((similar >= bucket).sum()):>4}")
    print(f"  median {np.median(similar):.2f}, 90th percentile {np.percentile(similar, 90):.2f}")

    capped = cap_per_label(train, args.cap)
    print(f"\nbaseline accuracy by slice (all test vs. test with nearest similarity < {args.threshold}):")
    for slice_ in sorted({e.slice for e in test}):
        slice_train = [e for e in capped if e.slice == slice_]
        tagger = TAGGERS["tfidf"]()
        tagger.fit(slice_train)
        indexes = [i for i, e in enumerate(test) if e.slice == slice_]
        predictions = tagger.predict([test[i] for i in indexes])
        correct = np.array([p.label == test[i].label for p, i in zip(predictions, indexes)])
        keep = np.array([similar[i] < args.threshold for i in indexes])
        removed = int((~keep).sum())
        clean_accuracy = float(correct[keep].mean()) if keep.any() else float("nan")
        print(
            f"  {slice_:<30} all {correct.mean():.3f} (n={len(indexes)})   "
            f"clean {clean_accuracy:.3f} (n={int(keep.sum())}, removed {removed})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
