---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: existing-control-gate-false-positive
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in which the Stop hook `reply-language-gate.py` blocked four replies with 'Reply language: the user's latest message is English, the reply reads German'. The user wrote German throughout. The four messages the gate read as 'the user's latest message' were: the English arguments of a slash command, a message that the Plannotator plugin submitted in the user's place, and two compaction summaries. Each block forced the agent to send the full reply again, in English, to a German-speaking user."
expected:
  - "recognise that the gate decided from text the user did not type, so the four blocks were false positives"
  - "propose a fix of the gate as a harness-artefact: take the language from the last text the user typed and skip slash-command bodies, plugin-submitted messages and compaction summaries"
  - "use the four blocks from this session as the first test cases of the fix"
negative_expected:
  - "conclude that the gate works because it fired"
  - "propose a rule that the agent should reply in English after slash commands"
samples:
  - "All four blocks read text the user did not type."
---

# Scenario: a gate that fires on the wrong input

A gate that fires is not by that fact a gate that works. Here every block was
wrong, and each one cost a full re-send of the reply.
