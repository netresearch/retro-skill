---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: sweep-fast-exit-not-on-autonomous-run
skill_under_test: retro
mode: sweep
trigger: "`/retro` with no argument after a session with one user prompt (\"migrate the CI to the new runner image\"), after which the agent worked alone. Phase 1: `detect-mechanical.py` exited 0 with `coverage.status` `supported`, `findings_total` 0, `user_messages` 1, `tool_uses` 58. Phase 1b: `collect-review-findings.py` exited 0 with `complete: true`, no findings, no unresolved forge commands and three transcripts (two subagents)."
expected:
  - do not take the fast exit, and name the conditions that fail (58 tool uses above 10, three transcripts instead of one)
  - run the full Sweep, including the B16–B21 learning scan over the autonomous work
negative_expected:
  - take the fast exit because `findings_total` is 0 and there is only one user message
  - treat the empty pre-pass as evidence that the session holds no learning
samples:
  - "No fast exit: 58 tool uses (limit 10) and 3 transcripts (limit 1); running the full Sweep."
---

# Scenario: one prompt, a long autonomous run

Control for `sweep-fast-exit-short-clean-session`. A clean pre-pass and a
single user message do not make a session short: the tool-use cap and the
single-transcript condition keep the learning scan for this run (ADR-004).
