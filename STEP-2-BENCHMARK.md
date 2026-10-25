# Step 2 benchmark results

Run date: 2026-10-19

## Environment and commands

- Python 3.12.4
- OR-Tools 9.15.6755
- scikit-learn 1.6.1
- fastembed 0.9.0; embedding backend `BAAI/bge-small-en-v1.5`
- Solver pool/template: `Test Questions/2025 ACF Winter Question Pool.csv` and `templates/acf-winter-final.json`
- Solver packet counts: 8, 12, and 16; seeds 0-2; CP-SAT time limit 30 seconds per run.
- Similarity fixtures: reviewed Winter pairs and reviewed Fall pairs; borderline pairs excluded, as in the evaluator's default.

Commands:

```sh
python3 -m unittest tests.test_feasibility tests.test_similarity tests.test_scoring tests.test_solvers
python3 -m calibration.evaluate_similarity --embeddings
python3 -m calibration.evaluate_similarity \
  --pool "Test Questions/2025 ACF Fall/Question Pool.csv" \
  --pairs calibration/similarity_pairs_fall.json --embeddings
python3 -m utilities.benchmark_solvers --packets 8 12 16 --seeds 3 --time-limit 30
python3 -m utilities.benchmark_solvers --all-scorers --embeddings \
  --packets 8 12 16 --seeds 3 --time-limit 30
```

The focused unit tests passed: 20 tests in 2.072 seconds on the final rerun.

## Similarity scorer evaluation

Metrics are AUC, average precision (AP), and best F1 with its threshold. Best F1 thresholds are selected on the same small labeled fixture, so treat F1 as descriptive rather than an unbiased estimate of production performance. Winter has 48 non-borderline pairs (11 labeled related); Fall has 52 (14 labeled related).

### Winter fixture

| Scorer | AUC | AP | Best F1 | Threshold |
|---|---:|---:|---:|---:|
| stdlib TF-IDF | 0.907 | 0.762 | 0.759 | 0.072 |
| scikit-learn TF-IDF unigram | 0.907 | 0.762 | 0.759 | 0.072 |
| scikit-learn TF-IDF 1-2gram | 0.875 | 0.635 | 0.759 | 0.040 |
| scikit-learn LSA (100) | 0.899 | 0.691 | 0.759 | 0.283 |
| stdlib + topic (0.7/0.2/0.1) | 0.904 | 0.749 | **0.783** | 0.232 |
| stdlib + topic (0.9/0.07/0.03) | **0.921** | 0.760 | 0.759 | 0.067 |
| topic only | 0.828 | 0.608 | 0.727 | 1.000 |
| bge-small embedding | 0.894 | 0.725 | 0.727 | 0.688 |
| bge-small + topic (0.7/0.2/0.1) | 0.909 | **0.769** | 0.750 | 0.582 |

### Fall held-out fixture

| Scorer | AUC | AP | Best F1 | Threshold |
|---|---:|---:|---:|---:|
| stdlib TF-IDF | 0.878 | 0.683 | 0.765 | 0.050 |
| scikit-learn TF-IDF unigram | 0.878 | 0.683 | 0.765 | 0.050 |
| scikit-learn TF-IDF 1-2gram | 0.914 | 0.809 | 0.765 | 0.020 |
| scikit-learn LSA (100) | 0.891 | 0.715 | 0.743 | 0.230 |
| stdlib + topic (0.7/0.2/0.1) | 0.889 | 0.720 | 0.812 | 0.335 |
| stdlib + topic (0.9/0.07/0.03) | 0.883 | 0.712 | 0.765 | 0.145 |
| topic only | 0.887 | 0.690 | 0.812 | 1.000 |
| bge-small embedding | 0.923 | 0.833 | 0.757 | 0.664 |
| bge-small + topic (0.7/0.2/0.1) | **0.934** | **0.864** | **0.839** | 0.771 |

The existing default (`stdlib + topic`, 0.9/0.07/0.03) has the strongest Winter AUC among tested scorers, while the embedding/topic blend leads on Fall. This small two-fixture comparison does not establish a clear enough cross-domain benefit to replace the dependency-light default with embeddings. Keep embeddings optional and gather more labeled examples before retuning defaults.

## Solver benchmark

The full solver matrix uses all nine scorers from `calibration.evaluate_similarity`, including both optional embedding variants. Each successful row aggregates three seeds. `valid` counts layouts with no hard-rule errors; mean soft scores are full post-solve weighted scores (lower is better), and seconds are mean wall time per solve. Scores are only comparable between solvers using the same scorer because the scorers have different ranges and scales.

### Current default scorer

This first default-only run records the best score per packet count; the all-scorer matrix below was a separate run, so wall times may differ slightly.

| Packets | Solver | Valid | Mean soft score | Best soft score | Mean seconds |
|---:|---|---:|---:|---:|---:|
| 8 | Python baseline | 3/3 | 77.1 | 76.9 | 1.4 |
| 8 | CP-SAT | 3/3 | 103.2 | 103.0 | 1.2 |
| 12 | Python baseline | 3/3 | 123.4 | 122.5 | 2.1 |
| 12 | CP-SAT | 3/3 | 156.0 | 155.9 | 1.6 |
| 16 | Python baseline | 3/3 | 177.9 | 177.5 | 2.4 |
| 16 | CP-SAT | 3/3 | 210.9 | 210.8 | 2.0 |

