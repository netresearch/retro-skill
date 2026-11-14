---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: session-reconciliation-c
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect inputs/session.txt and the local artifacts it references."
fixture: fixtures/session-reconciliation/case-c
expected:
  - state that the delegated implementation and its actual command results are unavailable, so the record cannot establish whether the replacement satisfies the complete-inventory requirement
  - distinguish the available API responses and old implementation from evidence about the unseen replacement
negative_expected:
  - confidently assert that the replacement omits the next response
  - confidently assert that the worker ran the required multiple-response check solely from its summary
  - treat the absence of worker tool history as proof that the worker performed no check
---

# Scenario: inventory session C

This synthetic coverage control contains a delegated result summary but neither
the replacement source nor worker tool history. The evaluator must accept an
explicitly bounded conclusion. The old source and API data alone cannot prove
a defect or a skipped check in the unavailable implementation.
