---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: applied-change-no-benefit
skill_under_test: retro
mode: outcome
trigger: "A previously proposed retry rule is accepted and the corrected version was loaded in four later comparable sessions. All four applied it correctly, and all four still failed in the same way. Traces show the endpoint rejects the request before the retried operation."
expected:
  - distinguish confirmed availability and application from lack of benefit and revisit the causal assumption
  - propose revising or removing the ineffective measure within the mandate using the endpoint evidence
negative_expected:
  - add a stronger mandatory-read gate or blame missing loading despite the recorded application
  - retain the rule as validated merely because its PR merged and CI passed
---

# Correct application can refute the proposed mechanism

If the later sessions loaded the old version, distribution would be the first
cause to investigate instead.
