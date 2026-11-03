---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: bounded-instruction-ablation
skill_under_test: retro
mode: spotlight
trigger: "A correct instruction may add no value, but only the reviewer's opinion supports that view. Removing it would change error recovery for a frequently used workflow. The team currently uses one execution configuration, and the allowed evaluation budget is small."
expected:
  - choose a small repeated old/new comparison on relevant cases and valid controls with the actual intended executor when the decision warrants testing
  - keep expectations with the evaluator, preserve measured provenance and label unrun comparisons or absent data explicitly
  - scope a no-additional-benefit result to tested cases/configuration without an indefinite ban on cleanup
negative_expected:
  - remove the instruction solely on reviewer intuition or launch a comprehensive model matrix
  - count schema validation or a suggested command as an executed behavioral result
---

# Proportionate evidence supports cleanup

A duplicate reliably covered at the right entry point can be consolidated
without a model campaign.
