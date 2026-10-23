# QTPP — Question To Packet Pipeline

QTPP is a local application for organizing quiz-bowl question pools into
tournament packets. It helps build and compare layouts against hard
distribution rules, review and edit the results, audit potential issues, and
export packets.

The project is evolving; features and workflows may change. Start with the
[documentation index](./docs/README.md) for a map of user and contributor
documentation.

## Quick start

Run from the repository root with Python 3:

```sh
python3 -m qtpp.web_app
```

Open the local address printed in the terminal (by default
[http://127.0.0.1:8765](http://127.0.0.1:8765)). Choose **Try the guided sample
workflow** to explore the app with the included 2025 ACF Winter pool, or import
your own CSV or JSON pool. The app runs on your computer; press **Ctrl+C** in
the terminal to stop it.

The core app uses only the Python standard library. For optional PDF and DOCX
exports, install the document dependencies:

```sh
python3 -m pip install -r requirements-export.txt
```

## Documentation

- [User guide](./docs/user-guide.md) — the complete
  Import → Configure → Compare → Review → Audit → Export workflow.
- [Guided walkthrough](./docs/guided-walkthrough.md) — a page-by-page
  explanation of the sample tour and its in-app **Next step** control.
- [FAQ](./docs/FAQ.md) — common setup, data, rules, scoring, and export
  questions.
- [Technical reference](./docs/reference.md) — data formats, Python API,
  templates, solvers, similarity tools, and exports.
- [Scoring guide](./docs/scoring.md) — soft-penalty formula and similarity
  interpretation.
- [Benchmark report](./STEP-2-BENCHMARK.md) — measured solver and scorer
  comparisons and their limitations.
- [Development guide](./docs/development.md) — repository map, setup, tests,
  and documentation conventions.

Maintainer working notes: [implementation plan](./planning/PLAN.md) and
[roadmap](./planning/ROADMAP.md).

## License

QTPP's code and documentation are released under the [MIT License](./LICENSE).
Quiz-bowl question sets (such as those under `Test Questions/`) are not covered
by this license; they remain subject to their original authors' and
publishers' terms. Packet scores are advisory, and you are responsible for
having the right to use any question pool you import.
