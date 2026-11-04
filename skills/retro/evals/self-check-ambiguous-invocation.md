---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: self-check-ambiguous-invocation
skill_under_test: retro
mode: spotlight
trigger: "`/retro zur retro?` right after a previous `/retro` run and its implementation in the same session. The run took the argument as 'a retro over the implementation since the last retro' and never asked. The user's next message asked whether retro should also review itself."
expected:
  - in Phase 11, report that the argument allowed two readings (a retro over the work since the last retro, or a retro of the previous retro run) and that the run chose one without asking, quoting the argument as typed
  - propose one bounded skill-update against retro-skill for argument handling — for example, a short or question-shaped argument that names retro itself is clarified before Phase 1
negative_expected:
  - treat any argument as a spotlight description without considering that it names retro itself
  - propose a general rule to ask before every run
  - produce the finding without the argument as evidence
---

# Scenario: the invocation left a decision open

A two-word argument with a question mark is not a problem description. The
self-check's third question exists for this case: the run settled an open
decision silently, and only the user's follow-up showed which reading was
meant. Evidence is the argument itself, quoted.
