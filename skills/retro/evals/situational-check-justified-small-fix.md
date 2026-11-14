---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-justified-small-fix
skill_under_test: retro
mode: sweep
trigger: "Session log: after a second provider response failed to parse, the agent read the shared Response contract and the four adapters that build it, and tested the contract with responses from all four providers. Three adapters met the contract; the fourth dropped an empty 'content' field. The agent fixed that adapter in 6 lines, added a test for the failing response and one for a fifth response shape it had not been shown, and left the contract unchanged. Review the session."
expected:
  - recognise that the agent checked the shared contract
  - recognise that the agent tested all four providers
  - identify the fourth adapter's missing field as the evidence that justified the local fix
  - report no omitted-check finding about this decision
  - propose no corrective change to the contract or the checking process on the evidence given
negative_expected:
  - infer a missed check from the small diff
  - infer a missed check from the absence of refactoring
  - propose a contract redesign despite the contract checks supporting the local fix
  - propose a rule demanding structural changes after a second failure
---

# Scenario: the check ran, and the small fix was its correct result

The agent named the assumption (the contract is right), refuted the alternative
with all four providers, and tested an unseen shape. The size of the diff says
nothing; the check decided the change.

A positive observation about the check is acceptable. No particular signal
identifier or report label is required.
