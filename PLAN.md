## Plan: CSV-to-Packet Builder

Build a tool that imports the existing combined Question Pool CSV, assigns questions into packets under hard sizing/category rules, improves ordering and thematic separation through tunable soft scores, and exports the existing packet JSON format. Reuse the Python model. Keep both the optimizer dependency and user-facing UI as measured decisions rather than assumptions.

**Steps**

1. **Define input and packet rules.** Add a CSV importer that handles the repository's UTF-8-BOM CSV and bonus-parts JSON, preserving IDs, raw/sanitized text, topic fields, difficulty, and set metadata. Define a build specification for packet count, exact tossup/bonus capacities, hard per-packet category min/max counts, and permitted leftovers. Interpret the example History rule as four History tossups per packet with one each from American, European, World, and Other History; make quota entries configurable rather than hard-coding that example. Fail clearly when hard requirements cannot be satisfied.
2. **Prototype similarity and select the solver.** Start with normalized category/subcategory matching plus local text-derived similarity; create a small reviewable set of question pairs to tune and assess the score. Treat no two History tossups in a row, related questions in one packet, and related questions near one another as weighted penalties, not validity failures. Benchmark a lightweight Python search against OR-Tools CP-SAT on representative packet data, comparing hard-rule correctness, soft-score quality, runtime, and setup cost. Choose the solver after the benchmark; do not silently relax hard constraints.
3. **Implement generation and JSON export.** Generate ordered packet placements while keeping overflow questions unassigned in the pool. Export one JSON file per packet using the current schema, preserving question text/answers and bonus part structure. Add deterministic seeds or equivalent repeatability so a generated draft can be reproduced. Surface infeasible hard rules and remaining soft-rule penalties in the result.
4. **Choose and build the interaction surface.** Keep the engine independent of the UI. Use a small CLI harness for repeatable generation and benchmarking; then choose the user-facing surface after the engine prototype. Recommended direction: a local browser app with CSV import, packet/constraint settings, generate, inspect/edit placements, and JSON export, because topic-similarity tuning benefits from reviewing and adjusting drafts. Preserve CLI as a useful batch interface if the browser app is selected.
5. **Document the workflow and limits.** Update the README with CSV input requirements, constraint semantics, solver choice, similarity tuning workflow, and export behavior. Treat DOCX/PDF export as a later increment; JSON is the v1 output.

**Relevant files**
- `/Users/rachelnolan/Coding/PacketizerV2/packetizer/model.py` — reuse `QuestionSet`, `Packet`, `QuestionPlacement`, `Topic`, and `Difficulty`; extend only if generation results need a domain representation not already covered.
- `/Users/rachelnolan/Coding/PacketizerV2/packetizer/json_import.py` — existing packet JSON conventions and validation behavior to preserve.
- `/Users/rachelnolan/Coding/PacketizerV2/utilities/generate_question_pool.py` — source of truth for current CSV columns and bonus serialization.
- `/Users/rachelnolan/Coding/PacketizerV2/Test Questions/2025 ACF Winter/Question Pool.csv` — representative real input and benchmark data.
- Add focused modules under `/Users/rachelnolan/Coding/PacketizerV2/packetizer/` for CSV import, build constraints/scoring, generation, and packet JSON export, following the existing package style.
- Add focused tests under `/Users/rachelnolan/Coding/PacketizerV2/tests/`; retain `/Users/rachelnolan/Coding/PacketizerV2/tests/test_json_import.py` as the JSON compatibility reference.
- `/Users/rachelnolan/Coding/PacketizerV2/README.md` — document the user workflow and supported constraints.

**Verification**
1. Unit-test CSV parsing for BOM headers, both question types, bonus parts, metadata, and malformed/misaligned rows.
2. Test exact packet capacities, hard category min/max rules, allowed leftovers, infeasible configurations, unique placement, and stable repeatability.
3. Test soft scoring for adjacent History tossups and topic/text-similar pairs; use a small labeled set of pairs to tune weights and compare rankings.
4. Benchmark candidate solvers using the checked-in pool; record validity, score, runtime, and dependency/setup cost before selecting one.
5. Round-trip generated packets through the existing `load_question_set` importer and inspect the resulting per-packet JSON.
6. Run `python3 -m unittest discover -s tests`; once a UI is selected, manually exercise CSV import through JSON download with the sample pool.

**Decisions**
- Input: combined Question Pool CSV.
- Packet sizes: exact configured capacities; leftover questions are allowed and remain unassigned.
- Hard constraints: configurable per-packet category min/max quotas; each packet's motivating History split is four tossups, one each from American, European, World, and Other History.
- Soft preferences: avoid adjacent History tossups and minimize same-packet/proximate topic and text similarity; score weights will be tuned iteratively.
- Text similarity: use topic labels and analyze question text, but start without committing to an external semantic-model dependency.
- Output: current per-packet JSON schema. DOCX/PDF are future work.
- Solver: benchmark OR-Tools CP-SAT against a lightweight Python baseline before deciding.
- User interaction: UI choice remains open; recommended workflow is generate, review/edit, export in a local browser app.

**Further Considerations**
1. During the solver benchmark, decide whether a local semantic embedding model is worth its dependency/download cost versus a lexical baseline.
2. After seeing a generated draft, choose the browser-app versus CLI-first user workflow; the generation API should support either.
