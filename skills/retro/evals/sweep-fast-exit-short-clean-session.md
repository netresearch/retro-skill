---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: sweep-fast-exit-short-clean-session
skill_under_test: retro
mode: sweep
trigger: "`/retro` with no argument at the end of a Claude Code session in which the user asked for one typo fix in `README.md` and then wrote \"thanks\". The transcript was located and confirmed by a phrase the user typed. Phase 1: `detect-mechanical.py` exited 0 with `coverage.status` `supported`, `findings_total` 0, `user_messages` 2, `tool_uses` 4. Phase 1b: `collect-review-findings.py`, run without `--scan-since`, exited 0 with `complete: true`, no findings, no unresolved forge commands and one transcript."
expected:
  - take the fast exit after Phase 1b and report a `Fast exit:` line that names each condition with its measured value
  - report one deviation line for the skipped Phases 2–9, the line `B21: none (fast exit)` and the Phase 11 line
  - name `/retro --full` as the way to run the full Sweep
negative_expected:
  - run Phase 2 enrichment, skill discovery or project-harness inspection anyway
  - skip Phases 2–9 without announcing them
  - ask the closing question although no proposal is open
samples:
  - "Fast exit: ~/.claude/projects/<slug>/<session-id>.jsonl, Claude Code, confirmed by token; detector exit 0, coverage supported, 0 findings; collector exit 0, complete, 0 findings, 0 unresolved forge commands, 1 transcript; 2 user messages, 4 tool uses. Run /retro --full for the full Sweep."
---

# Scenario: a short session with nothing to find

Every condition of the fast exit in `commands/retro.md` § Phase 1b holds.
The report is the coverage line, the announced skip, `B21: none (fast exit)`
and Phase 11 (ADR-004).
