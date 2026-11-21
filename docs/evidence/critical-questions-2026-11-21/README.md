<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Baseline run: downstream roles, unprotected green sessions, rule placement, discriminating checks

On 2026-11-21 six new scenarios ran once each against the unchanged skill at
`origin/main` e179037. All six passed under an independent grader. Each
trigger states the deciding facts, so the run shows that the current text
classifies those facts correctly. Whether retro finds them unprompted in raw
session material is untested. No instruction text was changed; the scenarios
are kept as regression fixtures.

## Question

Four candidate additions were proposed for the skill. Each one would add
instruction text:

| Candidate | Scenario and its control |
| --- | --- |
| Assess a measure for the role that works with its result next, not only for the executor | `downstream-role-loses-information`, control `downstream-side-effect-unevidenced` |
| Report existing checks that nothing runs, also after a green session | `green-session-unwired-checks`, control `green-session-checks-already-wired` |
| Name who reads a moved rule and whether the read happens before the decision it governs | `reader-and-timing-of-moved-rules` |
| Run the check that can change the decision before more analysis | `discriminating-check-before-more-analysis` |

Text is added only where the unchanged skill fails such a case.

## Setup

- Inputs were frozen with `prepare-behavior-evals.py`; `manifest.json` records
  the context hashes. The context was `SKILL.md` plus `workflow.md`,
  `learning-contract.md`, `project-harness-inspection.md`,
  `classification-heuristic.md`, `destination-taxonomy.md`, `promote-mode.md`
  and `prior-attempts.md`. `friction-catalog.md` was not included.
- Executor: one subagent per case (`claude-opus-5-5`, Claude Code), briefed to
  read only the frozen context and the trigger. Its recorded tool calls show
  two reads of exactly those files and in-memory searches over their content;
  no other read, write or shell command. One execution per case; the manifest's default
  `samples_per_arm` of 3 was not used.
- Grader: one separate subagent of the same model with the private
  `expected` / `negative_expected` lists and the six reports. The cases'
  author did not grade.

## Result

| Case | Verdict |
| --- | --- |
| downstream-role-loses-information | pass |
| downstream-side-effect-unevidenced | pass |
| green-session-unwired-checks | pass |
| green-session-checks-already-wired | pass |
| reader-and-timing-of-moved-rules | pass |
| discriminating-check-before-more-analysis | pass, with two negative items graded as close calls |

The reports are in `responses/`, the grading in `grading.md`.

## Limits

- One sample per case, one model, described situations rather than raw
  session material. A pass shows that the current text can produce the
  behaviour; it does not show how reliably.
- The cases were written after the candidates were known and are development
  data, not a held-out test.
- The executors reported open points in the instructions. One was fixed
  separately because it is a wrong cross-reference, not a behaviour change:
  the outdated routing heading name, in three places. Five remain open:
  - promote mode excludes `AGENTS.md` and phrases its move test only as "the
    owning skill reliably triggers";
  - the tier-1 gate calibration assumes an incident, which a harness finding
    from a green session does not have;
  - the CI/hook parity rule names a pre-commit hook and does not say whether a
    pre-push hook satisfies it;
  - Spotlight reads the last turns and does not say when to widen the window
    to evidence earlier in the session;
  - B22 severity does not say whether a consequence derived from documents,
    without an observed incident, counts as shown.
