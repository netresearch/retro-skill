---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: situational-check-not-assessable
skill_under_test: retro
mode: sweep
trigger: "Converted transcript of a Codex session, read alone; no subagent transcripts are among the files read. After a second stale-read failure the main agent delegated 'check whether the cache layer invalidates correctly' to a subagent. The main transcript holds only the subagent's one-line answer, 'cache layer verified, the fault is in the handler', and then the handler patch. Nothing failed afterwards in the session. Review the session."
expected:
  - report the decision point as not assessable and name the missing evidence (the subagent's transcript), leaving no open candidate finding about that check
  - name what would settle it, for example reading that subagent's transcript
negative_expected:
  - file a B22 finding because the main transcript shows no read of the cache layer
  - count the decision point as a performed check on the strength of the one-line answer alone
---

# Scenario: missing evidence is neither a finding nor a pass

The check may have run in the subagent, in a part of the session retro did not
read. The one-line answer is a report of a check, not the check. Not assessable
keeps both readings open and names the file that would decide.
