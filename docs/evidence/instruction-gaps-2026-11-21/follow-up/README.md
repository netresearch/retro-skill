<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Follow-up: four smaller gaps

The runs of this directory's parent record raised further points. This change
closes four of them:

| Gap | Where the rule now stands |
| --- | --- |
| The by-hand `AGENTS.md` path had no race check, since there is no scan hash | `promote-mode.md` rule 3: hash each section when reading, compare before removing |
| Rule 1 was written for the global rules file and its reach on `AGENTS.md` was unstated | `promote-mode.md`: on the by-hand path rule 1 keeps what every agent working the repository needs in every turn |
| No destination class named a repository document a configured agent loads | `destination-taxonomy.md` `project-rule`: such a document is part of the project rule store |
| D6 and the Outcome summary read later feedback as a fault of the session | `friction-catalog.md` D6 and `workflow.md` Outcome: a requirement can grow after the session; read the cause first |

Three cases ran once against the revised text, without the rule 1 sentence,
which was added after the run in answer to one of its reports:
`reader-and-timing-of-moved-rules`, `situational-check-later-information` and
the promote control `promotion-pr-rejected`. A separate grader passed all three
(`grading.txt`, without its last sentence, which named local file paths).
`responses/` holds the reports verbatim and `manifest.json`
the context hashes. One sample per case, one model.
