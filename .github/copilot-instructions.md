# QTPP project instructions

## Keep documentation in sync

When a change affects behavior, commands, inputs/outputs, file formats, UI
labels or flow, scoring, dependencies, or project layout, update the affected
documentation in the same change. See the documentation map in
[docs/development.md](../docs/development.md#keeping-documentation-current).

| If you change... | Update... |
|---|---|
| Install/run commands, optional dependencies | `README.md` quick start, `docs/development.md` |
| Browser workflow, UI labels, page order | `docs/user-guide.md`, `docs/guided-walkthrough.md`, `docs/FAQ.md` |
| Guided demo steps (`demoStages` in `qtpp/web/app.js`) | `docs/guided-walkthrough.md` |
| Import/export formats, templates, Python API, solvers | `docs/reference.md` |
| Score terms, weights, similarity defaults | `docs/scoring.md`, and `STEP-2-BENCHMARK.md` if benchmarks are rerun |
| New or moved documents | `docs/README.md` index and the root `README.md` links |
| Shipped or dropped roadmap item | `planning/ROADMAP.md` |

## Documentation conventions

- Keep the root README a short landing page; put detail in `docs/`.
- Document current behavior only. Mark experimental or future work as such;
  `planning/` files are internal notes, not product commitments.
- Use relative Markdown links and check that moved or renamed files and
  headings do not break links.
- Do not add question text or other copyrighted question content to docs.
- Note documentation changes in the final summary of your work, or state why
  none were needed.
