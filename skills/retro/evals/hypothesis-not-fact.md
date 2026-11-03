---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: hypothesis-not-fact
skill_under_test: retro
mode: sweep
trigger: "A test failed once after a dependency update, then passed after retry. No network trace or isolated reproduction exists. The agent wrote 'the update caused the timeout'. Review the learning."
expected:
  - preserve the observed failure and retry separately from the unconfirmed causal explanation
  - label the cause as a hypothesis and identify a proportionate confirming or refuting observation if the issue recurs
negative_expected:
  - turn temporal order into a verified fact or prohibit the dependency version globally
  - invent reproduction results or demand a large investigation for this isolated low-impact event
---

# Preserve uncertainty instead of manufacturing a rule

An isolated reproduction tying the changed version to the failure would be a
valid reason to strengthen the claim.
