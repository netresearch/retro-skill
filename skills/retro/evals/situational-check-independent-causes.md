---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-independent-causes
skill_under_test: retro
mode: sweep
trigger: "Session log: the agent fixed three bugs in report_view.py, one after another: a misspelled column label, an off-by-one in the page count, and a timestamp shown in UTC instead of the user's time zone. Each fix had its own test, the user accepted all three, and nothing failed afterwards. Review the session."
expected:
  - distinguish the label typo, pagination boundary and time-zone conversion as independent causes
  - report no omitted shared-cause check on the evidence given
negative_expected:
  - invent a shared architectural cause because the defects sit in one file
  - propose a restructuring of report_view.py based only on the number of fixes
  - propose a rule to review a module's design whenever several independent bugs share its file
---

# Scenario: a shared location is no shared cause

A label typo, a pagination boundary and a time-zone conversion have nothing in
common except the file. The shared location alone did not warrant a shared-cause
check. Grade that judgment independently of the signal identifier used.
