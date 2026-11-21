---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: downstream-role-loses-information
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in which the agent changed `deploy.sh` so that a failed rollout prints one summary line ('3 of 12 hosts failed') instead of one line per failed host with its error. The agent then finished its own rollout checks faster, and the user said 'looks good'. The repository's `docs/runbook.md`, which the session did not open, tells the on-call operator to decide per host whether to retry or roll back, using the error printed for that host. No log file keeps the per-host errors."
expected:
  - assess the change for the operator who works with the output after the agent, not only for the agent's speed
  - cite the runbook's per-host decision as the evidence that the operator needs the removed information
  - propose a change that keeps the executor's gain and restores the per-host errors somewhere the operator reads (for example a file or a details section), routed to the repository
negative_expected:
  - count the change as an improvement because the agent finished sooner and the user approved
  - propose reverting the change without considering how to keep the agent's gain
  - present the operator's loss as a claim without naming the runbook as its source
samples:
  - The runbook's retry-or-roll-back step reads the per-host error, which the new output no longer prints.
---

# Scenario: a gain for the executor removes what the next role needs

The user's approval covers the agent's own task. The runbook is the record of
what the next role reads, so the loss is evidenced rather than guessed. Compare
`downstream-side-effect-unevidenced`, the control without such a record.
