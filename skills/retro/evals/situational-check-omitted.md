---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-omitted
skill_under_test: retro
mode: sweep
trigger: "Session log: the agent fixed a CSV import that rejected semicolon-delimited files by adding a branch in the parser. Two turns later a tab-delimited file failed with the same message, 'unknown delimiter', raised by the shared detect_delimiter() function; the agent added a second branch in the importer and a third in the export preview, and never opened detect_delimiter(). Each fix got one test for its own file, and all tests were green. In the next message the user reported that a pipe-delimited file fails the same way. Review the session."
expected:
  - classify a B22 finding with outcome omitted, anchored at the turn where the tab-delimited file failed with the same message as the first defect
  - name the check that turn called for (read detect_delimiter() and test whether the fixes handle the shared property or only the two examples) and cite the pipe-delimited failure as the shown consequence
  - state the cause in the agent system, or state that this log does not show it and list candidates; an instruction is not assumed to be the remedy
  - if a skill-update is proposed, it names this warning sign and its check, leaves the owning skill to discovery, and carries an eval stub that feeds variants one at a time and holds further variants out
negative_expected:
  - report only a B9 repeated mistake or only the user's correction, without the decision point and the check it called for
  - treat the green per-file tests as evidence that the fix was complete
  - propose a rewrite of the whole importer or a general rule to "always think about the architecture"
---

# Scenario: a returning failure class answered with another branch

The second failure carried the same message from the same shared function. That
made the shared cause visible at the time, and one read of that function was a
proportionate, runnable check. The pipe-delimited failure is the evidence that
the per-example fixes missed the shared property.
