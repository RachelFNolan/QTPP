# Development guide

This guide is for contributors working in the repository.

## Repository map

- `qtpp/` — Python domain model, import/export, build rules, solvers, scoring,
  workspace orchestration, and browser UI.
- `qtpp/web/` — browser assets (`index.html`, `app.js`, and `app.css`).
- `tests/` — unit and integration tests for the Python package.
- `templates/` — reusable packet-build template JSON files.
- `calibration/` — similarity fixtures, label data, and calibration utilities.
- `utilities/` — standalone pool and benchmark utilities.
- `docs/` — user documentation and technical references.
- `planning/` — internal implementation and roadmap notes.
- `Test Questions/` — sample question sets used in examples and tests.

## Set up and run

The core package uses the Python standard library. Start the local workspace
from the repository root:

```sh
python3 -m qtpp.web_app
```

Install optional packages only when needed:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pip install -r requirements-export.txt
```

`requirements-dev.txt` supplies optional solver, evaluation, and suggestion
backends; `requirements-export.txt` enables PDF and DOCX document generation.

## Verify changes

Run the Python test suite with:

```sh
python3 -m unittest discover -s tests
```

For a focused change, invoke the relevant test module first, then run the full
suite when appropriate. Documentation-only changes should at minimum be
checked for accurate commands, valid relative links, and consistency with the
current UI and API.

## Keeping documentation current

Update documentation in the same change as the behavior it describes.

| If you change... | Update... |
|---|---|
| Install/run commands, optional dependencies | [README](../README.md) quick start and this guide |
| Browser workflow, UI labels, page order | [User guide](./user-guide.md), [guided walkthrough](./guided-walkthrough.md), [FAQ](./FAQ.md) |
| Guided demo steps (`demoStages` in `qtpp/web/app.js`) | [Guided walkthrough](./guided-walkthrough.md) |
| Import/export formats, templates, Python API, solvers | [Technical reference](./reference.md) |
| Score terms, weights, similarity defaults | [Scoring guide](./scoring.md); [benchmark report](../STEP-2-BENCHMARK.md) if benchmarks are rerun |
| New or moved documents | [Documentation index](./README.md) and root README links |
| Shipped or dropped roadmap item | [Roadmap](../planning/ROADMAP.md) |

Before finishing, check that relative links and heading anchors still resolve
and that commands in the docs still run. The same checklist is in
[`.github/copilot-instructions.md`](../.github/copilot-instructions.md) for
AI assistants.

## Contribution conventions

- Keep changes focused and consistent with the existing package and test
  patterns.
- Add or update tests when behavior changes; preserve the standard-library
  core unless a new dependency is justified.
- Keep user instructions in `docs/` and short entry-point material in the
  root README. Put detailed formulas, schemas, and programmatic examples in
  the technical reference or scoring guide.
- Distinguish current behavior from experimental or future work. The
  `planning/` files are maintainer notes, not product commitments.
- Update affected documentation and links when commands, inputs, outputs, or
  user-visible behavior change.
