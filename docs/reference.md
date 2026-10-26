# Technical reference

This page collects data-model and programmatic details that are not needed for
the first-time browser workflow. For the end-user path, see the
[user guide](./user-guide.md).

## Data model

- A `QuestionSet` contains the tossup and bonus pools, source-set metadata,
  and zero or more ordered `Packet` objects.
- Questions exist independently of packet assignment. Packets contain
  ordered `QuestionPlacement` references by question ID, with packet-local
  numbers.
- Tossups and bonuses retain IDs, topic classifications, question-level
  difficulty, and source text. Sanitized text is retained when available.
- A `Bonus` contains a lead-in and ordered `BonusPart` objects. Each part
  retains its question, answer, point value, difficulty modifier, and
  optional sanitized text.
- `QuestionSetMetadata` can include a set-wide `Difficulty` baseline with a
  broad level and optional numeric or named sublevel. A question-level
  override takes precedence; absent overrides inherit the set baseline.
  Set-level difficulty is optional for imports that do not provide it.
- HTML-style emphasis in source text is preserved rather than interpreted or
  discarded.

Create a pool before assigning packets:

```python
from qtpp import QuestionSet, QuestionSetMetadata

question_set = QuestionSet(
    metadata=QuestionSetMetadata(
        id="set-id", name="Example", year=2025, standard=True
    ),
    tossups=all_tossups,
    bonuses=all_bonuses,
)
```

## Importing pools

### Field mapping

`qtpp.field_mapping` backs the web import's mapping screen. `inspect_csv` /
`inspect_json` return the file's columns (dotted paths for nested JSON), sample
rows, and a suggested mapping from `suggest_mapping`; `mapped_csv_text` /
`mapped_pool_json` rewrite a file into the canonical layouts below using a
mapping. The web API exposes `POST /api/inspect-import` and an optional
`mapping` on `/api/import` and `/api/import-json`. Without a mapping, the
importers behave as before. `QuestionMetadata.author` holds an optional author.

### Packet JSON

Use `load_question_set` for an existing packet-set directory:

```python
from qtpp import load_question_set

question_set = load_question_set("path/to/packet-set-directory")
print(question_set.metadata.name)
print(len(question_set.packets))
```

