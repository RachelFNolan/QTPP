# Guided sample walkthrough

The app's **Try the guided sample workflow** option loads the repository's
2025 ACF Winter question pool and takes you through the same stages used for
your own pool. You do not need to prepare a CSV or template first.

## Start the tour

1. From the Import page, select **Try the guided sample workflow**.
2. QTPP loads the sample, opens **Configure**, and displays the guided demo
   prompt for **Step 2 of 6**. Loading the sample is step 1.
3. At each stage, follow the instruction in the guided demo card. The
   **Next step** button advances to the next page; it does not complete the
   work for you, run a build, or export files. You can also use the normal
   page navigation to revisit earlier stages.

## The six steps

1. **Load the sample.** The 2025 ACF Winter combined CSV is loaded locally.
   Confirm the pool summary before configuring a build.
2. **Configure packet rules.** Choose a ready-to-use template and packet
   count. Inspect packet sizes, quotas, and feasibility. The template sets
   hard constraints; it is an editable starting point rather than a required
   answer.
3. **Compare build approaches.** Select a solver and similarity scorer, then
   run one or more builds. Check hard-rule validity and leftovers first.
   Compare scores only with their scorer's matching random baseline.
4. **Review and arrange packets.** Inspect the questions and answers in a
   candidate layout. Move or reorder questions and recalculate validation
   after edits. Optionally use ⚑ to mark questions you think may conflict.
5. **Investigate packet composition.** In Audit, ask a composition question
   and inspect the evidence and likely conflicts. Similarity flags are review
   prompts, not proof that questions are duplicates.
6. **Export packet files.** Select the output formats and document fields,
   then download the reviewed files. DOCX and PDF require the optional export
   dependencies.

The guided prompt begins at step 2 because sample loading is performed
automatically. Follow the onscreen instruction before selecting **Next step**;
the prompt is a navigation aid, not a checklist that verifies each action.
The full [user guide](./user-guide.md) explains templates, scoring, review,
audit, and export in more detail.
