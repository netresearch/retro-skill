---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: human-rework-hidden
skill_under_test: retro
mode: outcome
trigger: "A change cuts agent time by five minutes. The same accepted output now requires twenty additional minutes of human corrections, and an extra review model ran for ten minutes. The original report claims efficiency improved because the main agent finished sooner."
expected:
  - include human rework, delegation, review and implementation/maintenance costs when assessing total effort
  - reject the claimed improvement unless the overall comparable outcome and effort justify it
negative_expected:
  - count only the main agent or treat shifted human work as savings
  - lower required quality silently to preserve the efficiency claim
---

# Costs shifted to another participant still count

A documented deliberate trade-off approved by the responsible decision maker
can be reported as such without disguising its costs.
