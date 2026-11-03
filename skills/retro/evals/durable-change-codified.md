---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: durable-change-codified
skill_under_test: retro
mode: outcome
trigger: "`/retro outcome --since 30d` over a past session whose PR merged 20 days ago, was never reverted or superseded, passed CI, and introduced a non-obvious approach (a caching pattern for an expensive call) that no installed skill currently documents. The same window also contains a second session whose commit was reverted after 3 days."
expected:
  - surface the reverted commit as a D1/D9 outcome candidate and check whether a defect, changed requirement or other cause explains it
  - ALSO surface the merged, unreverted, CI-green change as a D11 positive candidate, describing durability separately from actual use or benefit
  - investigate applicable later opportunities, loaded configuration, application and outcomes before claiming effectiveness; leave unobserved use and benefit unknown
  - allow a bounded positive procedure proposal if the original success and transferable prerequisites justify it, without making its future benefit a proven fact
  - investigate why the other commit was reverted rather than assuming a defect when requirements may have changed
negative_expected:
  - report only the failure (reverted commit) and treat the successful merged change as "nothing to do"
  - codify the merged change even though its approach is local/one-off with no transferable rule (generalizability filter must gate D11)
  - treat merge age, green CI or absence of a revert as proof of application or superiority
  - require a failure or an arbitrary waiting period before considering a bounded first-success learning
---

# Scenario: a durable change is a positive candidate with bounded evidence

D11 preserves the positive side of outcome analysis. A merged change that
survived known checks is worth examining, but it may never have been used.
The reviewer must distinguish implementation, availability, application and
observed benefit. An original successful procedure can justify a scoped
learning without proving superiority or promising future results. A local
one-off remains a valid no-action control.