The importer validates packet/set consistency and bonus part-array alignment,
and reports malformed source data with its file and field. The Fall sample
packet JSON was exported from the
[QBReader 2025 ACF Fall set](https://www.qbreader.org/db/set/?_id=68fc54d55b5d7bee38aa3e0a).

### Raw question-pool JSON

Use `load_question_pool_json` when the input has questions but no packets:

```python
from qtpp import load_question_pool_json

pool = load_question_pool_json("my-questions.json")
```

The file can be `{"set": {...}, "tossups": [...], "bonuses": [...]}` or a bare
question list (bonuses are recognized by `leadin`/`parts`). Questions use the
packet JSON question fields (`_id`, `question`, `answer`, `category`,
`subcategory`, bonus `leadin`/`parts`/`answers`/`values`/`difficultyModifiers`,
and optional sanitized fields); `packet` and `number` are not required. Set
metadata comes from the top-level `set`, then the first question's `set`, then
file-name defaults. When not supplied, `year` defaults to the current year.

### Combined Question Pool CSV

Load the supplied combined pool with:

```python
from qtpp import load_question_pool_csv

pool = load_question_pool_csv(
    "Test Questions/2025 ACF Winter Question Pool.csv"
)
print(len(pool.tossups), len(pool.bonuses))
```

There is one row per tossup or bonus, distinguished by `question_type`.
Source-file, set, packet, and question identifiers retain provenance and
placement data. Bonus rows keep the lead-in and all parts together;
`bonus_parts_json` preserves each part's question, answer, value, and
difficulty modifier. The importer accepts the UTF-8-BOM format, permits
additional columns, and reports malformed rows with CSV row context. It
preserves IDs, raw and sanitized text, topics, question difficulty, and bonus
part data. Generated pools can include `set_standard` and `set_difficulty`;
legacy files without those fields import unknown set metadata rather than
inventing values.

## Packet build rules

`PacketBuildSpec` describes exact tossup/bonus capacities, per-packet
category/subcategory bounds, allowed count-pattern combinations, set-wide
aggregate bounds, and permitted leftover bounds. `validate_distribution`
checks proposed counts independently of a solver.

Distributions are JSON templates loaded with `load_template(path)` or
`template_from_dict(data)` and written with `save_template` or
`template_to_dict`. `BuildTemplate` is immutable; use `dataclasses.replace`
to create an edited copy. Presets are in [`templates/`](../templates/).

Quota selectors specify minimum and maximum counts. Allowed patterns can
enumerate permitted combinations using `"type:category:subcategory": count`
entries, use compact category-count rules with an optional
`distinct_categories` requirement, or use grouped rules with exact overall
type counts and per-group totals and limits. The Fall final template uses
grouped rules instead of enumerating all combinations. Template loading
validates the schema version and rule structure and reports errors with the
file path.

Each group in a grouped rule also accepts `minimum_distinct_categories` and
`maximum_distinct_categories` (how many different categories of the group a
packet may use) and `disjoint_types` (no category supplies both a tossup and a
bonus within the group). For example, a group of Geography, Current Events, and
Other Academic with `"total": 3, "minimum_per_type": 1, "disjoint_types": true`
draws its tossups and bonuses from separate categories.

Tossup–bonus separation is represented in the spec as
`separation: {window, by_category, by_subcategory}`. Within a packet, the
configured topic matches are excluded when the absolute difference between
tossup and bonus positions is less than or equal to `window`.

## Solving and similarity

Build and solve a pool with the Python baseline:

```python
from qtpp import (
    build_similarity,
    load_question_pool_csv,
    load_template,
    solve_baseline,
)

pool = load_question_pool_csv("Question Pool.csv")
spec = load_template("templates/acf-winter-final.json").create_spec(16)
result = solve_baseline(pool, spec, build_similarity(pool), seed=0)
```

`check_pool_feasibility` and `max_feasible_packets` report necessary
conditions before solving. Solvers raise `InfeasibleError` rather than
silently relaxing hard rules.

`build_similarity` combines TF-IDF text similarity with category and
subcategory overlap. The default blend is 0.90 text, 0.07 subcategory, and
0.03 broad category; weights were selected against reviewed pairs rather than
learned automatically. A text scorer can be supplied with `text_scorer=`;
it must provide `score(first_id, second_id)` in `[0, 1]`. The optional
embedding experiments are described in the
[benchmark report](../STEP-2-BENCHMARK.md).

`SoftWeights` control the soft penalties for adjacent same-category tossups and bonuses,
similar questions in one packet, and similar questions near each other in the
ordered tossup or bonus sequence. Read [the scoring guide](./scoring.md)
before comparing raw scores from different scorers.

The `solve_baseline` solver uses a random hard-rule-valid construction
followed by swap local search. `solve_cpsat` requires OR-Tools, installed via
`requirements-dev.txt`; its objective uses only a subset of the soft terms and
the highest-scoring candidate pairs (`top_pairs`). The baseline remains the
recommended default based on the checked-in benchmark. Run
`python3 -m utilities.benchmark_solvers` to compare on a pool.

## Topic-family and time/place tools

The browser workspace applies these penalties by default (shared alternate
subcategory 0.5, cross-category theme 0.25, guessed families half the family
penalty); the `topic_penalties` object in the `/api/generate` request
(`family_penalty`, `theme_penalty`, `classify_missing`) overrides them. In the
Python API they are opt-in. `build_similarity(pool,
family_penalty=0.5)` adds a pair penalty when two questions share a family.
By default, a question's `alternate_subcategory` is its family, compared
case-insensitively; catch-alls such as Misc Literature, Misc Arts, and Other
Social Science are skipped. Use `excluded_families=` to change those
exclusions. For Other History, which has no alternate values, curated families
can be provided as `curated_families={question_id: ["Military"]}` or loaded
with `load_curated_families(...)`. An empty curated list removes a question's
family. The family penalty defaults to zero in `build_similarity`.

`theme_penalty=` adds a smaller penalty to pairs from *different* categories
that share a theme, such as a Hinduism religion question and a Ramayana
literature question. Themes come from the optional `themes` section of the
taxonomy ([`default_taxonomy.json`](../qtpp/default_taxonomy.json)); a question
joins a theme through its alternate subcategory (`families`) or a whole-word
match on its text (`keywords`). When `classify_missing` is on, the workspace
guesses families for questions with no alternate subcategory using
`family_suggest.suggested_tags` (TF-IDF by default, no extra dependencies).

`python3 -m utilities.suggest_families suggest --pool "Question Pool.csv"`
generates family suggestions. Without `--labels`, it uses
[`qtpp/default_taxonomy.json`](../qtpp/default_taxonomy.json). Alternatively,
provide a labels file and restrict processing with `--subcategory`. Backends
include `fastembed` (default), `sentence-transformers`, and dependency-free
`tfidf`. Review suggestions before approving them; they never affect a build
unless explicitly loaded. The taxonomy schema and behavior are documented in
[`qtpp/taxonomy.py`](../qtpp/taxonomy.py).

The default taxonomy's category/subcategory scopes and alternate-subcategory
labels are based on the observed values in the 2026 ACF Nationals pool.
Categories with no observed alternate labels have an empty `labels` object, so
the classifier does not invent labels for those categories. Catch-all labels
observed in that pool (Misc Arts, Misc Literature, and Other Social Science)
are listed as catch-alls rather than classifier targets.

The same utility has a `time-place` mode for suggested eras and regions. Save
the results for review, then use `load_time_place_tags(...)` and pass the
returned tags to `build_similarity` with nonzero `era_penalty` and/or
`region_penalty` to use them.

## Similarity calibration

Calibration fixtures and utilities live under `calibration/`. The reviewed
Winter and Fall pair fixtures are used to compare candidate scorers:

```sh
python3 -m calibration.evaluate_similarity
# The Fall pool is not checked in (Test Questions subfolders are gitignored);
# point --pool at your own copy.
python3 -m calibration.evaluate_similarity \
  --pool "Test Questions/2025 ACF Fall/Question Pool.csv" \
  --pairs calibration/similarity_pairs_fall.json
```

`calibration.sample_similarity_pairs` selects pairs for review, and
`calibration.review_pairs` exports/imports a Markdown review sheet. The web
app's Audit view can also append judgments to `calibration/labels.jsonl`;
`python3 -m calibration.label_cache summary` reports its counts, while
`python3 -m calibration.evaluate_similarity --labels` evaluates a scorer
against those labels. The label cache contains IDs and normalized-text hashes,
not question text.

Reviewer marks from the Review page are stored separately in
`calibration/review_marks.jsonl` (`qtpp/review_marks.py`), one JSON object per
line: `mark_id`, `question_id`, optional `other_id`, `note` (up to 500
characters), `status` (`open`, `resolved`, or `removed`), `reviewer`, `pool`,
`created_at`, `updated_at`. The latest line per `mark_id` wins. The local server
exposes `POST /api/marks` (list marks for the current pool) and
`POST /api/mark` (create, or update with `mark_id`; optional `also_label` writes
a pair label with `source` `review-mark`). Audit results include the pool's
marks.

Check the
[benchmark report](../STEP-2-BENCHMARK.md) for fixture sizes and the limits of
the reported metrics.

## Generating and exporting packets

Generate a draft and export JSON packets:

```python
from qtpp import build_similarity, generate_packets, export_packets

generated = generate_packets(pool, spec, build_similarity(pool), seed=7)
export_packets(generated.question_set, "out/")
print(generated.report)
```

`generate_packets` runs a solver and attaches numbered packets to the pool.
The same inputs and seed reproduce the same draft and byte-identical files.
Unassigned questions remain in the pool and appear in
`report.leftover_ids`. Infeasible requests or results with hard-rule errors
raise `InfeasibleError`; invalid output is not exported. `export_packets`
writes one JSON file per packet in the schema read by `load_question_set`.

Optional document exports use `export_packet_docx(...)` and
`export_packet_pdf(...)`, which return bytes for one packet. Both build from
`PacketDocument` and `FieldSelection`, preserving selected question text,
answers, bonus values/modifiers, categories, difficulty, IDs, and front
matter. Install the writer dependencies with:

```sh
python3 -m pip install -r requirements-export.txt
```

The browser Export view can produce JSON, DOCX, and PDF files and bundle the
selection in a ZIP download. Empty packets and hard-rule violations block
export.
