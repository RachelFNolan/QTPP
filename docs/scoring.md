# Packet scoring

The packet score is a **soft penalty**: lower values are preferred, but the
score does not determine whether a packet satisfies its hard template rules.
Those rules are validated separately.

## Total score

For all packets in a layout, the default total is:

$$
\mathrm{Score}
= 1 \cdot A
+ 1 \cdot P
+ 3 \cdot N
$$

where:

- \(A\) is the number of adjacent tossup pairs in the same broad category.
- \(P\) is the sum of pairwise similarity scores for every pair of questions
  within each packet, across both tossups and bonuses. Order does not matter
  for this term.
- \(N\) is the nearby-order penalty. Within each packet's tossup sequence and
  bonus sequence, it sums pair similarity divided by the pair's distance for
  pairs up to three positions apart.

For example, if a pair has similarity \(0.6\) and the questions are two
positions apart in the same tossup or bonus sequence, this pair contributes
\(0.6\) to \(P\) and \(0.6 / 2\) to \(N\). With the default nearby weight of
three, its contribution to the total is \(0.6 + 3(0.3) = 1.5\), not counting
any other pairs or adjacency penalties. The same-packet term includes
tossup-bonus pairs; the nearby term only compares questions within the same
type's ordered sequence.

The weights and nearby window can be changed. The defaults are defined by
[`SoftWeights`](../qtpp/scoring.py), and the score is calculated by
[`score_packet`](../qtpp/scoring.py).

## Pairwise similarity

The default pair score is a weighted blend:

$$
\mathrm{sim}(q_i,q_j)
= 0.90 \cdot T(q_i,q_j)
+ 0.07 \cdot U(q_i,q_j)
+ 0.03 \cdot C(q_i,q_j)
$$

where:

- \(T\) is TF-IDF cosine similarity of the questions' searchable text.
- \(U\) is 1 when the question topics agree at the subcategory level, and 0
  otherwise. Subcategory agreement requires the same broad category and
  accounts for alternate subcategory labels.
- \(C\) is 1 when the broad categories match, and 0 otherwise.

The default searchable text uses sanitized question wording when available
(otherwise the original wording) and primary answers. For bonuses it includes
the lead-in and the wording and primary answer for each part. Tokenization
lowercases text and removes stopwords; it does not stem or lemmatize tokens.

The weights are defaults selected based on reviewed similarity-pair
calibration, not learned automatically. A scorer may be replaced or augmented
with reviewed human judgments, so the pair formula can differ for a given
build. See [`similarity.py`](../qtpp/similarity.py) and the
[calibration and benchmark notes](../STEP-2-BENCHMARK.md).

## Reading comparisons

Raw penalties depend on the scorer and its scale, so raw scores from different
scorers are not directly comparable. The workspace also compares each build
with random layouts that obey the same hard rules, scored with the same
scorer. With multiple scorers selected, its “referee” value is the average
improvement over those random baselines; solvers do not directly optimize
that average.

Similarity is a ranking signal, not a judgment that questions are duplicates
or that players will necessarily find them confusing. Review the generated
packets as well as their scores.
