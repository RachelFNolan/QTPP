# QTPP

QTPP is being built incrementally to organize quiz bowl tossups and bonuses into packets under ordering and topic constraints. The first increment defines a typed, Python-native model and imports the supplied packet JSON format. It uses only the Python standard library, keeping the domain model usable by later optimization or machine-learning components.

For the packet penalty formula and how similarity is estimated, see
[the scoring guide](./docs/scoring.md).

## Data model

- A `QuestionSet` contains the full tossup and bonus pools, source set metadata, and zero or more ordered `Packet` objects.
- Questions belong to the question pool independently of packet assignment. A packet stores ordered `QuestionPlacement` references by question ID, with packet-local numbers.
- Tossups and bonuses retain their IDs, topic classifications, question-level difficulty, and source text. Sanitized text is retained where available.
- A `Bonus` is modeled as a lead-in and ordered `BonusPart` objects; each part keeps its question, answer, point value, difficulty modifier, and optional sanitized text.
- `QuestionSetMetadata` can include a set-wide `Difficulty` baseline with a broad level and optional numeric or named sublevel. For example, `Difficulty("College", "Medium")` or `Difficulty("High School", 7)`. A question can provide its own `Difficulty` override; when its difficulty is `None` (the default), it inherits the set baseline. The set-level value is optional when importing data that does not specify one. Legacy integer-only question difficulty fields are imported as inherited difficulty; explicit overrides use the `Difficulty` object shape.

HTML-style formatting in source text is preserved rather than interpreted or discarded.

Question pools can be created before any packets exist:

```python
from qtpp import QuestionSet, QuestionSetMetadata

question_set = QuestionSet(
    metadata=QuestionSetMetadata(id="set-id", name="Example", year=2025, standard=True),
    tossups=all_tossups,
    bonuses=all_bonuses,
)
```

## Importing

```python
from qtpp import load_question_set

question_set = load_question_set("Test Questions/2025 ACF Winter")
print(question_set.metadata.name)
print(len(question_set.packets))
```

The importer validates packet/set consistency and bonus part-array alignment, and reports malformed source data with its file and field.

