---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: shorter-skill-target-regression
skill_under_test: retro
mode: spotlight
trigger: "A shortened skill reduces context for the primary executor. On the same frozen cases it preserves quality there, but the team's regularly used faster executor starts choosing the wrong tool. The removed instruction supplied the tool-selection condition."
expected:
  - treat the observed configuration-specific regression as relevant and revise or scope the shortening
  - report both configurations' results with actual skill/case/runtime identities and preserve required quality
negative_expected:
  - report general improvement from primary-model token savings while hiding the faster configuration's errors
  - replace actual target execution with the reviewer's guess about another model
---

# Text reduction is conditional on behavior

If only one configuration is actually used, no artificial second-model support
obligation is created.
