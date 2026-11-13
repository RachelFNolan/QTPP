# Local tagger (experimental, internal notes)

Goal: suggest alternate subcategories, era and region tags, and cross-category
theme tags locally, with no outside LLM. Tags are suggestions with a confidence
and never overwrite imported values. These are internal notes, not product
commitments.

## Status

- Alternate subcategory: chosen tagger is TF-IDF plus all-MiniLM-L6-v2
  embeddings (`concat`). Development cross-validation accuracy is about 0.84;
  about 73% of questions are answered at 0.7 confidence with about 93% accuracy.
  Stronger embedding models (bge-small, bge-base) gained about one point at
  several times the cost, so they were not adopted. The formal 2025+ validation
  has not been run for this choice.
- Era and region: experimental soft tagger (`calibration/soft_tags_updated.py`) compares
  question text to short tag descriptions. No keyword rules. Default threshold
  0.25, with era temperature 0.03 and region temperature 0.02. Held-out check
  on 100 validation questions done (see below).
- Theme tags: not started.

## Decisions

- Evaluation first, with a date split: sets through 2024 for development,
  2025 and later for formal validation.
- Tags are soft and multi-label, each with a confidence. A question can carry
  several era and region tags, and may carry none.
- A bonus is one entity. It is tagged as a whole and is never scored or split
  by part.
- Eras are 7 (Ancient; Medieval; Early modern; Revolutionary and industrial age;
  Imperial age and World War I; Interwar and World War II; Postwar to present).
  Regions are 22, as in `calibration/soft_tags_updated.py`. The vocabulary is approved.
  Any later merge needs review and approval.
- A "multiple eras/regions" flag will not be derived from tag-confidence
  spread. Tested on 50 reviewed History questions, that flag had about 40%
  precision. It should come from a human judgment or a learned signal.

## Findings from the 50-question History review

- Confidence is meaningful. Era precision was 85% at 0.7+ and about 50% below
  0.5 with the old 12 eras. Region precision was 100% at 0.7+.
- Era vocabulary was too fine. Neighboring periods were confused, and modern
  eras were under-tagged.
- With 7 eras, high-confidence tags were reliable but found only about a third
  of the correct eras (recall is the limit).
- These numbers were tuned on the same 50 questions, so they are optimistic.

## Held-out check on 100 validation History questions

- Sample: 20 questions per History subcategory, drawn from the 2025-and-later
  pool (`tagger_data/collegiate_2025_plus` and the other validation files). Not
  used for tuning. Settings were fixed before scoring.
- Scored with `python3 -m calibration.tune_soft_tags --source validation --fixed`
  at the current temperatures. No sweep was run on this sample.
- Era (123 judged positives): threshold 0.20 gave 72% precision and 76% recall;
  0.25 gave 74% and 72%; 0.30 gave 77% and 70%; 0.50 gave 85% and 54%.
- Region (128 judged positives): 0.20 gave 76% and 70%; 0.25 gave 78% and 67%;
  0.30 gave 82% and 66%; 0.50 gave 87% and 60%.
- Decision: keep the default threshold at 0.25, given the recall emphasis.
- Caveats: the sample is small. Some tags were judged only through `missing` lines.

## Idea under consideration: entity lookup

Extract entities (people, places, events) and look up when and where they are
associated, from the corpus's own tag distributions and optionally Wikidata.

Caveat: many quiz bowl answer lines are generic and apply in any era or place
(for example, "slavery"). The lookup must:

