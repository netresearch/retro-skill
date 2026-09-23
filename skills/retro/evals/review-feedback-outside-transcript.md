---
id: review-feedback-outside-transcript
skill_under_test: retro
mode: sweep
trigger: "`/retro` at the end of a session that opened two merge requests. The transcript shows no reviewer comment. `collect-review-findings.py` lists: on the first MR a resolved human review thread ('the variable check runs after the deploy job, so it guards nothing') followed by a fix commit; a human note 'please always link the ticket in the MR title here'; a bot note 'Pipeline passed'. The second MR has no finding, and its branch names a Jira ticket whose owner commented 'can we agree on global rollouts across all projects before they happen?' and moved it from QA back to In Progress. A third, linked issue is listed as NOT READ (HTTP 404)."
expected:
  - run `collect-review-findings.py` on the session transcript before judging B18–B20, because the transcript alone shows no review feedback
  - surface the fixed review thread as B19 (escaped defect) and route it to the check that would have caught it before the push — the skill or gate that owns that check — not only to a sentence describing the fix
  - surface 'please always link the ticket in the MR title here' as B20 (maintainer request) routed to `project-rule` in that repository's `AGENTS.md`
  - surface the ticket comment and the QA → In Progress transition as feedback on the session's work, though neither appears in any MR
  - report the NOT READ issue as unknown and name it, never as an artefact without findings
negative_expected:
  - conclude "no review feedback" from the transcript because no reviewer comment appears in it
  - treat the bot's 'Pipeline passed' note as a finding worth a proposal
  - read the ticket only for its status and skip the comment because the MR itself had no findings
  - fold the NOT READ issue into the count of artefacts with no findings
---

# Scenario: the feedback that never entered the transcript

A review finding is a defect that passed every check the agent ran, which makes
it the most precise learning a retro gets. Most of it arrives where the
transcript cannot see it: a thread answered after the session ended, a bot
review nobody opened, and — in teams that accept work in the ticket — a comment
and a status change on the Jira ticket instead of on the merge request.

`collect-review-findings.py` reads those sources (see
[`../references/friction-catalog.md`](../references/friction-catalog.md)
§ Feedback from outside the transcript, B18–B20). The discriminators under test:

- the escaped defect (B19) is routed to the missing check, because the fix is
  already in the code and the question is why no check found it first;
- the maintainer request (B20) is a convention for one repository, so it goes to
  that repository's rules, not to a skill;
- the ticket is read for its comments even when the merge request is silent;
- an artefact that could not be read stays distinguishable from one that was
  read and had nothing on it.
