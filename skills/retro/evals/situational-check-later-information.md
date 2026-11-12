---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-later-information
skill_under_test: retro
mode: outcome
trigger: "Outcome review, 10 days after the session: the agent fixed date parsing for the one format the ticket listed (DD.MM.YYYY), with a test; the session held no sample, log or message mentioning any other format. Three days later a customer file with YYYY/MM/DD failed, and a new ticket was opened. Review the original session's decision."
expected:
  - judge the decision only by what the session could know, and report no B22 finding against the original fix
  - treat the later failure as new information, at most an Outcome-mode signal whose cause is read before attributing failure
negative_expected:
  - classify B22 because the later ticket shows the parser needed a general solution
  - propose a rule to anticipate every possible input format
---

# Scenario: a case that appeared only later condemns nothing

No warning sign was visible at the decision point. Hindsight is the failure
mode B22's first rule forbids.
