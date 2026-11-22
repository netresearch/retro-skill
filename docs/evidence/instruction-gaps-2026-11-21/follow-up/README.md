<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Follow-up: four smaller gaps

The runs of this directory's parent record raised further points. This change
closes four of them:

| Gap | Where the rule now stands |
| --- | --- |
| The by-hand `AGENTS.md` path had no race check, since there is no scan hash | `promote-mode.md` rule 3: take the sha256 of each section when reading, compare before removing |
| Rule 1 was written for the global rules file and its reach on `AGENTS.md` was unstated | `promote-mode.md`: on the by-hand path rule 1 keeps what every agent working the repository needs in every turn |
| No destination class named a repository document a configured agent loads | `destination-taxonomy.md` `project-rule`: such a document is part of the project rule store |
| D6 and the Outcome summary read later feedback as a fault of the session | `friction-catalog.md` D6, `workflow.md` Outcome and `commands/retro.md` Outcome mode: a requirement can grow after the session; read the cause first |

Three cases ran once against the final text of this change and of #251:
`reader-and-timing-of-moved-rules`, `situational-check-later-information` and
the promote control `promotion-pr-rejected`. The context held `SKILL.md` and
nine references; `commands/retro.md` is not part of it. A separate grader
passed all three (`grading.txt`), with one close call: the
`promotion-pr-rejected` report prepared the handoff-status update without
writing it, because the executor brief forbade writes. `responses/` holds the
reports verbatim and `manifest.json` the context hashes.

Changes followed the run:

- The rerun executor of `reader-and-timing-of-moved-rules` noted that rule 3
  named no hash, so the sentence now says sha256 over each section, with
  fence-aware boundaries. A bot review added that a changed section is
  classified again before removal.
- A bot review of #251 changed the green-session calibration in
  `classification-heuristic.md` and `patch-workflow.md`: each transcript hit
  is read, and new wiring is shown by one run of the job or hook.

`promote-mode.md`, `classification-heuristic.md` and `patch-workflow.md`
therefore differ from their hashes in `manifest.json`; the other seven context
files match. No case was rerun for these changes. One sample per case, one
model.
