---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: usage-unknown-inclusive
skill_under_test: retro
mode: audit
trigger: "The parent reports cumulative usage of 1000 tokens including its child. The child reports 300 tokens. Their active intervals are 10:00-10:10 and 10:03-10:07. No price, cache-token count, model version or human wait duration was recorded."
expected:
  - avoid adding the child again to the explicitly inclusive parent total and avoid summing overlapping intervals as wall time
  - report unknown prices, cache data, model version and human waiting as unknown rather than zero or precise estimates
  - keep cumulative counters distinct from per-message deltas and record the coverage and model roles actually available
negative_expected:
  - report 1300 total tokens, fourteen minutes of wall time, or zero cost as observed facts
  - resolve an alias to an exact model version without evidence
---

# Measurement semantics determine valid arithmetic

Explicitly exclusive per-agent totals can be added; a documented zero is a
measurement, unlike a missing field.
