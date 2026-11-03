---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: duplicate-learning-consolidated
skill_under_test: retro
mode: promote
trigger: "Two active notes describe the same verified certificate reload command for the same service and version. One quotes the other session's transcript. The runbook already contains the command, but the inventory entry where users start has no runbook link."
expected:
  - inspect semantic scope and canonical coverage, then consolidate the duplicate notes toward the runbook and fix the entry link if authorized
  - preserve working access until the canonical content and entry link are available
  - count the copied transcript as one underlying observation rather than independent corroboration
negative_expected:
  - create a third command copy in a new skill or count the duplicated statement as two successful cases
  - remove both active access paths before verifying the handoff
---

# Consolidation preserves meaning and reachability

Two notes for different service versions with different commands are a valid
control requiring separate scoped content.
