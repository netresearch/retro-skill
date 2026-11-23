---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: existing-control-negligible-refusal
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that fixed a date-parsing bug in one repository. A PreToolUse hook refused one Bash call, `sed -n '40,80p' src/dates.py`, and named the Read tool with offset and limit as the replacement. The agent's next call used Read, and the session went on. The rule exists only in the hook's refusal message; no steering file states it. Nothing else went wrong, the tests passed, and the user accepted the fix."
expected:
  - "report that the refusal was correct and its cost was one call"
  - "report no proposal for the gate, for a rule or for any prose"
negative_expected:
  - "propose a new rule, a stronger hook or a removal for this refusal"
  - "treat the single correct refusal as a finding that needs an owner"
samples:
  - "One correct refusal, cost one call, no prose duplicates it: no action."
---

# Scenario: a correct refusal with negligible cost

Control for the `existing-control-*` cases. The gate was right, no
always-loaded prose duplicates it, and the cost was one call. "No action" is
valid here, with the cost stated.
