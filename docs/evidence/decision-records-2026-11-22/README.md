<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Decision records: baseline and revised skill text

On 2026-11-22 three new scenarios ran once each against the unchanged skill
text at `origin/main` c64b327 and against the revised text of this change.
The revised text passed all three under an independent grader. The unchanged
text passed two and failed one as a close call.

## Question

The change adds `check-decision-records.py` and the signals E1, E7 and E8.
Does the skill text then classify the script's output correctly, and does the
unchanged text already do so?

| Case | What it checks |
| --- | --- |
| `decision-policy-undefined` | No ADR declaration in the root `AGENTS.md` (E7): report it, draft the declaration, leave yes or no to the owner |
| `decision-record-crossed` | A change crossed an accepted ADR unknowingly (E1): confirm by reading the record, route the recurrence to a CI check |
| `decision-record-superseded-with-reason` | Control: the change implements a superseding ADR, so there is no finding |

## Setup

- Inputs were frozen with `prepare-behavior-evals.py`; `manifest.json`
  records the context hashes of both arms. Both contexts held `SKILL.md` plus
  `workflow.md`, `friction-catalog.md`, `classification-heuristic.md`,
  `destination-taxonomy.md`, `project-harness-inspection.md`,
  `promote-mode.md` and `learning-contract.md`.
- Executor: one subagent per case and arm (`claude-opus-5-5`,
  Claude Code), briefed to read only its frozen context and the trigger and to
  run nothing. One execution per case and arm.
- Grader: one separate subagent of the same model with the private
  `expected` / `negative_expected` lists and the six reports under random
  labels; `label-map.json` maps the labels back. The cases' author did not
  grade.

## Result

| Case | Unchanged text | Revised text |
| --- | --- | --- |
| decision-policy-undefined | fail, close call | pass |
| decision-record-crossed | pass, one item partly met | pass |
| decision-record-superseded-with-reason | pass | pass |

The unchanged text named the missing declaration, but it proposed no
yes-or-no line and placed the decision in the commit or a code comment. In the
crossed case it proposed the CI check without its owner or the target-branch
scope. In the control it read the script's E1 as an undocumented code and
reported no finding. Reports are in `responses/`, the grading in
`grading.txt`; both are kept as the agents returned them.

## Limits

- One sample per case and arm, one model. A pass shows that the text can
  produce the behaviour, not how reliably.
- Each trigger quotes the script's output, so the cases test classification of
  that output, not whether retro runs the script. Both arms saw the same
  output; the unchanged text has no instruction to run the script at all.
- The cases were written together with the change and are development data,
  not a held-out test.
- The 15 ADRs read for the record format (five in
  netresearch/agent-harness-skill, ten in netresearch/coding_agent_cli_toolset)
  carry no `Touches` field. E8 and E1 find nothing in existing records until
  records name their paths.
