---
id: pending-state-memory-is-reverified
skill_under_test: retro
mode: promote
trigger: "A promote run finds a project-type memory whose description reads 'three things the demo needs sit unreleased on main'. It was written a week ago."
expected:
  - "Treat the note as a state claim, not an existence claim, and re-verify whether the thing it says is pending has since happened."
  - "Check the description line first, because it is what MEMORY.md loads into every session."
  - "Propose a tombstone-only drain when the state has resolved, or a rewrite that keeps only the part still true."
  - "Cite the scanner's pending_state / pending_state_in_index fields as the reason the note was examined."
negative_expected:
  - "Skip the stale-check because the note is type project rather than reference."
  - "Pass the note after confirming the named repository and branch still exist."
  - "Promote the note upward with its pending-state description intact."
---

# Scenario: a note that was true is not a note that is true

Every memory records what was true when it was written. Most of those truths
are durable — a lesson, a convention, the location of a file — and checking
them means checking that the thing they name still exists.

A state claim is different. "Blocked", "unreleased", "waits until it is
released": these were true on the day and become false the moment the awaited
thing happens, without a word of the note changing. An existence check passes
them, because the repository, the branch and the command they name all still
exist.

The fixture is a real note. It was accurate on the day it was written, the
blockade it described was resolved the next day, and for a week `MEMORY.md`
carried its description — "the 500, the nr-vault floor and the nr-llm pin all
wait on one unreleased repo" — into every session. Its body stayed historically
correct the whole time; the damage sat entirely in the one line that is always
read. It was found only because the user asked an unrelated question five days
later.

The stale-check in `promote-mode.md` would not have caught it on three counts:
it was scoped to `reference` notes and this one was `project`; it runs only at
promote time and a `project` note is not promoted upward; and it asked whether
a path or flag still exists, which this note's claim was never about.

The general form: **ask what kind of claim a note makes before choosing how to
verify it — existence is checked by looking, state is checked by asking whether
the awaited thing has happened.**
