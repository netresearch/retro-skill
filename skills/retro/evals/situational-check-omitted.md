---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-omitted
skill_under_test: retro
mode: sweep
trigger: "Session log: the agent fixed a CSV import that rejected semicolon-delimited files by adding a branch in the parser. Two turns later a tab-delimited file failed with the same message, 'unknown delimiter', raised by the shared detect_delimiter() function; the agent added a second branch in the importer and a third in the export preview, and never opened detect_delimiter(). Each fix got one test for its own file, and all tests were green. In the next message the user reported that a pipe-delimited file fails the same way. Review the session."
expected:
  - identify the tab-delimited failure as the decision point where a shared-cause check was warranted
  - cite the repeated error from detect_delimiter() as information available at that decision point
  - identify the omitted inspection or counter-probe of detect_delimiter() across delimiter variants
  - cite the pipe-delimited failure as a later consequence of the unresolved shared problem
  - distinguish the observed omission from hypotheses about why the agent skipped the check
  - if a skill-update is proposed, name the concrete warning sign that should activate the check
  - if a skill-update is proposed, name the proportionate check it should require
  - if a skill-update is proposed, leave the owning skill to discovery rather than assume one
  - if a skill-update is proposed, include an eval stub that feeds related variants one at a time
  - if a skill-update is proposed, keep further variants held out from the executor
negative_expected:
  - report only repeated failure or user correction without identifying the earlier decision point and missing check
  - treat the green per-file tests as evidence that the fix was complete
  - treat the later pipe-delimited failure as information the agent already had at the earlier decision point
  - assume another instruction is the remedy without considering the cause of the omission
  - propose a rewrite of the whole importer without evidence that the limited check requires it
  - propose a general rule to "always think about the architecture"
---

# Scenario: a returning failure class answered with another branch

The second failure carried the same message from the same shared function. That
made the shared cause visible at the time, and one read of that function was a
proportionate, runnable check. The pipe-delimited failure is the evidence that
the per-example fixes missed the shared property.

A correct diagnosis under an existing signal passes. The signal identifier and
the wording used for the omission are not grading criteria.
