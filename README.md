# Packetizer

Packetizer is being built incrementally to organize quiz bowl tossups and bonuses into packets under ordering and topic constraints. The first increment defines a typed, Python-native model and imports the supplied packet JSON format. It uses only the Python standard library, keeping the domain model usable by later optimization or machine-learning components.

## Data model

- A `QuestionSet` contains the full tossup and bonus pools, source set metadata, and zero or more ordered `Packet` objects.
- Questions belong to the question pool independently of packet assignment. A packet stores ordered `QuestionPlacement` references by question ID, with packet-local numbers.
- Tossups and bonuses retain their IDs, topic classifications, question-level difficulty, and source text. Sanitized text is retained where available.
- A `Bonus` is modeled as a lead-in and ordered `BonusPart` objects; each part keeps its question, answer, point value, difficulty modifier, and optional sanitized text.
- `QuestionSetMetadata` can include a set-wide `Difficulty` baseline with a broad level and optional numeric or named sublevel. For example, `Difficulty("College", "Medium")` or `Difficulty("High School", 7)`. A question can provide its own `Difficulty` override; when its difficulty is `None` (the default), it inherits the set baseline. The set-level value is optional when importing data that does not specify one. Legacy integer-only question difficulty fields are imported as inherited difficulty; explicit overrides use the `Difficulty` object shape.

HTML-style formatting in source text is preserved rather than interpreted or discarded.

Question pools can be created before any packets exist:

```python
from packetizer import QuestionSet, QuestionSetMetadata

question_set = QuestionSet(
    metadata=QuestionSetMetadata(id="set-id", name="Example", year=2025, standard=True),
    tossups=all_tossups,
    bonuses=all_bonuses,
)
```

## Importing

```python
from packetizer import load_question_set

question_set = load_question_set("Test Questions/2025 ACF Winter")
print(question_set.metadata.name)
print(len(question_set.packets))
```

The importer validates packet/set consistency and bonus part-array alignment, and reports malformed source data with its file and field.

