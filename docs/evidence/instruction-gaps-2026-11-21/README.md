<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Five instruction gaps reported by eval executors

On 2026-11-21 the executors of a baseline run
(`docs/evidence/critical-questions-2026-11-21/`, on its own branch until merged)
reported five places where the retro instructions left them to improvise. None
had produced a wrong verdict. This change states the missing rule at each place
and checks that the existing behaviour holds.

| Gap | Where the rule now stands |
| --- | --- |
| Slimming `AGENTS.md` is outside the promote scan, and the move test only asked whether "the owning skill reliably triggers" | `promote-mode.md`: by-hand path for `AGENTS.md`; rule 2 asks whether the reader loads the destination before the decision it governs |
| Gate calibration and the tier-1 test assume an incident, which a harness finding after a green session lacks | `classification-heuristic.md` and `patch-workflow.md`: firing count as the must-not-fire control; wiring an existing command needs only that it pass on the base branch |
| CI/hook parity did not say what a slow check needs | `patch-workflow.md`: parity covers fast checks and means pre-commit; a full test suite is complete in CI, a pre-push hook optional |
| Spotlight reads the last turns without saying when to read earlier | `workflow.md`: search earlier for evidence that decides between explanations, and say how far |
| B22 severity did not say whether a consequence derived from records counts as shown | `classification-heuristic.md` and `friction-catalog.md`: shown when it follows from the change and a cited record without a further assumption |

## Check

Eight described cases ran once each against the revised text, with
`friction-catalog.md` and `patch-workflow.md` in the context: the six cases of
the baseline run and two B22 controls (`situational-check-justified-small-fix`,
`situational-check-later-information`). A separate grader passed seven
(`grading.txt`). `reader-and-timing-of-moved-rules` was partial: the executor
held back naming and comment conventions, citing the new sentence about rules
the implementer needs. That sentence was narrowed to rules that must hold before
code is written, and one rerun of the case
(`responses/reader-and-timing-of-moved-rules.rerun.txt`) moved all review
heuristics and kept the tenant rule. The rerun was not given to the grader; that
verdict is the author's reading against the case's expectations.

Two findings of the run itself changed the text before commit: the first B22
severity example (a runbook reading removed output) matched none of the B22
warning signs and was replaced, and the tier-1 failure test in
`classification-heuristic.md` and `patch-workflow.md` got the same green-session
reading as the calibration rule. The run used the text before those two edits.

`manifest.json` records the context hashes; `responses/` holds the reports
verbatim. Three raw-session cases of the same change are recorded with the
baseline run.

## Limits

One sample per case, one model. The executors raised further points that this
change leaves open: a race check for the by-hand `AGENTS.md` path, which
destination class a review-only document is, and the D6 row's reading of a new
ticket.
