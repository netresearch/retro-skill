---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: rule-tally-window-too-small
skill_under_test: retro
mode: audit
trigger: "`/retro audit --scope project` ran `scan-cross-session.py --rule-tally AGENTS.md --project=<slug> --days 7`: sessions_scanned 6, window_sufficient false, never_applicable null, and 11 measured rules show applicable_sessions 0."
expected:
  - "propose no removal candidate from this run, because the window is below --min-sessions"
  - "say that a longer window is needed before C7 can name candidates"
negative_expected:
  - "list the 11 rules with zero hits as never applicable or as removal candidates"
samples:
  - "Six sessions are below the threshold; C7 names no candidates."
---

# Scenario: too few sessions for a zero to mean anything

This is the control for
[rule-never-applicable-is-a-candidate](rule-never-applicable-is-a-candidate.md).
The script withholds `never_applicable`; retro must not rebuild the list from
the per-rule zeros.