The packet JSON files in [`Test Questions/2025 ACF Fall`](./Test%20Questions/2025%20ACF%20Fall) were exported from the [QBReader 2025 ACF Fall set](https://www.qbreader.org/db/set/?_id=68fc54d55b5d7bee38aa3e0a). Load the directory with `load_question_set` in the same way as the Winter example.

## Combined question pool

The supplied `Test Questions/2025 ACF Winter` set has a combined CSV at
[`Test Questions/2025 ACF Winter/Question Pool.csv`](./Test%20Questions/2025%20ACF%20Winter/Question%20Pool.csv).
It contains one row per tossup or bonus. The `question_type` column distinguishes
them, while source file, set, packet, and question identifiers retain provenance
and placement information. Bonus rows keep the lead-in and all parts together;
`bonus_parts_json` preserves each part's question, answer, value, and difficulty
modifier. The combined question and answer text columns provide readable
multiline versions for browsing and searching.

Keeping both types in one CSV makes the pool easier to search, deduplicate, and
maintain consistently. Separate CSVs can be more convenient for tools that only
consume one type, but require coordinating schemas and updates. Filtering the
combined file on `question_type` can produce those type-specific views when
needed.

The CSV can be loaded as an unpacketized pool:

```python
from packetizer import load_question_pool_csv

question_pool = load_question_pool_csv(
    "Test Questions/2025 ACF Winter/Question Pool.csv"
)
print(len(question_pool.tossups), len(question_pool.bonuses))
```

The importer accepts the UTF-8-BOM format, permits additional columns, and
reports malformed rows with their CSV row context. It preserves question IDs,
raw and sanitized text, topics, question difficulty, and bonus part data.
Generated pools also include `set_standard` and `set_difficulty`; legacy files
without those fields import with missing set metadata marked unknown rather
than defaulted.

## Packet build rules

`PacketBuildSpec` describes exact tossup/bonus capacities, per-packet
category/subcategory bounds, allowed count-pattern combinations, set-wide
aggregate bounds, and permitted leftover bounds. `validate_distribution`
checks proposed counts without depending on a solver.

Distributions are defined as JSON templates and loaded into a `BuildTemplate`
with `load_template(path)` (or `template_from_dict` for in-memory use);
`save_template` / `template_to_dict` write them back. `BuildTemplate` is an
immutable value; use `dataclasses.replace` to make an edited copy. Ready-made
ACF templates (Winter submitted and final, Fall final) are in
[`templates/`](./templates). Each file lists quotas as selector objects with
minimum/maximum counts. Allowed patterns can enumerate permitted combinations
using `"type:category:subcategory": count` entries, or use a compact category
count rule with a list of categories, exact tossup/bonus counts, and an optional
`distinct_categories` requirement. For example, a rule with categories
`["Geography", "Current Events"]`, counts `{"tossup": 1, "bonus": 1}`, and
`distinct_categories: true` requires one tossup and one bonus from those
categories, with the two questions coming from different categories. The
category names match the broad question category and include all subcategories.
For flexible distributions spanning multiple category groups, a grouped count
rule can set exact overall type counts and describe each group's total, minimum
per type/category, and distinct-category limits. The Fall final uses this form
instead of enumerating 48 combinations.
Loading validates the schema version and rule structure and reports errors
with the file path.

## Building packets (Step 2 prototype)

```python
from packetizer import *
pool = load_question_pool_csv("Question Pool.csv")
spec = load_template("templates/acf-winter-final.json").create_spec(16)
result = solve_baseline(pool, spec, build_similarity(pool), seed=0)  # or solve_cpsat
```

- `check_pool_feasibility` / `max_feasible_packets` report necessary conditions before solving; solvers raise `InfeasibleError` rather than relaxing a hard rule.
- `build_similarity` combines TF-IDF text similarity with category/subcategory overlap (`SimilarityWeights`, default 0.9/0.07/0.03, chosen against the reviewed pairs in `calibration/similarity_pairs.json`). Pass `text_scorer=` (any object with `score(first_id, second_id)` in [0, 1]) to swap in an embedding model; in testing, bge-small embeddings did not beat TF-IDF on the reviewed pairs. Soft penalties (`SoftWeights`): adjacent same-category tossups, similar questions in one packet, and similar questions within a nearby window.
- `solve_baseline` is pure Python: a random hard-rule-valid construction, then swap local search. It requires exact selectors in explicit pattern rules.
- `solve_cpsat` needs `ortools` (`pip install -r requirements-dev.txt`). Hard rules are exact constraints, but only the most similar pairs (`top_pairs`) enter its objective. It defaults to one worker because multi-worker search hung on macOS in testing.
- `python3 -m utilities.benchmark_solvers` compares them. On the sample pool both are always valid in 1–3 s. The baseline scores 10–13% lower (better) on the full soft score, so it is the default choice.
- Similarity calibration lives in `calibration/`: `similarity_pairs.json` holds the reviewed Winter pairs (`label` = a player would notice a shared topic; `borderline` = unsure, skipped by default). Fall pairs are kept separately in `similarity_pairs_fall.json` as a held-out check. For Fall, review `similarity_pairs_fall_review.md`, import with `python3 -m calibration.review_pairs import --json calibration/similarity_pairs_fall.json --markdown calibration/similarity_pairs_fall_review.md`, then evaluate using `python3 -m calibration.evaluate_similarity --pool "Test Questions/2025 ACF Fall/Question Pool.csv" --pairs calibration/similarity_pairs_fall.json`. `python3 -m calibration.evaluate_similarity [--embeddings] [--include-borderline] [--weights TEXT SUB CAT]` compares scorers (`--weights` scores your own blend). `calibration.sample_similarity_pairs` draws a fresh sample, and `calibration.review_pairs` exports/imports a markdown review sheet. Rerun the evaluation before changing `SimilarityWeights` defaults.

## Tests

```sh
python3 -m unittest discover -s tests
```
