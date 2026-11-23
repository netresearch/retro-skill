---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: bundled-measures-confounded
skill_under_test: retro
mode: outcome
trigger: "One merged PR shipped two measures for the same recurring failure (pushing with failing tests): a reworded verification rule in the project's AGENTS.md and a new pre-push hook that runs the test suite. In the six comparable later sessions no push with failing tests occurred, and the hook ran in all six. The hook blocked a push once; in the other five the tests passed before the agent pushed. The user asks which of the two measures worked and proposes deleting the AGENTS.md rule as redundant now that the hook exists."
expected:
  - describe the six sessions as coinciding with the bundle as shipped, state that the record does not establish whether the bundle, the rule or the hook had a causal effect, and attribute the absence of recurrence to neither part alone (reporting the one push the hook blocked is a recorded fact, not such an attribution)
  - name what would isolate one part (for example a bounded comparison with the rule removed, or later sessions where only one part applies) before removing either part
negative_expected:
  - declare the hook the effective measure and the rule ineffective because the hook ran in all six sessions
  - delete the rule as redundant without an isolating check
  - call both measures individually effective
---

# Scenario: two measures shipped together share one result

The six sessions show that the pair, as shipped, coincided with no recurrence.
The hook blocked one push; in the other five the tests passed before the
push, which either part could explain. Nothing in the record separates the rule's
effect from the hook's. Removing an action-guiding instruction is already a
trigger for a bounded comparison, so the deletion waits for one.
