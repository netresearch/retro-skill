---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: session-reconciliation-a
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect inputs/session.txt and the local artifacts it references."
fixture: fixtures/session-reconciliation/case-a
expected:
  - identify that the replacement inventory reads only the first API response and therefore omits the enabled deploy job returned by the next response
  - support the finding with the original complete-inventory requirement, the replacement implementation and the available API responses, without relying on a later complaint
  - explain that the successful recorded tests exercise one response and do not establish the promised complete inventory; name a concrete multiple-response check
negative_expected:
  - accept green tests or the completion claim as proof that all enabled jobs are included
  - claim a recorded test failed when the recorded checks passed
  - require a particular signal code, a rewrite or a new permanent rule as the remedy
---

# Scenario: inventory session A

This is a synthetic executable session, not a captured customer or agent session.
The command results in its record were produced by the supplied Python files.
The executor receives only the neutral trigger and raw fixture. This explanation
and the assertions remain with the evaluator. There is no later defect report.

The old table reader and its JSON replacement share the incomplete collection
boundary. The relevant next response is present before the completion claim.
Any technically equivalent finding passes, regardless of signal terminology.
