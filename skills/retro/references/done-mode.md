# Done Mode — `/retro done`

Every other retro mode asks *what did we learn*. Done mode asks *are we actually
finished* — and refuses to say so until seven gates hold with evidence. It
exists because "done" was being declared with the retro not run and the time
not booked: the original task was complete, the session was not.

It is a **gate**, not a detector: it reuses the pipeline's approval and
materialization phases (8–10) for the writes it triggers (bookings, ticket
comments) and chains the Sweep for gate 3 when no retro has run yet.

## The seven gates

A gate is ✅ only with evidence from the system that owns the truth — a status
read back, a URL, a command's output — never from what the agent remembers
doing. ⏸ means waiting on the user (a decision, a ticket key). ❌ means work
remains, and the report names it.

| # | Gate | Evidence that closes it |
|---|------|-------------------------|
| 1 | **Task** — the original request, as the user phrased it, is delivered | Every artefact named with its live state: PR/MR (state, checks, threads, `mergeStateStatus` / `detailed_merge_status`), issue, tag, deploy. "I pushed" is not a state. |
| 2 | **Findings** — every interim finding is *fixed*, *filed* or *rejected* | One row per finding: fixed (commit SHA) · filed (issue/ticket URL in the row — "filed" without a URL is not filed) · rejected (one-line reason the user has seen). |
| 3 | **Retro** — the Sweep ran for this session | Proposals shown, each approved/edited/rejected, approved ones materialized (PR URL, rule text re-read). If no Sweep has run, Done mode runs it now — Phases 1–10 — before continuing. |
| 4 | **Cleanup** — nothing of the session's own making is left running or lying around | The sweep list below, each line with its command output. |
| 5 | **Questions** — nothing is pending on the user that the task still needs | Either no open question, or exactly one human-gated decision stated once with the exact command, and the loop stopped there. Re-listing a parked decision is a ❌. |
| 6 | **Tickets** — every ticket touched carries the outcome | Per ticket: comment with what/why/evidence, assignee or reviewer set, transition done or hand-back posted; the last work summary is current (`netresearch-jira` › QA Best Practices › keep the work summary current). |
| 7 | **Time** — every day of the session is booked | TimeTracker entries listed per day with ticket, project, activity, minutes. See *Booking* below. |

## Cleanup sweep (gate 4)

Run all of it; a subset is how "cleaned up" turns out false.

```bash
pgrep -af 'php -S|node|python -m http'          # servers an agent started
docker ps -a                                    # containers (e2e, db, apache)
git worktree list                               # per repo touched this session
git branch -vv | grep ': gone]'                  # local branches whose remote is gone
git stash list                                  # per repo — survives every worktree
ls -d /tmp/phpstan /tmp/cache/PHPStan /tmp/rector_cached_files 2>/dev/null
du -sh "$SCRATCHPAD"/*                          # scratch disk
```

Plus: subagents stopped (`TaskStop`), background watchers ended, no `/loop`
armed. **Before removing a worktree or branch:** `git status --porcelain`,
`git stash list`, `git cherry -v origin/main <branch>` — anything unpushed
stays, and the report says so.

**Stashes are their own row, not a footnote to worktree removal.** They live in
the repository, not in a worktree, so a repo can report a clean tree, no
worktrees and no stray branches while still holding them — and a stash whose
branch is gone is invisible from every other check. Read each one before
dropping it: `git stash show --stat`, then look for its content in the target
(`git stash show -p | grep '^+'` and search a distinctive line on `main`).
Three stashes from March, April and June were each already merged by another
route; the SHA goes in the report so the drop stays reversible.

**Three more rows the obvious list misses.** Each one produced a false "all
done" in the session this mode came out of:

| Check | Why it is not covered above |
|---|---|
| Memory-store consistency: no orphaned notes, no dead index links | A note deleted this session can leave `[[wikilinks]]` in surviving notes; an unindexed note is invisible at session start although the file exists |
| **Author** of every open PR before classifying it | "Renovate handles those" was wrong for one of five — it was an own PR with 14 red checks, waved through by the label rather than read |
| Consumer cache after a release (`~/.claude/plugins/cache/<marketplace>/<skill>/`) | A published release is not an installed one; "consumers have the fix" is false until the cache shows the version |

