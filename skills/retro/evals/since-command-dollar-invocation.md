---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: since-command-dollar-invocation
skill_under_test: retro
mode: sweep
trigger: "Phase 11 of a /retro run in OpenCode or OpenChamber runs detect-mechanical.py --since-command retro on the session's own transcript; the invocation was typed as `$retro`."
expected:
  - `--since-command retro` recognises `$retro` at the start of a user message as the invocation and analyses from there
  - a `$retro` quoted or mentioned later in a message does not move the start
negative_expected:
  - exit 2 with "/retro was never invoked", which leaves the self-check without its mechanical input
  - treating `$retrospective` or `$retro-x` as the command
---

# Scenario: `$retro` is the same run as `/retro`

OpenCode and OpenChamber invoke skills with a `$` prefix. Measured on
2026-11-26: the self-check's pre-pass refused the only invocation of the
session.
