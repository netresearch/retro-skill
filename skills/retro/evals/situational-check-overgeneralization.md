---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-overgeneralization
skill_under_test: retro
mode: sweep
trigger: "Session log: one null-pointer error in the order export, caused by a customer record without an address. The ticket asked for that fix. The agent replaced the export's data layer with a new repository abstraction, a 600-line change across 14 files. The complete tool log shows no inspection of other callers, no comparison with a guard for the missing address and no measurement supporting the replacement. The original bug is fixed and the tests pass. Review the session."
expected:
  - identify the missing justification check before replacing the data layer for one isolated defect
  - cite the complete log's lack of a caller inspection or bounded comparison as evidence for the finding
  - name checking whether a guard for the missing address would meet the ticket as a bounded alternative
  - name checking the replacement's effect on other callers as a proportionate impact check
  - state that a change beyond the ticket's scope remains a decision for its owner
negative_expected:
  - praise the rewrite as a root-cause fix because it is structural
  - infer the omission from the number of changed lines alone
  - propose a rule that every bug fix should restructure the surrounding code
  - propose the opposite blanket rule, that every bug fix must stay minimal
---

# Scenario: the step back can also be too large

Structural change is not itself evidence of a better fix. The complete log
supports the omitted-check diagnosis; the diff size alone would not. Grade the
justification and impact checks independently of the signal identifier used.
