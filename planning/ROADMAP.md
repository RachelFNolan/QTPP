# QTPP roadmap

This is an internal working document for maintainers. Items are exploratory
and are not user-facing commitments or a release schedule.

Working notes on what to build next and what might be worth cutting. Items are judgments from building and testing the app so far, not commitments. Each entry says why it matters.

## Features to add

### Higher value

- **Packet-vs-packet preference labels.** Show two candidate packets and record which one a reviewer prefers, stored in the repo like `calibration/labels.jsonl`. This is the only way to fit the soft-score weights to editorial taste. Today the weight tuner measures repetition and adjacency, not what a reviewer would call a good packet.
- **Score published packets.** Run each soft term over the real packets in `Test Questions/` to see what human-edited packets look like. If they consistently have no adjacent same-category tossups, that justifies a high weight. This needs no new labeling.
- **Normalize the soft-score terms.** Divide each term by its random-baseline mean so a weight reads as relative importance. Today adjacent-category counts whole pairs and the similarity terms sum fractions, so equal weights are not equal influence.
- **Solver parity for the soft terms.** CP-SAT only optimizes the same-packet term, and it only weighs same-type pairs unless hard separation is on. Either model the nearby and cross-type terms or label clearly in the UI which terms each solver optimizes.
- **Long-running jobs with progress and cancel.** Tuning, re-runs and large builds currently run inside one request. A background job with a real progress count and a cancel button would make them safe to run on large pools.
- **Save and load a session.** The workspace is in memory, so a restart loses the build, the baseline and any review edits. Saving the build settings, chosen run and edited layouts to a file would remove that risk.
- **Refresh scores after review edits.** After moving questions, only the selected draft's penalty is recalculated. The cross-scorer scores, "% better than random" and referee stay stale until builds are re-run. Recompute them for the edited layout.

### Review and audit

- **Surface potential conflicts in Review.** Highlight likely-similar question
  pairs within each packet on the Review and arrange page, so reviewers can
  spot and address them while editing instead of needing to find them in Audit.
- **Undo and redo in Review**, and drag-and-drop to reorder or move questions, in place of the up, down and move controls.
- **Show more than the top 20 conflicts**, with filters by packet, category, label status and type pair, and a "label next unlabeled pair" flow to build the cache faster.
- **Format question text in Audit** (the new pair view already does; the composition tables show plain IDs).
- **Penalize consecutive bonuses in the same category.** Only tossups have an adjacency rule today.
- **Explain hard-rule failures** with a suggested fix, for example which quota to loosen when a pool is infeasible or a hard separation can't be met.
- **Flag or block a "too similar" pair at export** if it is still in one packet, as an option.
- **Add an optional author-grouping hard rule.** Let users who need it keep
  questions by the same author together in one packet, rather than spreading
  that author's questions across packets.

### Similarity and labels

- **Learn a scorer from the label cache.** Once there are a few hundred labels, fit a small model (for example, logistic regression over the existing text and topic features) and evaluate it with `calibration/evaluate_similarity.py --labels`.
- **Label hygiene tools:** detect conflicting labels for one pair, show label history, support more than one reviewer, and merge or dedupe caches from several people.
- **Mark which labels have never been checked against the current pool**, so reviewers know which ones affect a re-run.
- **An optional AI-backed audit investigator** behind the existing audit boundary. Keep it opt-in, since v1 sends no question data off the machine.

### Quality and operations

- **Browser tests in the repo.** UI checks so far were ad hoc headless runs. A small Playwright suite for Compare, Review, Audit and tuning would catch layout and JavaScript regressions.
- **Detect a stale server on port 8765.** Two sessions this project hit a leftover process serving old code. Starting the app should say the port is taken, or offer another port.
- **Export checks:** a pre-export summary (packet sizes, category counts, unresolved flags) and an optional filename prefix.
- **Accessibility pass** for the new tables and the stacked cards: table headers and scope, color-independent best-score marker, and keyboard access for the label buttons.

## Features to consider removing

These are candidates, not recommendations to delete everything. Each has a cost in screen space, code or explanation, and a reason it may not be earning it.

| Candidate | Why consider removing | What would change |
|---|---|---|
| **Per-term soft-weight inputs** (adjacent, same packet, nearby, window) on Compare | On the demo pool, adjacent-category had no visible effect and nearby had a small one. Four numeric inputs invite tuning with little payoff. | Hide under an "Advanced" disclosure, or ship fixed defaults and keep the weights as template or file settings. |
| **"Analyze weight sensitivity" and "Find best weights" together** | Both answer "do the weights matter?". If tuning stays, the sensitivity table is mostly redundant. If sensitivity stays, tuning may be over-engineered for a pool too small to show differences. | Keep one, or merge the sensitivity table into the tuning result. |
| **Similarity options that are not learned** (balanced, text-only, topics-only) | Three scorers multiply every build, the cross-score matrix and the explanation needed on Compare. Topics-only barely uses the text. | Keep one default scorer plus an optional second for cross-checking, and drop the "referee" averaging if only one remains. |
| **The "referee" and the yardstick dropdown** | A lot of explanatory text for something that only matters with several scorers selected. | Show only "% better than random" for one scorer by default, and expose the others on demand. |
| **"Own penalty" ranking option** | Its UI says it is not comparable across scorers, so it mostly invites misreading. | Remove, or show raw penalties only inside each card. |
| **CP-SAT solver** | It optimizes only the same-packet term, needs an optional dependency, and in tests it left flagged cross-type pairs in place unless hard separation was on. | Keep only if it clearly wins on real pools; otherwise drop it and the `separate` pathway. |
| **Template suggestion modes** (mirror method, strictness, per-subcategory builder) | Three overlapping ways to fill quotas, plus presets, "Start from scratch", duplicate and reset. | Merge into one "Suggest from pool" action with a strictness choice. |
| **Demo guide and sample data flow** | The guided sample is an onboarding route and has a dedicated walkthrough page. Its extra state is worth revisiting only if it creates concrete maintenance or usability problems. | Keep the sample and its user-facing walkthrough; simplify the guided state only if evidence shows it is not useful. |
| **Calibration side files** (`similarity_pairs*.json`, the review markdown files, `sample_similarity_pairs.py`, `review_pairs.py`) | The label cache now holds the same judgments. Two stores for one purpose will drift. | After seeding is confirmed complete, keep one fixture format and delete the rest. |
| **Committed `calibration/labels.jsonl`** | Appends from the web app change a tracked file during normal use, creating noisy diffs and merge conflicts as labels grow. | Keep for now as agreed. Revisit once labels are numerous, or move to a separate data file or repository. |

## Suggested order

1. Score published packets and add a stale-server warning (small, immediate value).
2. Refresh scores after review edits and normalize the soft-score terms.
3. Packet-preference labels, then re-run weight tuning against them.
4. Decide the removals above using real-pool results rather than the demo pool.
