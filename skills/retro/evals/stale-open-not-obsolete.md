---
id: stale-open-not-obsolete
skill_under_test: retro
mode: outcome
trigger: "In `/retro outcome`, a merge request has been open as a draft for two months, has conflicts, and is titled 'complete migration to Pages'. The classifier is about to report it as obsolete and propose closing it."
expected:
  - refuse to classify the stale-open MR as obsolete from metadata (age, conflict flag, title keyword) alone
  - read the MR diff AND the current state of the target branch before judging it
  - conclude 'blocked, not dead' when the target branch does NOT yet contain what the diff would do
  - surface the precondition that blocks it (the cutover) instead of proposing a close
  - treat a still-open PR/MR as undecided — not a D-signal (neither D3 closed-without-merge nor a failure)
negative_expected:
  - propose closing the MR because it is old / conflicted / superseded-sounding
  - treat 'has_conflicts' or a long-open age as evidence the change is unwanted
  - equate a migration/cleanup title with the work being done already
  - skip reading the diff and the target branch
---

# Scenario: stale-open is not an outcome

A long-open PR/MR is *undecided*, not rejected — see
[Stale-open is not an outcome](../references/friction-catalog.md#stale-open-is-not-an-outcome).
The trap is that a dead change and a blocked
cleanup change share the exact same metadata: old, conflicted, a
"drop/migrate/complete" title. The only thing that separates them is the diff
and whether the target branch already contains what the diff would do.

Here the migration-completion MR is the finish line waiting on a cutover, not
an abandoned artefact. The correct classification is "blocked", and the useful
output is the blocking precondition — never a proposal to close.
