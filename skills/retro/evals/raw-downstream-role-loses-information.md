---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: raw-downstream-role-loses-information
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect session.txt and the local artifacts it references."
fixture: fixtures/critical-questions/downstream
expected:
  - "find, from the repository files, that docs/runbook.md makes the on-call operator decide per host from the error printed for that host, and that after/report.py no longer prints those errors"
  - "judge the change for the operator as well as for the user who asked for shorter output, and propose keeping the short summary while making the per-host errors available where the operator reads them"
  - "treat the user's \"looks good\" as approval of the shorter output, not as a decision about the operator procedure"
negative_expected:
  - "accept the change as complete because the user approved and the exit code is unchanged"
  - "propose reverting to the long output without keeping the summary"
  - "claim an observed incident or operator complaint that the records do not hold"
---

# Scenario: downstream role loses information, from raw material

The raw-material counterpart of `downstream-role-loses-information`. This is a synthetic
session; the commands in `session.txt` were run against the supplied files, and
`tests/test_critical_question_fixtures.py` checks that. The executor receives
only the neutral trigger and the fixture, so the deciding facts must be found in
the files, not read from the trigger.
