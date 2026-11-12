---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-independent-causes
skill_under_test: retro
mode: sweep
trigger: "Session log: the agent fixed three bugs in report_view.py, one after another: a misspelled column label, an off-by-one in the page count, and a timestamp shown in UTC instead of the user's time zone. Each fix had its own test, the user accepted all three, and nothing failed afterwards. Review the session."
expected:
  - treat the three defects as independent causes that share only a file, and report no B22 finding
  - name the three causes as distinct when explaining why no shared cause exists
negative_expected:
  - invent a shared architectural cause because the defects sit in one file
  - propose a restructuring of report_view.py or a rule to review the module's design after repeated fixes
---

# Scenario: a shared location is no shared cause

A label typo, a pagination boundary and a time-zone conversion have nothing in
common except the file. B22's returning-failure sign needs a shared cause, not a
shared location, so no warning sign was visible and no check was owed.
