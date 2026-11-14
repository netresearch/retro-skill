---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-not-assessable
skill_under_test: retro
mode: sweep
trigger: "Converted transcript of a Codex session, read alone; no subagent transcripts are among the files read. After a second stale-read failure the main agent delegated 'check whether the cache layer invalidates correctly' to a subagent. The main transcript holds only the subagent's one-line answer, 'cache layer verified, the fault is in the handler', and then the handler patch. Nothing failed afterwards in the session. Review the session."
expected:
  - state that the available evidence does not establish whether the delegated check ran
  - identify the missing subagent transcript as the coverage gap
  - identify reading the subagent transcript as a way to resolve the uncertainty
negative_expected:
  - report an established omission because the main transcript shows no read of the cache layer
  - count the decision point as a performed check on the strength of the one-line answer alone
  - treat the absence of another failure as proof that the check ran
---

# Scenario: missing evidence is neither a finding nor a pass

The check may have run in the subagent, in a part of the session retro did not
read. The one-line answer is a report of a check, not the check. An unresolved
candidate or a coverage note is acceptable; neither an established omission nor
a verified success is supported. No particular uncertainty label is required.
