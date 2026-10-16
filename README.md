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
checks proposed counts without depending on a solver. The
`acf_winter_submitted_template()` and `acf_winter_final_template()` presets
provide the Winter distributions for submitted 24/24 and final/edited 20/20
packets. `blank_build_template()` starts with capacities and no category rules.
Presets are immutable values; create an edited copy when changing their rules
or capacities.

Templates can be stored as JSON with `save_template(template, path)` and read
back with `load_template(path)` (or `template_to_dict` / `template_from_dict`
for in-memory use). Editable copies of the ACF Winter presets are in
[`templates/`](./templates). Each file lists quotas as selector objects with
minimum/maximum counts; allowed patterns list each permitted combination as
`"type:category:subcategory": count` entries, with zero counts omitted. Loading
validates the schema version and rule structure and reports errors with the
file path.

## Tests

```sh
python3 -m unittest discover -s tests
```
