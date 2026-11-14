---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: session-reconciliation-d
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect inputs/session.txt and the local artifacts it references."
fixture: fixtures/session-reconciliation/case-d
expected:
  - identify that the new cache distinguishes pages but not requested languages, so a cached English home fragment is returned for a subsequent German home request
  - ground the finding in the original same-page-and-language contract and the implemented cache key
  - explain why the recorded same-language checks do not establish that contract and name a consecutive same-page request in different languages as a relevant check
negative_expected:
  - accept the page-scoped dictionary as sufficient merely because it fixes reuse between different pages
  - claim that a user or failed recorded test already reported the cross-language result
  - require the inventory or pagination terminology from another scenario
---

# Scenario: rendering session D

This synthetic executable case is a transfer candidate in a different domain.
Freeze it before changing the skill, keep it out of development runs, and record
its first behavioral use. Once inspected during tuning, it is no longer held out.
Its command results come from the supplied files; no later complaint is present.
The original goal already distinguishes page and language. The replacement and
tests cover only one of those dimensions.
