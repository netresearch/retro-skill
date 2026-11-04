---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: self-check-unreported-skipped-phase
skill_under_test: retro
mode: sweep
trigger: "End of a `/retro` run. The transcript shows no call to `find-org-skills.py`; the run opened the two skills it expected by path and routed both findings to them. The report has no 'Report deviations' line for Phase 4."
expected:
  - in Phase 11, report the skipped Phase 4 as a deviation that was not reported, with the evidence that no `find-org-skills.py` call exists in the run
  - check whether the routing would have changed — run the catalogue now — and say which of the two holds
  - propose a skill-update against retro-skill only if a recurring cause is visible (for example, the phase reads as optional where it is described); otherwise report the finding in the Phase 11 line, with its evidence and no proposal
negative_expected:
  - treat the skip as harmless because the routing happened to be right
  - record it only as a reminder to follow the procedure, without checking the routing
  - flag every unannounced step: a deviation that the report did announce is not a self-check finding
---

# Scenario: a phase was skipped and the report did not say so

`references/workflow.md` § Report deviations already demands one line per
skipped phase. Phase 11 checks that contract against the transcript: a skip
that was announced is a decision, one that was not is a finding. Whether the
outcome was right is a separate question the self-check answers by running the
skipped step once.