## Booking (gate 7)

- **TimeTracker, never a Jira worklog.** TimeTracker (`tt` MCP, `log_time`)
  syncs into Tempo; a direct Jira worklog double-books.
- **Per day, not per session.** A session can span days; derive the days from
  commit timestamps, scratch-file mtimes and the transcript, not from "today".
- **`get_day` immediately before every `log_time`** — a parallel session may
  have booked the same window (or your own work) already.
- **Project/activity from precedent:** `list_recent_entries` (write the result
  to a file and `jq` it — it overflows the context), match the ticket prefix.
- **Dual-write:** `agentWalltimeMinutes` + `humanMinutes` + `touchpoints`
  (`prompts`, `reviews`, `interventions`), description ≤255 characters, factual.
- **No ticket, no booking.** If the ticket key is unknown, search the tracker
  (JQL: `project = "<KEY>" AND text ~ "<repo>"`) before asking; if still
  unknown, gate 7 is ⏸ with the proposed entries, and the report asks once.

## Forge and tracker bindings

| System | Read the state with | Write with |
|--------|---------------------|------------|
| GitHub | `git-workflow`'s `pr-status.sh -R owner/repo <pr>` (checks, reviews, rulesets, threads, `NEXT:`) | `gh pr edit/comment`, `gh issue create`, GraphQL `resolveReviewThread` |
| GitLab | `glab api projects/:id/merge_requests/<iid>` → `detailed_merge_status`; `…/discussions` for unresolved threads (`pr-status.sh` is GitHub-only) | `glab mr note`, `glab issue create` |
| Jira | `netresearch-jira` conventions; status + assignee from the issue itself | comment, transition, assignee |
| TimeTracker | `get_day`, `list_recent_entries` | `log_time` (dual-write) |

## Pipeline mapping

- Phases 1–3 (detection) are skipped — announce it in one line — unless gate 3
  triggers the Sweep, which then runs in full.
- Phase 8 (approval) applies to every write Done mode proposes: each booking,
  each ticket comment, each worktree removal with anything unpushed.
- Phase 10 report is the gate table; the word **done** appears only when all
  seven rows are ✅.

## Report format

```
| # | Gate      | State | Evidence / next step |
|---|-----------|-------|----------------------|
| 1 | Task      | ✅    | PR #174 OPEN, 71/71 checks, 0 threads, CLEAN; assignee aseemann |
| 2 | Findings  | ✅    | 2 filed: #175, #176 · 1 fixed: 234b50b · 0 rejected |
| 3 | Retro     | ✅    | 5 proposals: 4 approved (PRs …), 1 rejected |
| 4 | Cleanup   | ✅    | 0 containers, 0 stray processes, worktree pr169 removed, pr174 kept (PR open) |
| 5 | Questions | ✅    | none; CI wiring parked by user (stated once) |
| 6 | Tickets   | ✅    | #174 hand-back comment, assignee set |
| 7 | Time      | ⏸    | 26.08 12:44–14:48 → NEXT-81 proposed; ticket confirmation pending |
```

A ⏸ or ❌ row ends the report with what is needed to close it — not with
"erledigt".

## Boundaries

**Never:** merge, tag or deploy from Done mode (those are the task's own,
explicitly authorized steps); book time without a ticket; dismiss a scanner
alert to turn a gate green; delete a worktree or branch holding unpushed
commits; declare done with a ⏸ or ❌ in the table.

**Ask first:** the ticket key when no precedent exists; removal of anything
with unpushed work; any ticket transition that closes a ticket someone else
owns.

## Evals

`../evals/done-gate-holds-on-unbooked-time.md` — the gate must refuse "done"
when the retro or the booking is missing, even though the code task is
complete.