- measure specificity (how concentrated an entity's tags are across the corpus)
  and return a tag only for specific entities;
- allow an explicit "any era or region" outcome, and abstain rather than force
  a tag from the answer line alone;
- weight evidence by role (answer, main subject, passing mention) and by
  specificity;
- leave the text-based tag in place for generic answers, since clues usually
  anchor them;
- report results separately for specific and generic answers.

Generic answers are also the likeliest targets for later theme tagging.

### Method so far (experimental, corpus statistics only)

Code: `calibration/entity_lookup.py`. No Wikidata.

- Entities come from spaCy `en_core_web_sm` NER (PERSON, GPE, LOC, NORP, FAC,
  EVENT) over clue text, leadin, and answer lines. The strongest role wins per
  entity: answer (weight 1.0), leadin (0.5), clue (0.25).
- The statistics pool is built only from pre-2025 questions (all categories,
  `labeled_only=False`). Validation never enters the pool.
- Specificity (option A): the top tag's share of the entity's weighted
  confidence mass, compared with absolute thresholds set separately for eras
  and regions. Specific at or above `era_specific` / `region_specific`; any
  below `era_any` / `region_any`; otherwise abstain. Support must be at least
  `min_support`. Replaces the earlier lift rule, which depended on vocabulary size.
- The entity path acts only when the answer-line outcome is specific. It raises
  the top tag of each specific entity (`np.maximum` with the text tag). It can
  add a tag above threshold but never removes one.
- Default settings in code: `min_support` 3.0, leadin 0.5, clue 0.25,
  era_specific 0.4, era_any 0.18, region_specific 0.15, region_any 0.06.
  The validation path still uses these defaults. They have not been frozen
  or scored.

### Dev sweep and matched control (History only, dev only)

- Scoring pool: 196 reviewed History dev questions, merged from `tag_review.md`
  (49) and `tag_review_extra.md` (150). Reviewer label spellings are mapped
  with `REVIEW_ALIASES` in `calibration/tune_soft_tags.py`. Skipped: 17
  ambiguous, 4 unmapped, 17 unknown verdicts.
- Grid: 576 settings, leave-one-out on the dev pool. Settings were ranked by
  entity F1 minus a budget-matched control F1 (see below).
- Control: on the same questions the answer gate marks specific, the second-ranked
  text tag is raised to the threshold. This adds about as many tags as the entity
  path and uses no entity statistics. An earlier control that promoted the
  second tag on all questions added more tags, so it was not a fair comparison.
- Text-only F1: era 0.69, region 0.71. Best entity mean: 0.756 (era 0.74,
  region 0.78). Matched control: era 0.74, region 0.75. Best matched gain
  is +0.013 (region +0.03, era 0). The top five settings tie at +0.013.
- Added tags: era entity 86 vs control 94; region entity 107 vs control 106.
- The "any" outcome never fires under these thresholds. Even a perfectly flat
  distribution has a top share of at least 1/7 ≈ 0.143 for eras and 1/22 ≈ 0.045
  for regions, so the tuned `any` thresholds can only fire on near-flat entities,
  and none occur in this data. The "any" branch is untested.
- These gains are optimistic: the best of 576 settings was chosen on the same
  196 questions. Validation has not been scored.

### Contamination check (Literature and Fine Arts, dev only, no labels)

- The entity pool is built from all pre-2025 categories. A History-only pool
  was compared with the all-category pool on dev Literature (2,000) and Fine
  Arts (1,934) questions.
- The all-category pool fires the answer gate far more often: era specific on
  524 vs 97 Literature questions and 481 vs 126 Fine Arts questions; region
  specific on 1,074 vs 195 and 934 vs 228. Tags were added to 214 Literature and
  181 Fine Arts questions (era) with all categories, vs 43 and 55 with History
  only. This suggests cross-category entity leakage. It does not show whether
  the added tags are correct.
- Next step if resumed: review samples for Literature and Fine Arts. Partial
  files exist and are gitignored: `tagger_data/reviews/tag_review_literature.md`
  (20 of 100 questions) and `tagger_data/reviews/tag_review_fine_arts.md`
  (10 of 100). Nothing is verdict-labeled yet. Both need completing before any
  score.
- Status: on hold. The earlier stalled sub-agent was not used to finish them.

### Coverage check (descriptive, all categories)

`python3 -m calibration.entity_lookup --coverage`. Pool: all 21,159 pre-2025
questions. Scored: 16,684 validation questions. Default settings. No tags
changed, no F1. Cells are rates with 95% Wilson intervals.

Note: this table was computed with the earlier lift rule, before option A. The
gate rates below are stale and should be rerun with the current settings.

| Measure (pooled) | Rate |
|---|---|
| Answer keys seen in dev | 46% (45–47%) |
| Answer keys with support ≥ 3.0 | 17% (17–18%) |
| Answer-line gate, era: specific / abstain / insufficient / any | 34% / 6% / 60% / 0% |
| Answer-line gate, region: specific / abstain / insufficient / any | 40% / 0% / 60% / 0% |

Per-category answer-key coverage is lowest for Science (20%, usable 6%) and
highest for Mythology (67%) and Philosophy (59%). Other Academic has no dev
questions and is shown as no dev data.

"Question has a key" is 100% in every category, because clue text almost always
contains a named entity. It does not discriminate and should not be read as
coverage.

Open problems found by the coverage run:

1. Lift depended on vocabulary size. Option A replaced it with absolute
   per-kind thresholds, fitted on dev only. The "any" outcome still never fires,
   so it is untested. Open question: whether any "any" rule can work with
   a 7-era or 22-region vocabulary.
2. About 60% of validation questions get no answer-line outcome. Those are
   insufficient support, so the entity path cannot reach them at the current
   support threshold.
3. Dev coverage is uneven across categories (see the per-category rows above).
   Science answers are least covered, so a tournament-mix change would change
   how well this method works.

## Next steps

1. Decide whether the "any" outcome is worth redesigning (see open problem 1).
   Hold on tweaking it until the user decides.
2. Entity experiment, Literature and Fine Arts: on hold. Finish the partial
   review files, then score on reviewed dev questions.
3. Entity experiment on validation: only after settings are frozen by the user.
   Build the statistics from dev and score validation once.

The era and region vocabulary (7 eras, 22 regions) is approved. "Late Cold War"
stays merged into "Postwar to present".

Later:

- Enlarge the review set and the held-out test set before choosing any new
  setting. The first held-out check (100 questions) is done.
- App integration: stored suggestions with source and confidence, a review UI,
  optional dependencies, docs and tests.
