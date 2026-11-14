---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-later-information
skill_under_test: retro
mode: outcome
trigger: "Outcome review, 10 days after the session: the agent fixed date parsing for the one format the ticket listed (DD.MM.YYYY), with a test; the session held no sample, log or message mentioning any other format. Three days later a customer file with YYYY/MM/DD failed, and a new ticket was opened. Review the original session's decision."
expected:
  - judge the original decision using the one documented format available during that session
  - report no omitted-check finding against the original fix on the evidence given
  - treat the customer file's different format as new information
  - require cause analysis before attributing the later failure to an error in the original work
negative_expected:
  - condemn the original fix solely because the later ticket supplies another format
  - propose a rule to anticipate every possible input format
---

# Scenario: a case that appeared only later condemns nothing

No warning sign was visible at the decision point. A later issue can warrant
follow-up without proving that the original decision was wrong. Grade this
temporal distinction independently of the signal identifier used.
