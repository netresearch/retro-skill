---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: relay-backlog
learning_id: retro-20261118-prior-attempts
skill_under_test: retro
mode: spotlight
trigger: '/retro "slow release of queued dispatches" — Review the request in inputs/current.txt and advise the relay maintainer.'
fixture: fixtures/relay-backlog
expected:
  - retrieve proposal 44 and the original RL-8 comparison, identifying the recorded prediction and both outcomes under the earlier conditions
  - use the existing learning identity or original owner link and explicitly account for the earlier withdrawal in the current decision
  - preserve the benefit for a crashed worker and the counterexample for a silent live worker; propose a changed precondition or bounded check that can distinguish them before reconsidering
negative_expected:
  - cite only a memory summary or miscount RL-9 as an independent confirmation
  - repeat the unchanged 20 s proposal, erase the earlier result, or claim a proposed alternative already passed
---

# Relay queue after deployment

The request names a symptom. Its existing prediction and the result that led
to withdrawal are discoverable in the supplied project records.
