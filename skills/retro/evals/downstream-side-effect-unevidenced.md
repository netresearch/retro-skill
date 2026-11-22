---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: downstream-side-effect-unevidenced
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in which the agent shortened the debug output of a local test helper, `scripts/dev-check.sh`, from about 400 lines to 20. The script is not called from CI, a hook or any other script; the repository's `AGENTS.md` and `README.md` name it only as a local convenience for the person running it. The session's later test runs were faster to read."
expected:
  - treat the shortened output as a local improvement with no evidenced effect on another role
  - mention at most that no other consumer was found, naming what was searched
negative_expected:
  - invent an operator, reviewer or CI consumer who loses information
  - propose restoring the long output or adding a rule about preserving debug output
  - raise a question to the user about hypothetical other consumers
samples:
  - The script has no caller besides the person running it locally, per AGENTS.md and README.md.
---

# Scenario: no evidenced downstream role, no side-effect finding

Control for `downstream-role-loses-information`. A side effect needs a role
that reads the output; where the records name none, the change stands.
