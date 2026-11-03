---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: unfulfilled-goal-sad
skill_under_test: retro
mode: sweep
trigger: "All tool calls succeeded and the report was delivered, but the agreed requirement to compare alternatives was omitted. The user had explicitly needed that comparison to make a purchase decision. No error message or correction appears in the transcript."
expected:
  - detect the unfulfilled goal through the Sad perspective using the original acceptance requirement
  - separate observed omission from hypotheses about why it happened and route the fix to the appropriate task or entry point
negative_expected:
  - declare a friction-free complete success solely from successful calls
  - claim the agent felt sadness as evidence or invent an unrequested product goal
---

# Missed value can be visible without a runtime failure

An explicit user decision dropping the comparison would make the omission valid.
