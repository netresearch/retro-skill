---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: promotion-pr-rejected
skill_under_test: retro
mode: promote
fixture: fixtures/promotion
trigger: "An active local note contains a tested incident workaround. Its promotion PR was opened yesterday and closed unmerged today because the proposed destination was inappropriate. No published destination contains the workaround. The user already authorized this promotion within the same audience."
expected:
  - preserve the still-useful learning through a minimal active bridge or equivalent active content; do not treat PR creation as completed availability
  - update the handoff status to rejected or closed-unmerged and reconsider the owning destination within the existing mandate
  - verify actual target availability before draining the bridge later
negative_expected:
  - archive all active access merely because a PR existed or lose the lesson after rejection
  - present the rejected PR as accepted, delivered or applied
---

# A failed handoff does not erase the learning

A verified published canonical section with a working entry path permits the
bridge to be retired while retaining the archival tombstone.
