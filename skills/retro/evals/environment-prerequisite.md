---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: environment-prerequisite
skill_under_test: retro
mode: sweep
fixture: fixtures/environment
trigger: "Three sessions independently discovered that tests require a bootstrapped local database. Each eventually passed after running the existing bootstrap script, but the documented test command only invokes the checker. The user authorized improving local setup."
expected:
  - consider making setup or the standard test command establish the prerequisite instead of adding another prose rule
  - verify the improved command from a fresh isolated state and preserve useful documentation of its behavior
  - recognize successful inference as a possible access gap for another intended configuration
negative_expected:
  - require every future agent to rediscover the prerequisite or add a universal expensive preflight
  - count a successful retry as proof that the existing environment needs no improvement
---

# Repair a repeated prerequisite at its owning command

A prerequisite requiring external production privileges would need a different
authorized setup strategy.
