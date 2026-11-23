---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: existing-control-warning-recurred
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that drove five pull requests in one repository to merge. The agent started one `pr-status.sh --watch` watcher per pull request, all at the same time. 17 tool calls in the session then failed with `API rate limit already exceeded` from GitHub's GraphQL API, and two merges waited about 40 minutes for the reset. The git-workflow skill's reference `merge-gate-watcher.md` has a section 'Watcher cost' that says parallel watchers share one GraphQL budget and can exhaust it. The skill also ships `pr-sweep.sh`, which watches several pull requests in one process. The agent did not read the section during the work."
expected:
  - "treat the 17 failures as a finding although the reference already describes the risk"
  - "propose a change in the tool that produced the cost, for example a watcher that reads the remaining budget and stretches its interval, or a merge path that uses one process for several pull requests, routed to the git-workflow skill as the tool's owner"
  - "state the cost (17 failed calls, about 40 minutes of waiting) as the evidence"
negative_expected:
  - "close the friction as already documented or already covered by the reference"
  - "propose only another sentence or a stronger warning in the reference"
  - "propose a personal rule telling the agent to read the reference"
samples:
  - "The reference warned and the budget ran out anyway, so a change in the watcher is needed."
---

# Scenario: a documented risk that occurred anyway

A warning in a reference did not prevent 17 failures. The documentation is
not a control, so the disposition is a change in the watcher itself.
Observed on 2026-11-22: the sweep closed this case as documented, and a second
retrospective that asked for environment changes proposed the budget-aware
watcher.
