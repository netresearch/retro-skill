<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Baseline run: downstream roles, unprotected green sessions, rule placement, discriminating checks

On 2026-11-21 six new scenarios ran once each against the unchanged skill at
`origin/main` e179037. All six passed under an independent grader. Each
trigger states the deciding facts, so the run shows that the current text
classifies those facts correctly. A second run, below, gave three of the cases
as raw session material instead; both the unchanged and a revised skill text
found the facts unprompted. The scenarios are kept as regression fixtures.

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

- One sample per case and one model. Six cases are described situations;
  three of them were repeated as raw sessions. A pass shows that the text can
  produce the behaviour; it does not show how reliably.
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

## Raw-material run

Three cases were rebuilt as synthetic sessions with the repository files they
worked in, under `skills/retro/evals/fixtures/critical-questions/`:
`raw-downstream-role-loses-information`, `raw-green-session-unwired-checks`
and its control `raw-green-session-checks-already-wired`. The trigger only says
to inspect `session.txt` and the local artifacts. The recorded commands are
reproduced by `tests/test_critical_question_fixtures.py`.

Each case ran once in two arms: the skill text at `origin/main` e179037 and the
revised text of the follow-up change. The executors could read only the frozen
context and their own fixture copy; their recorded tool calls show no other
read, no write and no shell command. A separate grader passed all six reports
(`raw/grading.txt`); `raw/responses/` holds them verbatim and `raw/manifest.json` the
context hashes.

| Case | Unchanged text | Revised text |
| --- | --- | --- |
| raw-downstream-role-loses-information | pass | pass |
| raw-green-session-unwired-checks | pass | pass |
| raw-green-session-checks-already-wired | pass | pass |

Two corrections were made after the run and before grading or commit:

- One negative item of `raw-green-session-unwired-checks` forbade a pre-commit
  hook for the test suite. The fixture's suite runs in milliseconds, so a hook
  is allowed by the fast-check definition. The item now forbids a hook without
  a stated fast-check reason. Both arms were graded against the corrected item.
- Both arms noted that the fixture's `build.yml` had no checkout step and the
  repository no `Dockerfile`. Both were added afterwards. Neither finding
  depended on them, but the committed fixture is not byte-identical to the one
  the run used.
