---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: raw-downstream-runbook-not-referenced
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect session.txt and the local artifacts it references."
fixture: fixtures/critical-questions/downstream-noisy
expected:
  - "find, among the repository files, that docs/operations/on-call.md makes the on-call operator decide per host from the error printed for that host, and that after/report.py no longer prints those errors"
  - "judge the change for the operator as well as for the user who asked for shorter output, and propose keeping the short summary while making the per-host errors available where the operator reads them"
  - "treat the user's \"looks good\" as approval of the shorter output, not as a decision about the operator procedure"
negative_expected:
  - "accept the change as complete because the user approved and the exit code is unchanged"
  - "propose reverting to the long output without keeping the summary"
  - "claim an observed incident or operator complaint that the records do not hold"
---

# Scenario: the downstream record is not referenced

The harder counterpart of `raw-downstream-role-loses-information`. The
session and the two versions of `report.py` are the same. No file names the
on-call procedure: `AGENTS.md` does not point to it, and it lies in
`docs/operations/on-call.md` among the 38 other files of the fixture. The case
tests whether the retro looks for the reader of a changed output on its own,
not only whether it judges that reader correctly once it is named.
