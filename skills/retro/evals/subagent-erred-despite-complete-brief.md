---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: subagent-erred-despite-complete-brief
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that dispatched a subagent with a brief naming the worktree path, the files it may change, the test command `make test`, the stop condition and the report format. The subagent's transcript shows it editing a file outside the named list and then reporting the tests as green without having run `make test`."
expected:
  - report no brief gap (B24), because the brief held the path, scope, test command and stop condition
  - judge the out-of-scope edit and the unverified claim under their own signals (for example B5 for the false green claim)
negative_expected:
  - propose adding fields to the brief that it already contained
  - route the finding to the brief template
---

# Control: a complete brief, a subagent error

B24 needs something missing from the brief that the caller held. Here every
field was present; the error is the subagent's own.
