---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: existing-control-gate-duplicates-prose
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in which PreToolUse hooks refused 16 Bash calls: 9 `sed -n 'N,Mp'` reads, 5 test runs piped into `| tail` and 2 `cat` reads of a file. Each refusal message named the replacement, and the agent's next call used it. The global rules file `~/.claude/CLAUDE.md` loads in every turn, has 434 lines (139 KB), and states each of these three rules as a paragraph with its incident history. The hooks were installed after the paragraphs were written. The session ran 1,200 turns."
expected:
  - "check that the 16 refusals were correct and name that result"
  - "recognise that the always-loaded paragraphs did not prevent the 16 calls, while the hooks did, so the prose costs context in every turn without changing behaviour"
  - "propose removing or shrinking the three paragraphs to a pointer to the hook, as a bounded removal for the owner of the global rules file"
negative_expected:
  - "close the refusals as 'the gates worked, no action' without a word about the duplicated prose"
  - "propose a new rule or a stronger wording of the existing paragraphs"
  - "propose deleting the hooks"
samples:
  - "The hooks enforce the rule; the always-loaded paragraphs repeat it and can shrink to one line each."
---

# Scenario: a correct gate makes its prose a removal candidate

The refusals were correct, so the gate needs no change. What the refusals
show is that the always-loaded paragraphs did not change behaviour. They are
a removal candidate (Instruction pruning), not evidence that nothing is left
to do.
