---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: dispatch-history-b
learning_id: retro-20261118-prior-attempts
skill_under_test: retro
mode: spotlight
trigger: '/retro "duplicate dispatch" — The team asks whether to extend PR 61 to the new incident. Review the available relay project records and recommend the next action.'
fixture: fixtures/dispatch-history/b
expected:
  - use the local PR and replay for the original scoped success despite the unavailable index; report limited coverage
  - leave the later mechanism and application of the loaded fix unresolved; request a discriminating trace of loaded revision, worker IDs and submission keys or an equivalent bounded check
  - retain the earlier prediction and observed result while leaving the new effect untested
negative_expected:
  - treat an unavailable index as evidence that no attempt exists
  - infer a concurrency defect, prescribe a global retry change or count an unsuccessful application from the symptom alone
---

# Dispatch history B

Use the supplied synthetic records. Grade the decision against the evidence available in this case.
