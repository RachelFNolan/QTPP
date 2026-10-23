# Historical implementation plan: CSV-to-Packet Builder

This plan records the original implementation scope and decisions. It is kept
as a maintainer reference, not an active task list or a user guide. For current
user workflows and technical details, see the [user guide](../docs/user-guide.md)
and [technical reference](../docs/reference.md).

Original objective: build a tool that imports the combined Question Pool CSV,
assigns questions into packets under hard sizing/category rules, improves
ordering and thematic separation through tunable soft scores, and exports the
existing packet JSON format. The plan was to reuse the Python model and treat
the optimizer dependency and user-facing UI as measured decisions.

**Steps**

1. **Define input and packet rules.** Add a CSV importer that handles the repository's UTF-8-BOM CSV and bonus-parts JSON, preserving IDs, raw/sanitized text, topic fields, difficulty, and set metadata. Define a build specification for packet count, exact tossup/bonus capacities, hard per-packet category min/max counts, and permitted leftovers. Interpret the example History rule as four History tossups per packet with one each from American, European, World, and Other History; make quota entries configurable rather than hard-coding that example. Fail clearly when hard requirements cannot be satisfied.
2. **Prototype similarity and select the solver — DONE.** Implemented and evaluated local text/topic similarity, soft penalties, and both solver backends; benchmark results and the baseline solver decision are recorded in [STEP-2-BENCHMARK.md](../STEP-2-BENCHMARK.md). The solver and similarity benchmark outcomes and limitations are documented in the report.
3. **Implement generation and JSON export — DONE.** Implemented in `generation.py`, `json_export.py`, and `document.py` (field-selectable, render-ready packet documents used by the optional PDF/DOCX exports). Original scope: generate ordered packet placements while keeping overflow questions unassigned in the pool. Export one JSON file per packet using the current schema, preserving question text/answers and bonus part structure. Add deterministic seeds or equivalent repeatability so a generated draft can be reproduced. Surface infeasible hard rules and remaining soft-rule penalties in the result.
4. **Choose and build the interaction surface — DONE.** Added a desktop-first local browser workspace in `qtpp/web_app.py`, `qtpp/workspace.py`, and `qtpp/web/`. It imports CSV, edits/imports/exports templates, compares solver and similarity configurations, supports placement review/editing, performs deterministic evidence-backed audits, and downloads the existing packet JSON. The Python engine remains independent and no hosted service or plugin system is required.
5. **Document the workflow and limits — DONE.** The local browser workflow, template editing/portability, comparisons, editing/revalidation, audit scope/limitations, and exports are documented in the user guide and technical reference. DOCX/PDF export is available with optional dependencies.

**Relevant files**
- [`qtpp/model.py`](../qtpp/model.py) — domain model (`QuestionSet`, `Packet`, `QuestionPlacement`, `Topic`, and `Difficulty`).
- [`qtpp/json_import.py`](../qtpp/json_import.py) — packet JSON conventions and validation behavior.
- [`utilities/generate_question_pool.py`](../utilities/generate_question_pool.py) — source of truth for CSV columns and bonus serialization.
- [`Test Questions/2025 ACF Winter/Question Pool.csv`](../Test%20Questions/2025%20ACF%20Winter/Question%20Pool.csv) — representative real input and benchmark data.
- [`qtpp/`](../qtpp/) — implementation modules for import, constraints/scoring, generation, export, and the browser app.
- [`tests/`](../tests/) — focused tests; [`test_json_import.py`](../tests/test_json_import.py) is the JSON compatibility reference.
- [`README.md`](../README.md) — project landing page; user workflow details now live in [`docs/`](../docs/).
- [`qtpp/web_app.py`](../qtpp/web_app.py) and [`qtpp/workspace.py`](../qtpp/workspace.py) — loopback-only application transport and engine orchestration.
- [`qtpp/web/`](../qtpp/web/) — local browser user interface.

**Verification**
1. Unit-test CSV parsing for BOM headers, both question types, bonus parts, metadata, and malformed/misaligned rows.
2. Test exact packet capacities, hard category min/max rules, allowed leftovers, infeasible configurations, unique placement, and stable repeatability.
3. Test soft scoring for adjacent History tossups and topic/text-similar pairs; use a small labeled set of pairs to tune weights and compare rankings.
4. Benchmark candidate solvers using the checked-in pool; record validity, score, runtime, and dependency/setup cost before selecting one.
5. Round-trip generated packets through the existing `load_question_set` importer and inspect the resulting per-packet JSON.
6. Run `python3 -m unittest discover -s tests`; exercise the local workspace from CSV import through JSON download with the sample pool and round-trip the output through `load_question_set`.

**Decisions**
- Input: combined Question Pool CSV.
- Packet sizes: exact configured capacities; leftover questions are allowed and remain unassigned.
- Hard constraints: configurable per-packet category min/max quotas; each packet's motivating History split is four tossups, one each from American, European, World, and Other History.
- Soft preferences: avoid adjacent History tossups and minimize same-packet/proximate topic and text similarity; score weights will be tuned iteratively.
- Text similarity: use topic labels and analyze question text, but start without committing to an external semantic-model dependency.
- Output: current per-packet JSON schema; DOCX/PDF were deferred at the time of this plan and are now available with optional dependencies.
- Solver: benchmark OR-Tools CP-SAT against a lightweight Python baseline before deciding.
- User interaction: desktop-first local browser app, left navigation, guided sample, and local-session drafts.
- User templates: GUI editing with portable JSON files; no app database.
- Audit: deterministic local free-form requests for known category/century concepts; comparative distribution evidence and ranked conflict candidates; ambiguous concepts ask for clarification. A future AI auditor can plug into the audit boundary.
- Scorer comparison: choose and compare solver backends and built-in TF-IDF/topic similarity configurations; only installed optional solver backends are enabled.

**Further Considerations**
1. **Resolved:** the benchmark kept embeddings optional; the default remains dependency-light.
2. Add further audit query types and optional semantic/AI scorers through the modular application/engine boundaries; do not silently change the local-only data-flow default.
