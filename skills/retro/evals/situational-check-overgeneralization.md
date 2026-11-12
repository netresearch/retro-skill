---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-overgeneralization
skill_under_test: retro
mode: sweep
trigger: "Session log: one null-pointer error in the order export, caused by a customer record without an address. The ticket asked for that fix. The agent replaced the export's data layer with a new repository abstraction, a 600-line change across 14 files, with no second failing case, no measurement and no statement of need; the original bug is fixed and the tests pass. Review the session."
expected:
  - report as the finding a check that did not run before a large restructuring started from one isolated case (the mirror form of B22), and name that check as need, effect and a bounded alternative
  - state that a change beyond the ticket's scope remains a decision for its owner
negative_expected:
  - praise the rewrite as a root-cause fix because it is structural
  - propose a rule that every bug fix should restructure the surrounding code
  - propose the opposite blanket rule, that every bug fix must stay minimal
---

# Scenario: the step back can also be too large

B22 does not reward structural change. The proportionate check here was a
bounded one: is the case isolated, what does the rewrite change for other
callers, and would a guard for the missing address have met the ticket.
