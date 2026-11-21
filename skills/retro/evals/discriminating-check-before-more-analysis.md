---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: discriminating-check-before-more-analysis
skill_under_test: retro
mode: spotlight
trigger: "`/retro \"the agent ignored the release checklist again\"`. The release skill's `SKILL.md` contains the checklist. Two explanations are on the table: the skill was not loaded in the session, or it was loaded and the checklist was skipped. The session transcript is available and records every Skill tool call with its name. The user proposes rewording the checklist more forcefully."
expected:
  - name the one check that tells the two explanations apart (whether the transcript records a Skill call for the release skill) and run it before choosing a measure
  - state how the measure differs by result (a not-loaded skill points at its trigger or description; a loaded and skipped checklist points at the checklist or the procedure)
  - not adopt the rewording before that check has been made
negative_expected:
  - reword the checklist without reading the transcript's Skill calls
  - start a broad investigation of other sessions or models when the transcript can settle the question
  - ask the user which explanation is true when the transcript answers it
samples:
  - The transcript's Skill calls show whether the release skill was loaded.
---

# Scenario: the next step is the check that can change the decision

Both explanations are plausible, and they lead to different measures. The
transcript settles which one holds at a cost of one read, so no further
analysis and no question to the user is needed first.
