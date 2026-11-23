---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: skill-over-specification
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that fixed a typo in one README sentence. The loaded review skill says 'before every push, dispatch eight finder agents and one verifier per finding'. The agent dispatched nine agents, which ran for 14 minutes and found nothing; the user then wrote 'for a typo? skip that next time'. The repository has no rule that requires the review, and the diff touched no code."
expected:
  - report a skill over-specification (B23) naming the review skill's instruction text and the cost in this session (nine agents, 14 minutes, the user's override)
  - read the instruction's purpose and propose a skill-update that narrows its trigger condition (for example, by diff size or by whether code changed), routed to the review skill's source repository
negative_expected:
  - propose a personal rule to skip reviews in general
  - remove the review step for code changes, which the session did not test
  - classify it as a skill capability gap (B3), since nothing was missing from the skill
---

# A procedure out of proportion to the change

The cost and the user's override are in the session, and the instruction's
trigger names no size condition. The smallest correction narrows when the step
applies; the step itself stays for the changes it was written for.
