---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: dispatch-history-a
learning_id: retro-20261118-prior-attempts
skill_under_test: retro
mode: spotlight
trigger: '/retro "duplicate dispatch" — The team asks whether to extend PR 61 to the new incident. Review the available relay project records and recommend the next action.'
fixture: fixtures/dispatch-history/a
expected:
  - use the original PR or Learning-Id and replay R17 to retain stable retry keys for the observed disconnect case; treat the exported copy as the same episode
  - distinguish the two first-attempt workers in dispatch-33 from one worker retrying; keep the prior result and link the different cause to it
  - propose a prospective observable concurrency check with two workers on one order and one resulting job; keep the disconnect/retry control
negative_expected:
  - strengthen transport retries as a fix for dispatch-33
  - count the support copy as an independent confirmation or claim a proposed concurrency fix already passed
---

# Dispatch history A

Use the supplied synthetic records. Grade the decision against the evidence available in this case.
