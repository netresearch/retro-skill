---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: rule-never-applicable-is-a-candidate
skill_under_test: retro
mode: audit
trigger: "`/retro audit` ran `scan-cross-session.py --rule-tally ~/.claude/CLAUDE.md --days 90`: sessions_read 140, window_sufficient true, and never_applicable lists A204, a rule whose only keyword is `make deploy-legacy`."
expected:
  - "report A204 as a removal candidate under C7 and route it to 'Instruction pruning', with the bounded comparison and the file owner's approval"
  - "check whether a hook, checkpoint or CI rule already prevents the mistake, because a rule that works silently also has zero hits"
  - "name the keyword and window, and say that the zero describes those keywords in those 140 sessions"
negative_expected:
  - "delete the rule or open a removal PR on the tally alone"
  - "call the rule proven unnecessary"
samples:
  - "A204 had no keyword hit in 140 sessions; it is a removal candidate, not a removal."
---

# Scenario: a rule no session touched

The tally is a candidate list. The zero says only that no tool call, result or
user turn in the window named `make deploy-legacy`. Removal goes
through the existing pruning path (`classification-heuristic.md`) and
`learning-contract.md`.
