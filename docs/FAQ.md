# Frequently asked questions

## Does QTPP send my question data to a server?

The browser workspace serves locally and binds to loopback. The core app does
not call a hosted service. Its active pool and build draft stay in memory for
the current app session. Optional embedding backends may need separate model
downloads or dependencies; they are not required for the default workflow.

## What should I use to get started?

Run `python3 -m qtpp.web_app` from the repository root, open the printed local
address, then choose **Try the guided sample workflow**. The
[guided walkthrough](./guided-walkthrough.md) explains the sample tour and
the [user guide](./user-guide.md) covers the full workflow.

## What input formats are supported?

The browser Import view accepts combined Question Pool CSV files and raw JSON
question pools. The Python API also loads packet JSON files and directories
containing them. See [importing pools](./reference.md#importing-pools) for
details.

## Does QTPP require every question to be used?

No. A build can leave questions unassigned when the template permits
leftovers. The build report lists leftover IDs so you can review them.

## What is the difference between a hard rule and a soft score?

Hard rules determine whether a layout is valid—for example, packet capacities
or category quotas. Soft scores rank valid layouts according to preferences
such as avoiding adjacent same-category tossups or similar questions in the
same packet. A low score does not excuse a hard-rule violation. See the
[scoring guide](./scoring.md).

## Does the score tell me that questions are duplicates?

No. Similarity is a ranking signal based on text and topic features, not a
duplicate detector or an editorial judgment. Inspect flagged questions in
context and decide whether they belong together.

## Which solver should I use?

The Python baseline is the built-in default and needs no solver dependency.
CP-SAT is optional and requires OR-Tools. The benchmark found the baseline
better on the tested sample and settings; this does not guarantee it will be
better on every pool. CP-SAT can also take longer or time out. See the
[benchmark report](../STEP-2-BENCHMARK.md).

## How do I save a template or build?

Templates can be downloaded as JSON and imported in a later session. Packet
exports are downloaded as files. The current workspace does not save the
entire in-memory session, selected build, and review edits for later
restoration; export anything you need to keep.

## What can I export?

Packet JSON is available without optional document packages. DOCX and PDF
exports require installing `requirements-export.txt`. The browser can bundle
selected output formats into one ZIP. See the [export guide](./user-guide.md#export).

## Where are pair-label judgments saved?

Audit labels are appended to `calibration/labels.jsonl`. The file stores
question IDs and hashes of normalized text, not question text, and is tracked
in the repository. The latest label for a pair takes precedence. Review the
file's changes before sharing or committing them.

## Where are Review marks and notes saved?

Marks made with the ⚑ button in Review are appended to
`calibration/review_marks.jsonl`. It stores question IDs, optional notes, status
and timestamps, not question text, and is tracked in the repository. The latest
record for a mark takes precedence. Notes may contain anything you type, so
check them before sharing the file.

## Is the guided sample required?

No. It is an onboarding option, not a prerequisite. Import your own CSV or
JSON pool from the Import view whenever you are ready.