The packet JSON files in [`Test Questions/2025 ACF Fall`](./Test%20Questions/2025%20ACF%20Fall) were exported from the [QBReader 2025 ACF Fall set](https://www.qbreader.org/db/set/?_id=68fc54d55b5d7bee38aa3e0a). Load the directory with `load_question_set` in the same way as the Winter example.

## Importing a raw JSON question pool

```python
from qtpp import load_question_pool_json

pool = load_question_pool_json("my-questions.json")  # no packets
```

The file may be `{"set": {...}, "tossups": [...], "bonuses": [...]}` or a bare list of questions (bonuses are recognized by `leadin`/`parts`). Questions use the same fields as packet JSON (`_id`, `question`, `answer`, `category`, `subcategory`, bonus `leadin`/`parts`/`answers`/`values`/`difficultyModifiers`, optional sanitized fields), but `packet` and `number` are not needed. The set record comes from the top-level `set`, else the first question's `set`, else defaults from the file name (`year` defaults to the current year). The local web app's Import view accepts `.json` as well as `.csv`.

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
from qtpp import load_question_pool_csv

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

See [STEP-2-BENCHMARK.md](./STEP-2-BENCHMARK.md) for the current focused test results,
similarity evaluation across the candidate scorers, and solver benchmark details.

```python
from qtpp import *
pool = load_question_pool_csv("Question Pool.csv")
spec = load_template("templates/acf-winter-final.json").create_spec(16)
result = solve_baseline(pool, spec, build_similarity(pool), seed=0)  # or solve_cpsat
```

- `check_pool_feasibility` / `max_feasible_packets` report necessary conditions before solving; solvers raise `InfeasibleError` rather than relaxing a hard rule.
- `build_similarity` combines TF-IDF text similarity with category/subcategory overlap (`SimilarityWeights`, default 0.9/0.07/0.03, chosen against the reviewed pairs in `calibration/similarity_pairs.json`). Pass `text_scorer=` (any object with `score(first_id, second_id)` in [0, 1]) to swap in an embedding model; in testing, bge-small embeddings did not beat TF-IDF on the reviewed pairs. Soft penalties (`SoftWeights`): adjacent same-category tossups, similar questions in one packet, and similar questions within a nearby window.
- Topic families (opt-in): `build_similarity(pool, family_penalty=0.5)` adds to the score of pairs sharing a family, so solvers keep them out of the same packet and apart within it. A question's family is its `alternate_subcategory` (Math, Drama, Poetry, ...), compared case-insensitively; catch-alls (Misc Literature, Misc Arts, Other Social Science) are skipped, configurable with `excluded_families=`. Other History has no alternate values, so use curated families: `curated_families={question_id: ["Military"]}` (or `load_curated_families("families.json")` for `{"families": {id: [...]}}`) replaces a question's automatic family; an empty list removes it. This is a soft penalty, never a hard rule, and the default of 0 changes nothing. On the Fall pool (8 packets) the baseline's same-family pairs dropped from 22 to 8; CP-SAT only optimizes its `top_pairs` most similar pairs, so it improved less (27 to 21).

- Suggesting families for untagged questions: supply a labels file (`{"labels": {"Military": "battles, wars, armies", "Diplomatic": "treaties, alliances, negotiations"}}`; a value may also be a list of example phrases) and run `python3 -m utilities.suggest_families suggest --pool "Question Pool.csv" --labels labels.json --output suggestions.json`. Every question with a blank `alternate_subcategory` (and no entry in `--curated`) is compared with each label; restrict it with repeatable `--subcategory "Other History"`. `--backend` is `fastembed` (default), `sentence-transformers` or the dependency-free `tfidf` (weakest); `--model` overrides the model. A label is proposed only if its score reaches `--min-score` and beats the runner-up by `--min-margin`; otherwise it is `null` with a `best_guess`. Suggestions never affect a build: edit the `label` fields, then run `python3 -m utilities.suggest_families approve suggestions.json --output families.json` (entries with an empty label are dropped) and pass the result to `load_curated_families`. Descriptions matter; a bare label name embeds poorly. Pass your own function to `suggest_families(pool, labels, similarity)` to use another classifier.

- Taxonomy-driven suggestions (default): with no `--labels`, `suggest` uses [qtpp/default_taxonomy.json](qtpp/default_taxonomy.json), a per-category list of alternate subcategories (Science: Mathematics, Astrophysics, Earth Science, Engineering, Computer Science; Literature: Drama, Poetry, Long/Short Fiction; History: Military, Political, Social, Economic; Fine Arts: Opera, Instruments, Painting, Architecture, Sculpture, Specific Works, Dance, Film, Jazz, Photography; Social Science: Psychology, Economics, Anthropology, Linguistics, Sociology). Each label has descriptions, `aliases` (existing pool values such as Math or Astronomy map to Mathematics/Astrophysics so they match), and optional `subcategories` limits (Opera only applies to Auditory/Other Fine Arts, Painting to Visual/Other Fine Arts). A category can also be limited to subcategories (Science only applies to Other Science, so Biology is never labeled Mathematics). `Other` and the old catch-alls are never matched. Edit a copy and pass `--taxonomy FILE`; the schema is documented in [qtpp/taxonomy.py](qtpp/taxonomy.py) and is meant for a future GUI to read and write. Every untagged question in a taxonomy category is classified by similarity to the label descriptions; labels that already have at least `--min-examples` (default 5) tagged questions in the pool also get an example-based check, and a disagreement leaves the question unsure. `--auto-margin 0.06` marks proposals whose lead over the runner-up is at least that as status `auto`; the margin predicted accuracy better than the raw score (on hidden-alternate tests of the Winter pool, a margin of 0.06 or more was about 93% right, versus about 59% overall), and `approve --auto-only` accepts only those. Expect roughly 60-85% accuracy by category (Science, Social Science and Fine Arts are strongest; separating Drama and Poetry from fiction, and History's four labels, are weakest), so review the rest.
- Using unreviewed suggestions in scoring (opt-in): `build_similarity(pool, family_penalty=0.5, suggested_families=suggested_tags(pool, backend_fn), suggested_penalty=0.25)` penalizes pairs that share a suggested family but no confirmed one, by `suggested_penalty` (default half of `family_penalty`; confirmed families always win). Do not expect much from it: in a hidden-alternate test on Winter and Fall (alternates removed, scored against the real ones, 5-12 seeds), unreviewed suggestions did not measurably reduce same-family pairs at any weight or confidence cutoff, because only about half of the truly tagged questions received a correct tag. Confirmed tags (existing alternates plus reviewed or `--auto-only` approved suggestions, passed as `curated_families`) are what produced the large reductions, so review first and use this only as a stopgap.
- Era and region spread (opt-in): `python3 -m utilities.suggest_families time-place --pool "Question Pool.csv" --output tags.json` guesses an era (from years and centuries in the text; History and Literature) and a region (from place names; History) and writes them for review; questions with no clear signal get no tag. Then `eras, regions = load_time_place_tags("tags.json")` and `build_similarity(pool, eras=eras, regions=regions, era_penalty=0.1, region_penalty=0.1)` adds a soft penalty to same-category pairs sharing a tag (`era_categories=`/`region_categories=` change the scope). Both penalties default to 0. `family_penalty` merges aliases (Math = Mathematics) using the default taxonomy; pass `family_aliases=` to override or `{}` to disable.
- `solve_baseline` is pure Python: a random hard-rule-valid construction, then swap local search. It requires exact selectors in explicit pattern rules.
- `solve_cpsat` needs `ortools` (`pip install -r requirements-dev.txt`). Hard rules are exact constraints, but only the most similar pairs (`top_pairs`) enter its objective. It defaults to one worker because multi-worker search hung on macOS in testing.
- `python3 -m utilities.benchmark_solvers` compares them. On the sample pool both are always valid in 1–3 s. The baseline scores 10–13% lower (better) on the full soft score, so it is the default choice.
- Similarity calibration lives in `calibration/`: `similarity_pairs.json` holds the reviewed Winter pairs (`label` = a player would notice a shared topic; `borderline` = unsure, skipped by default). Fall pairs are kept separately in `similarity_pairs_fall.json` as a held-out check. For Fall, review `similarity_pairs_fall_review.md`, import with `python3 -m calibration.review_pairs import --json calibration/similarity_pairs_fall.json --markdown calibration/similarity_pairs_fall_review.md`, then evaluate using `python3 -m calibration.evaluate_similarity --pool "Test Questions/2025 ACF Fall/Question Pool.csv" --pairs calibration/similarity_pairs_fall.json`. `python3 -m calibration.evaluate_similarity [--embeddings] [--include-borderline] [--weights TEXT SUB CAT]` compares scorers (`--weights` scores your own blend). `calibration.sample_similarity_pairs` draws a fresh sample, and `calibration.review_pairs` exports/imports a markdown review sheet. Rerun the evaluation before changing `SimilarityWeights` defaults.

## Generating and exporting packets (Step 3)

```python
from qtpp import *
generated = generate_packets(pool, spec, build_similarity(pool), seed=7)  # solver="cpsat" also works
export_packets(generated.question_set, "out/")      # one JSON file per packet
print(generated.report)                             # solver, seed, soft-score breakdown, leftover IDs
```

- `generate_packets` runs a solver and attaches numbered packets to the pool (`build_question_set` does the second half for an existing `SolverResult`). The same inputs and seed reproduce the same draft and byte-identical files. Unassigned questions stay in the pool and are listed in `report.leftover_ids`. Infeasible requests or results with hard-rule errors raise `InfeasibleError`; nothing is exported.
- `export_packets` writes `NN_<packet-name>.json` files in the schema read by `load_question_set` (raw and sanitized text, bonus part arrays, topics, difficulty). Unknown set metadata is written as `null`. Empty packets are rejected, and no file is written if any packet is invalid.
- Install the optional document writers with `python -m pip install -r requirements-export.txt`; core imports and JSON export remain standard-library-only.
- `export_packet_docx(question_set, packet, selection=..., authors=...)` and `export_packet_pdf(...)` return bytes for one packet, ready to write to a file. Both build from `PacketDocument` and `FieldSelection`, retaining source emphasis (`<b>`, `<u>`, `<i>`) and selected answers, bonus values/modifiers, categories, difficulty, question IDs, and front matter. The layout follows a traditional quiz-bowl packet style: letter pages with one-inch margins, 10-point Times-style text, compact left-aligned headings, uppercase answer labels, and bracketed bonus-part tags. Pass `authors={question_id: name}` (or load `{"authors": {...}}` with `load_authors`) to include author names.
- The browser Export view can produce one DOCX and/or PDF per packet alongside the existing JSON files. Expand **Document contents** to select raw or sanitized question text, answer and metadata fields, and front matter. An optional author-map JSON can populate author fields. Hard-rule violations and empty packets block every selected format. The browser downloads everything as a single `.zip` (the API returns one when `"zip": true` is sent), which avoids browser prompts about multiple downloads.

## Local browser workspace (Step 4)

Run the desktop-first, local-only packet workspace with the Python standard library. Install `requirements-export.txt` as above to enable DOCX/PDF output:

```sh
python3 -m qtpp.web_app
```

Open the printed `http://127.0.0.1:8765` address. The app binds to loopback, serves its UI locally, and keeps the imported pool and generated draft in memory for the current session; it does not call a hosted service. Use **Try the guided sample workflow** to load the repository's 2025 ACF Winter CSV and follow the import-to-export path, or select your own combined Question Pool CSV.

The left navigation separates Import, Configure, Compare, Review, Audit, and Export. Each step shows a status marker and hint (done, ready, needs attention, or waiting on an earlier step), and every page ends with Back/Next buttons. A collapsible **Workspace summary** in the sidebar keeps the pool (set, counts, categories, subcategories), the template (name, packets, sizes, feasibility), and the build (solvers, selected run, hard-rule status, leftovers, unsaved edits) visible on every page. Forms validate inline and block **Run selected builds** with a stated reason; builds show a progress panel with elapsed time; error messages stay until dismissed (Esc or ×); the browser warns before you leave with unsaved template or placement edits. CSV/JSON pools can also be dragged onto the Import card.

- **Configure:** choose one of the checked-in packet templates, edit its per-packet category/subcategory quotas in separate **Tossup quotas** and **Bonus quotas** sections, or copy tossup categories, subcategories, minimums, and maximums to replace the bonus quotas. Downloading a modified pre-built template requires changing its name so its JSON filename cannot overwrite the pre-built template. Add **Additional distribution patterns** as rule cards (for example, “each packet needs 1 tossup and 1 bonus from Geography, Current Events, Pop Culture or Other Academic, each from a different category”): pick categories from the pool, set the tossup/bonus counts, and optionally require each to come from a different category. Group rules and exact-combination rules (such as the Fall preset's) appear as read-only cards and are edited in the collapsed **Advanced: view or edit JSON** box, which stays in sync with the cards. Import and download template JSON to reuse custom distributions in later sessions; template files and packet exports are the persistence mechanism.
- **Template help:** the side panel checks the template against the imported pool as you edit, showing shortfalls, the largest packet count the pool supports (with a one-click "use" link), and a pass/fail summary. The single **Starting point** dropdown on the Configure page combines pre-built templates (use as-is or as a base), pool-based suggestions, and **Start from scratch**. The suggestion options fill quotas that mirror the pool's category mix for your packet count and per-packet sizes (strictness: exact, ±1, or ±2). The mirror method works at category level (default strictness: exact counts). **Build by category and subcategory** lets you set tossups and bonuses per packet for each major category (prefilled from the pool, with custom rows allowed) and add subcategory rows with their own tossup/bonus minimum and maximum; **Apply to template** writes ordinary quota rows and sets the packet sizes to the totals, so the template JSON format is unchanged. Distinct-category rules remain manual. **Duplicate** and **Reset to preset** help iterate on variations.
- **Tossup–bonus separation (optional hard rule):** in Configure, set a window (≥1) and choose same category and/or same subcategory. Within a packet, no tossup and bonus sharing the chosen topic may be within that many positions (|tossup# − bonus#| ≤ window is excluded; tossup 4 with window 3 excludes bonuses 1–7). Solvers optimize ordering to satisfy it; any packet that still cannot is reported as a hard-rule violation. In templates/API it is `separation: {window, by_category, by_subcategory}` (`TossupBonusSeparation` on `PacketBuildSpec`).
- **Compare:** select the Python baseline and/or the optional OR-Tools CP-SAT solver, and compare balanced TF-IDF/topic, text-only TF-IDF, and topic-only similarity. Multiple selections run with the same pool, template, packet count, and seed. Results are stacked vertically with the best build highlighted (★ Best score). Each card shows **% better than random** (higher is better) beside the raw **penalty** (lower is better). Penalties from different similarity scorers are on different scales, so the % figure compares each build with random hard-rule-valid layouts scored by the same scorer (0% = no better than random). By default builds are ranked by the **referee**, the average of that figure across all selected scorers, which no solver optimizes directly; you can instead rank by one scorer or by each build's own penalty (not comparable across scorers). The number of random baseline samples is configurable (default 30; more is steadier but slower). Results also show placement, soft-score breakdown, runtime, and leftovers. CP-SAT is offered only when OR-Tools is installed. The similarity choices are local scoring configurations, not learned semantic models.
- **Weight sensitivity:** below the Compare results, **Analyze weight sensitivity** re-runs the Python baseline for the selected build with each soft-score weight (adjacent category, same packet, nearby) scaled by 0, ½, 2 and 4 in turn, same seed. A first table shows each term's raw size and share of the total penalty at your current weights; a second shows, for every variation, the raw term values, the penalty at your weights, and how much the packets changed (same-packet pairings and slot contents). Weights whose variation changes nothing are called out as not worth tuning. The search is stochastic, so small differences are noise.
- **Tune weights:** below the sensitivity table, **Find best weights** takes the best build for each selected scorer (by % better than random) and searches soft-score weights with the Python baseline: a coarse grid of 0.5×/1×/2× on each weight, then a refinement around the winner, each candidate averaged over several seeds. Candidates are rated on a yardstick that does not depend on the weights being tried (every term at weight 1, scaled by its random-layout mean, averaged over terms and scorers), so lowering a weight can never look better. The winner is re-checked on held-out seeds and is recommended only if it beats your weights by more than the noise; **Use these weights and re-run all builds** then confirms it across every solver/scorer pair. CP-SAT is not searched because its assignment only responds to the same-packet weight. A seeds/held-out/time-limit setting bounds the cost (about 70 builds per scorer at the defaults; hard cap 400). The yardstick measures repetition and adjacency, not editorial taste, so treat the result as a starting point.\n- **Review:** inspect packet questions and answers, move questions between packets, and reorder them within a packet. Recalculate after edits to see numbering, hard-rule violations, leftovers, and updated soft scores. Edits are revalidated before audit/export; JSON export is blocked when hard constraints fail or a packet is empty.
- **Audit:** run a pre-export review of hard-rule status, leftovers, the most similar within-packet question pairs, and adjacent same-category tossups. Free-form local requests currently recognize pool categories and century references such as “too much 20th-century material.” Composition is compared with the overall pool and peer packets; counts, coverage, percentage-point differences, and question IDs are shown rather than imposing a guessed threshold. If a request cannot be interpreted, the app asks for a clearer category or period. Date/century inference is heuristic and should be reviewed. The audit boundary is designed to allow a future AI-backed investigator, but v1 sends no question data to an external model.
- **Export:** download one JSON, DOCX, and/or PDF file per packet. JSON uses the existing import-compatible schema; document output uses the selected text, answer, metadata, and front-matter options. Your browser may ask permission for multiple downloads.

The Python package remains independent of the UI, and the existing CLI/batch workflows continue to work. The app has no project database or plugin system; future audit, scorer, or export capabilities can be added behind the existing engine/application boundaries.

## Similarity label cache

In the Audit view, mark each likely-conflict pair **Too similar**, **Fine together** or **Unsure**. Judgments accumulate in `calibration/labels.jsonl` (append-only, committed to the repo; newest label per pair wins). Pairs are keyed by a hash of both questions' normalized text, and only IDs and hashes are stored, never question text. `python3 -m calibration.label_cache seed` imports a reviewed pair file, `summary` prints counts, and `python3 -m calibration.evaluate_similarity --labels` scores each similarity scorer against the cache (warning while labels are few).

### Re-running with your judgments

At the bottom of the Audit conflicts card, **Re-run builds with my judgments** repeats the last build (same template, solvers, scorers and seed) with every saved judgment that matches the current pool: “Too similar” pairs are raised to a heavy penalty so solvers keep them apart, and “Fine together” pairs score zero. Scores and the random baseline use the same adjusted scorer, so “% better than random” stays like for like. The optional **Never place flagged pairs in the same packet** box makes the separation exact in CP-SAT and a very strong penalty in the Python baseline. The result reports how many flagged pairs shared a packet before and after. Without that box CP-SAT only weighs tossup–tossup and bonus–bonus pairs, so cross-type flagged pairs may remain.

## Tests

```sh
python3 -m unittest discover -s tests
```
