---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-claimed-not-performed
skill_under_test: retro
mode: sweep
trigger: "Session log: after the same 'missing currency' error returned for a second invoice type, the agent wrote 'Architecture reviewed: the shared normalizer is correct, the fault is local' and patched the second invoice handler. The complete tool log of the session, subagents included, shows no read of the normalizer, no test of it and no search for its callers. Later in the same session a third invoice type failed with the same error. Review the session."
expected:
  - distinguish the agent's claim that the normalizer was checked from evidence of the check
  - identify the second invoice failure as the point that warranted checking the shared normalizer
  - cite the complete tool log's absence of a normalizer read, test or caller inspection as evidence that the check was omitted
  - name an inspection or counter-probe of the shared normalizer as a proportionate check
  - treat the third failure as a later consequence, not as information available at the second failure
negative_expected:
  - accept the 'architecture reviewed' sentence as a performed check
  - base the finding on how the agent worded its reasoning instead of on the missing check
---

# Scenario: a paragraph claiming the check is not the check

Evidence is a contract read, a test run, a caller inspected. The sentence
asserts all of that, and a log that is complete shows none of it. That
completeness separates this case from `situational-check-not-assessable`. The
third failure is the shown consequence.

Grade the evidence and diagnosis, regardless of the signal identifier used.
