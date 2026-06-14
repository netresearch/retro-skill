---
id: conflicting-skill-instructions
skill_under_test: retro
mode: spotlight
trigger: "A skill says 'always squash-merge' in one section and 'use merge commits to preserve signatures' in another; the agent followed the wrong one."
expected:
  - identify the two instructions as contradictory (the root cause is a conflict, not a missing rule)
  - propose a bounded edit that resolves the conflict — prefer removing or superseding the obsolete side over adding a third instruction
  - prefer a taxonomy/reference cleanup when the conflict spans multiple reference files
  - reference both conflicting locations in the proposal so the edit is reviewable
negative_expected:
  - add a third, broader instruction on top of the two conflicting ones
  - silently pick one side without flagging the contradiction
  - route it to new-skill
---

# Scenario: conflicting skill instructions

When two instructions conflict, the fix is reconciliation, not addition — the
anti-overfitting instinct ("prefer deletion over another exception") applied in a
single pass. retro should name both sides, propose removing or superseding the
stale one, and keep the edit bounded. If the conflict lives across reference
files, propose the reference/taxonomy cleanup rather than patching SKILL.md prose.
