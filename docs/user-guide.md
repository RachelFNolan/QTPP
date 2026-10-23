# User guide

QTPP's local browser workspace takes you from a question pool to reviewed
packet files. It does not replace editorial review: generated scores are
signals, and the final packet layout remains your responsibility.

## Start the app

From the repository root, run:

```sh
python3 -m qtpp.web_app
```

Open the address printed in the terminal, normally
[http://127.0.0.1:8765](http://127.0.0.1:8765). The workspace binds to loopback
and keeps the active pool and draft in memory for that app session. Stop it
with **Ctrl+C** in the terminal.

## Guided sample walkthrough

The app's **Try the guided sample workflow** option is an onboarding route
through the real workflow using the repository's 2025 ACF Winter sample. Read
the separate [guided walkthrough](./guided-walkthrough.md) for the in-app
step sequence, what **Next step** does, and what to review at each stage.

Across both guided and normal sessions, the workspace sidebar summarizes the
pool, template, and build. Use status hints and page-level Back/Next controls
to return to work that needs attention. Inline validation explains why an
action is unavailable; dismissible errors remain visible until dismissed. The
browser warns before leaving with unsaved template or placement edits.

## Use your own question pool

The Import view accepts a combined Question Pool CSV or a raw JSON question
pool. The supplied CSV combines tossups and bonuses into one file and keeps a
`question_type` column to distinguish them. Bonus parts stay together. See the
[technical reference](./reference.md#importing-pools) for format details and
the supported Python import functions.

You can also drag a CSV or JSON file onto the Import card. Import errors should
identify the file, row, or field that needs attention. Resolve those before
configuring a build.

## Configure a packet build

Choose a preset template, edit a copy, import a template JSON file, or start
from a pool-based suggestion. A template sets exact packet capacities and
distribution quotas. The template helper checks feasibility against the
current pool and reports shortfalls and the largest feasible packet count.

Tossup and bonus quotas can be configured separately. Additional distribution
patterns can express requirements such as exact counts across a group of
categories or distinct-category selections. Advanced grouped and exact
patterns are editable in the template JSON editor. Download a named copy to
reuse it in a later session; template JSON is one of the workspace's
persistence mechanisms.

Tossup–bonus separation is an optional hard rule. It excludes same-category
and/or same-subcategory tossups and bonuses that fall within a configured
position window in a packet. See the [packet build rules](./reference.md#packet-build-rules)
for the template shape.

## Compare candidate layouts

Select the Python baseline solver and, if installed, the optional OR-Tools
CP-SAT solver. You can compare available similarity configurations under the
same inputs and seed. The Python baseline is the default recommendation from
the checked-in benchmark, but neither solver is a substitute for reviewing the
actual layout.

Soft penalties are scorer-dependent, so raw values from different scorers are
not directly comparable. Compare the percentage improvement over random
layouts generated under the same hard rules and scored with the same scorer.
The workspace can also show a referee average across selected scorers; no
solver directly optimizes that average. See the [scoring guide](./scoring.md)
for what the measures mean.

Weight sensitivity and weight tuning are exploratory tools. Their yardstick
measures repetition and adjacency rather than editorial preference, and small
differences can be stochastic noise. Treat recommendations as starting
points, not as objective quality judgments.

## Review and audit

In **Review**, inspect each packet's questions and answers, move questions
between packets, and reorder them. Recalculation updates numbering, hard-rule
validation, leftovers, and the selected draft's soft score. Revalidate edits
before exporting.

In **Audit**, check the build summary, remaining questions, adjacent tossups,
and likely-similar within-packet pairs. Free-form audit requests currently
recognize pool categories and some century references. Audit is under
development and currently of very limited use; treat its findings as
preliminary and review packet contents directly. Similarity is only a ranking
signal: it does not prove two questions are duplicates or that players will
find them confusing.

Pair labels are saved in `calibration/labels.jsonl`; only question IDs and
normalized-text hashes are stored, not question wording. This file is
append-only and tracked in the repository. Builds can be rerun using matching
judgments from the current pool. The audit and labels are optional; inspect
the actual questions and decide how to handle uncertain pairs yourself.

## Export

The Export view can produce packet JSON, and optional DOCX and PDF documents
when the export dependencies are installed. It can package the selected
formats together as one ZIP download. Choose raw or sanitized question text,
answers, metadata, and front matter as needed. An author-map JSON can populate
author fields.

Hard-rule violations and empty packets block export. Export only after
reviewing the final packet contents and any remaining audit flags. The
[technical reference](./reference.md#generating-and-exporting-packets)
describes the Python export functions and output details.
