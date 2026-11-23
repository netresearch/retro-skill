<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Existing controls: unchanged and revised command text

On 2026-11-23 the unchanged `commands/retro.md` (`origin/main` 1f6da03) and
the revised text of commit 943a15e ran on the same evidence. On five described
cases both texts gave the expected answer. On one case built from a real
session, the revised text scored 6.0 of 9 points and the unchanged text 2.0,
under an independent grader. ADR-003 records the decision.

## Question

On 2026-11-22 a Sweep closed frictions as covered because a document, rule or
gate existed: 17 GitHub rate-limit failures, hook refusals, and a
Windows-only defect that the fourth review round found. Does the revised
command (Phases 2b and 4b, and the rule that an existing control does not
close a friction) change that?

## Run 1: five described cases

The `existing-control-*` cases in `skills/retro/evals/` ran once per case
and arm. Inputs were frozen with `prepare-behavior-evals.py`; the context
held `SKILL.md` plus the command copied into the skill directory, each from
its own arm: the baseline arm `origin/main` 1f6da03, the revised arm the
command of commit 943a15e. All ten reports gave the expected disposition, so
no grader ran. Each trigger states
the decisive facts already sorted (for example the release targets next to
the PR runners), so the cases test classification, not whether the run looks.
They stay in the corpus as pins.

## Run 2: the real session

- **Evidence:** the compaction summary the real Sweep had in context, the
  output of its own pre-pass scripts as it received them, the netresearch/ofelia
  files at commit e9f231c (`AGENTS.md`, `.goreleaser.yml`,
  `.github/workflows/`), and git-workflow's `merge-gate-watcher.md` at
  1c35ad9. The trigger carried no diagnosis.
- **Context:** the command text alone, as a `/retro` run loads it.
- **Executor:** three subagents per arm (`claude-opus-5-5`, Claude Code),
  read-only.
- **Grader:** one separate subagent of the same model, with the six reports
  under random labels and three items: the rate-limit failures, the Windows
  defect and the hook refusals. PASS counts 1, PARTIAL 0.5.

| Arm | Rate limit | Windows | Hook refusals | Points |
| --- | --- | --- | --- | --- |
| Unchanged, run 1 | FAIL | PARTIAL | FAIL | 0.5 |
| Unchanged, run 2 | FAIL | PASS | FAIL | 1.0 |
| Unchanged, run 3 | FAIL | PARTIAL | FAIL | 0.5 |
| Revised, run 1 | PASS | PASS | PASS | 3.0 |
| Revised, run 2 | FAIL | PARTIAL | PARTIAL | 1.0 |
| Revised, run 3 | PARTIAL | PASS | PARTIAL | 2.0 |

All three unchanged runs closed the rate-limit failures as documented in the
watcher reference, as the real Sweep did. One revised run did too.

Context hashes (sha256, first 16 characters):

- `baseline-context.md`: `2f315e3e9f607933`
- `candidate-context.md`: `0cb3de41ba6047ec`
- `session.txt`: `e54c8a08a243d553`

## Limits

- Both runs measured the revised command at 943a15e. The review fixes in
  5bd7dc7 and later (destinations of the rule, the C6 condition on removing
  prose, mode scoping of Phase 4b) were not re-measured.

- Three samples per arm, one model, one session. The revised text improves
  the result; it does not make it reliable (one revised run still failed the
  rate-limit item).
- The reports and the session evidence are not committed: they quote a
  personal rules file, local paths and a private session. They stay with the
  run's author.
- The cases were written together with the change and are development data.
- Executors could not run scripts; two ran read-only shell listings against
  the instruction.
