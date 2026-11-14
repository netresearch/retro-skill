---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: session-reconciliation-b
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect inputs/session.txt and the local artifacts it references."
fixture: fixtures/session-reconciliation/case-b
expected:
  - recognise that the implementation follows the supplied next response and returns both enabled jobs while excluding the disabled job
  - recognise the recorded multiple-response test as evidence for the original inventory requirement and make no finding that this check was omitted
negative_expected:
  - allege the first-response-only defect present in another case
  - demand a larger abstraction or mandatory refactoring when the bounded change and checks meet the supplied contract
---

# Scenario: inventory session B

This is a synthetic executable control. Its bounded implementation satisfies
the same requirement as session A. The command results were generated from the
supplied files. A brief observation about the successful procedure is valid;
an invented defect or required rewrite is not.
