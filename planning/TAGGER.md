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
  question text to short tag descriptions. No keyword rules.
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
  Regions are 22, as in `calibration/soft_tags_updated.py`. Further merges (for example
  Britain and Ireland, already combined as British Isles) need review and approval.
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

## Next steps

1. Entity experiment on answer lines using only corpus statistics, scored on
   the reviewed History questions.
2. Region merge proposal, reviewed and approved by the project owner.
3. A larger review sample, and a held-out test set that tuning has not seen.
4. Integration into the app: stored suggestions with source and confidence, a
   review UI, optional dependencies, docs and tests.