### All-scorer matrix

| Scorer | Packets | Python baseline mean (valid) | Baseline sec | CP-SAT mean (valid) | CP-SAT sec |
|---|---:|---:|---:|---:|---:|
| stdlib TF-IDF | 8 | 44.1 (3/3) | 1.4 | 70.6 (3/3) | 1.2 |
| scikit-learn TF-IDF unigram | 8 | 44.1 (3/3) | 1.6 | 70.6 (3/3) | 1.3 |
| scikit-learn TF-IDF 1-2gram | 8 | 20.2 (3/3) | 3.3 | 32.4 (3/3) | 2.4 |
| scikit-learn LSA (100) | 8 | 126.0 (3/3) | 0.7 | 288.8 (3/3) | 1.0 |
| stdlib + topic (0.7/0.2/0.1) | 8 | 145.5 (3/3) | 1.4 | 167.7 (3/3) | 1.2 |
| stdlib + topic (0.9/0.07/0.03) | 8 | 77.1 (3/3) | 1.4 | 103.2 (3/3) | 1.2 |
| topic only | 8 | 356.6 (3/3) | 1.2 | 375.5 (3/3) | 1.3 |
| bge-small embedding | 8 | 4012.0 (3/3) | 0.7 | 4253.6 (3/3) | 1.0 |
| bge-small + topic (0.7/0.2/0.1) | 8 | 2928.5 (3/3) | 0.7 | 3102.5 (3/3) | 0.8 |
| stdlib TF-IDF | 12 | 74.7 (3/3) | 1.8 | 109.1 (3/3) | 1.9 |
| scikit-learn TF-IDF unigram | 12 | 74.7 (3/3) | 2.2 | 109.1 (3/3) | 2.0 |
| scikit-learn TF-IDF 1-2gram | 12 | 33.4 (3/3) | 4.2 | 47.9 (3/3) | 2.8 |
| scikit-learn LSA (100) | 12 | 222.6 (3/3) | 1.0 | 425.2 (3/3) | 25.5 |
| stdlib + topic (0.7/0.2/0.1) | 12 | 224.7 (3/3) | 1.9 | 253.4 (3/3) | 1.5 |
| stdlib + topic (0.9/0.07/0.03) | 12 | 123.4 (3/3) | 1.8 | 156.0 (3/3) | 1.5 |
| topic only | 12 | 535.4 (3/3) | 1.7 | timeout (seed 0) | — |
| bge-small embedding | 12 | 6172.3 (3/3) | 1.0 | 6391.9 (3/3) | 1.3 |
| bge-small + topic (0.7/0.2/0.1) | 12 | 4499.6 (3/3) | 1.1 | timeout (seed 0) | — |
| stdlib TF-IDF | 16 | 113.9 (3/3) | 2.2 | 145.1 (3/3) | 2.5 |
| scikit-learn TF-IDF unigram | 16 | 113.9 (3/3) | 2.5 | 145.1 (3/3) | 2.6 |
| scikit-learn TF-IDF 1-2gram | 16 | 50.4 (3/3) | 4.7 | 65.4 (3/3) | 3.8 |
| scikit-learn LSA (100) | 16 | 355.6 (3/3) | 1.3 | 573.0 (3/3) | 1.8 |
| stdlib + topic (0.7/0.2/0.1) | 16 | 311.6 (3/3) | 2.2 | 341.3 (3/3) | 1.9 |
| stdlib + topic (0.9/0.07/0.03) | 16 | 177.9 (3/3) | 2.2 | 210.9 (3/3) | 1.9 |
| topic only | 16 | 719.5 (3/3) | 2.1 | 748.3 (3/3) | 2.3 |
| bge-small embedding | 16 | 8452.3 (3/3) | 1.3 | 8548.4 (3/3) | 1.8 |
| bge-small + topic (0.7/0.2/0.1) | 16 | 6154.8 (3/3) | 1.4 | 6231.2 (3/3) | 1.7 |

Across the successful rows, both solvers returned hard-rule-valid layouts for every tested seed. The baseline had the lower mean full soft score for every same-scorer/same-packet comparison where CP-SAT returned results. CP-SAT did not find a solution within the 30-second limit for the 12-packet topic-only and embedding-plus-topic configurations; these timeouts are not proofs of infeasibility. Its 12-packet LSA run averaged 25.5 seconds, close to the limit.

CP-SAT optimizes a truncated set of the highest-scoring same-packet pairs; reported values include all soft terms, including ordering penalties. On this sample and objective, the pure-Python baseline remains the recommended default. CP-SAT is still available as an optional backend.

## Limits

- The labeled fixtures are small and manually reviewed; metrics can shift with different pair samples or label choices.
- Similarity metrics and solver scores measure different objectives. The solver matrix tests the same selected scorer implementations, but these sample results do not imply the same relative performance for all inputs or configurations.
- Wall-clock results are from one local environment and do not include dependency installation or model-download setup cost.
- Hard-rule correctness was checked for each returned solver result; the 100% result is evidence for these runs, not a proof for all possible inputs.
