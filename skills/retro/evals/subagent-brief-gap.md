---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: subagent-brief-gap
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session whose main loop had already read `docs/testing.md`, which says the test suite runs with `make test-in-docker`. It then dispatched an implementation subagent with a brief that named the task and the files but not the test command. The subagent's transcript shows it running `pytest` (import errors from missing services), then `npm test`, then searching for a Makefile, then 9 minutes later finding `docs/testing.md`. The brief came from the template in the orchestration skill, which has fields for task, files and output but none for verification commands."
expected:
  - report a brief gap (B24) with the evidence from the subagent's transcript and the fact that the caller held the test command
  - route a skill-update to the orchestration skill's brief template, adding a field for the verification command
negative_expected:
  - route the finding to the subagent's own behaviour, for example a rule to read docs/ first
  - propose a project-rule that duplicates docs/testing.md in AGENTS.md as the only change
  - report the subagent's opinion of its brief, which a finished agent cannot give
---

# The caller knew what the brief left out

The main loop had read the fact; the brief template had no place for it. The
repair belongs to the template that produced the brief.
