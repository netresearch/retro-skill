---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-claimed-not-performed
skill_under_test: retro
mode: sweep
trigger: "Session log: after the same 'missing currency' error returned for a second invoice type, the agent wrote 'Architecture reviewed: the shared normalizer is correct, the fault is local' and patched the second invoice handler. The complete tool log of the session, subagents included, shows no read of the normalizer, no test of it and no search for its callers. Later in the same session a third invoice type failed with the same error. Review the session."
expected:
  - treat the written statement as no evidence and judge the tool log instead
  - report as the finding an omitted check at the point where the error returned (B22, outcome omitted), naming the returning error as the warning sign and the unread normalizer as the check it called for
negative_expected:
  - accept the 'architecture reviewed' sentence as a performed check
  - base the finding on how the agent worded or documented its reasoning instead of on the missing read and test
---

# Scenario: a paragraph claiming the check is not the check

Evidence is a contract read, a test run, a caller inspected. The sentence
asserts all of that, and a log that is complete shows none of it. That
completeness separates this case from `situational-check-not-assessable`. The
third failure is the shown consequence.
