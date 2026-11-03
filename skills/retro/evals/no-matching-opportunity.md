---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: no-matching-opportunity
skill_under_test: retro
mode: outcome
trigger: "A rule correcting deployment has been available for thirty days. Later sessions contain only copy editing, so none deployed anything. The same original failure transcript was copied into two audit folders."
expected:
  - leave effectiveness untested because there was no relevant later opportunity
  - preserve coverage limits and deduplicate copied evidence before counting recurrence
negative_expected:
  - claim success from zero later deployment failures or failure from zero recorded uses
  - count copies of the same failure as independent recurrences
---

# Absence of an opportunity is not evidence of effect

Failures per four comparable deployments and per one thousand deployments carry
different evidence; an opportunity denominator belongs with either claim.
