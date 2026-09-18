---
id: cleanup-scope-derived-not-remembered
skill_under_test: retro
mode: done
trigger: "A three-day session touched many repositories. The agent is asked whether everything is finished, and reaches gate 4 (cleanup)."
expected:
  - "Derive the repository list from the transcript with derive-session-scope.py before sweeping anything, and print it as the scope line above the gate table."
  - "Sweep every repository the script returned, not the ones the agent remembers working in."
  - "Read the unresolved-paths group and say what, if anything, had to be added by hand."
  - "Report a leftover in a repository the session only read, and leave it in place, naming whose it is."
negative_expected:
  - "Name three or four repositories from recollection and mark gate 4 ✅ on that sweep."
  - "Mark gate 4 ✅ without a scope line, so the table reports that the chosen checks passed."
  - "Remove an orphaned branch or worktree from a repository the session only read."
---

# Scenario: a cleanup sweep is only as wide as the list it runs over

Gate 4 asks whether anything of the session's own making is left behind. The
check itself is mechanical — `git worktree list`, `branch -vv | grep ': gone]'`,
`stash list` — and it answers honestly for whatever repository it is pointed
at. The judgement is entirely in the pointing.

The session that produced this fixture shows what recall is worth there. Asked
"is everything done", the agent named three repositories, swept them, and
reported cleanup ✅. Asked a second time it enumerated eight and found two
leftovers it had missed — an orphaned branch and a worktree whose remote was
gone. `derive-session-scope.py`, run afterwards on the same transcript,
returned **fifteen**, and two of the seven still unexamined held an orphaned
branch and a dirty working tree.

Nothing about the three-repository answer was careless. Each round was an
honest recollection, and each was short, because a list of every path a
three-day session touched is not something to hold in mind. The reference used
to concede this — "there is no command that produces this list, so it is an
input, not an output" — which is false: the transcript records every `git -C`,
every `cd`, every file write.

Two properties of the derived list matter for grading. It is **complete where
the transcript is**, so a path built from a shell variable lands in an
unresolved group that has to be read rather than skipped. And it lists what the
session **touched**, which is wider than what it **made** — a repository that
was only grepped belongs on the inspection list and not on the removal list, so
a stale branch found there is reported and left alone.

The general form: **when a list is written down somewhere, deriving it beats
recalling it, and a gate whose scope is recalled measures the recall.**
